from __future__ import annotations

import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

import anyio

from .config import ServerSettings
from .errors import PublicToolError
from .models import BrowserCloseReceipt, BrowserPageSummary


class _Route(Protocol):
    async def abort(self, error_code: str | None = None) -> None: ...

    async def continue_(self) -> None: ...


class _Request(Protocol):
    @property
    def url(self) -> str: ...


class _Page(Protocol):
    @property
    def url(self) -> str: ...

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> object: ...

    async def title(self) -> str: ...

    async def evaluate(self, expression: str) -> object: ...


class _BrowserContext(Protocol):
    async def route(
        self,
        url: str,
        handler: Callable[[_Route, _Request], Awaitable[None]],
    ) -> None: ...

    async def new_page(self) -> _Page: ...

    async def close(self) -> None: ...


class _Browser(Protocol):
    async def new_context(
        self,
        *,
        accept_downloads: bool,
        service_workers: str,
        viewport: dict[str, int],
    ) -> _BrowserContext: ...

    async def close(self) -> None: ...


class _BrowserType(Protocol):
    async def launch(self, *, headless: bool) -> _Browser: ...


class _Playwright(Protocol):
    @property
    def chromium(self) -> _BrowserType: ...

    async def stop(self) -> None: ...


class _PlaywrightStarter(Protocol):
    async def start(self) -> _Playwright: ...


class _AsyncPlaywright(Protocol):
    def __call__(self) -> _PlaywrightStarter: ...


@dataclass
class _PageHandle:
    owner: str
    context: _BrowserContext
    page: _Page
    expires_at: float


class BrowserRuntime:
    """Application-owned, isolated browser contexts addressed by opaque handles."""

    def __init__(
        self,
        *,
        allowed_origins: tuple[str, ...],
        max_handles: int,
        handle_ttl_seconds: int,
        navigation_timeout_ms: int,
        max_text_chars: int,
    ) -> None:
        self._allowed_origins = frozenset(allowed_origins)
        self._max_handles = max_handles
        self._handle_ttl_seconds = handle_ttl_seconds
        self._navigation_timeout_ms = navigation_timeout_ms
        self._max_text_chars = max_text_chars
        self._playwright: _Playwright | None = None
        self._browser: _Browser | None = None
        self._handles: dict[str, _PageHandle] = {}
        self._orphaned_contexts: list[_BrowserContext] = []
        self._lock = anyio.Lock()

    @classmethod
    def from_settings(cls, settings: ServerSettings) -> BrowserRuntime:
        return cls(
            allowed_origins=settings.browser_allowed_origins,
            max_handles=settings.browser_max_handles,
            handle_ttl_seconds=settings.browser_handle_ttl_seconds,
            navigation_timeout_ms=settings.browser_navigation_timeout_ms,
            max_text_chars=settings.max_browser_text_chars,
        )

    async def open_page(self, url: str, *, owner: str) -> BrowserPageSummary:
        async with self._lock:
            await self._expire_handles()
            if len(self._handles) >= self._max_handles:
                raise PublicToolError(
                    "The browser handle limit has been reached; close a page first."
                )
            self._require_allowed_origin(url)
            context: _BrowserContext | None = None
            try:
                with anyio.fail_after(self._navigation_timeout_ms / 1000):
                    await self._ensure_started()
                    assert self._browser is not None
                    context = await self._browser.new_context(
                        accept_downloads=False,
                        service_workers="block",
                        viewport={"width": 1280, "height": 720},
                    )
                    await context.route("**/*", self._guard_request)
                    page = await context.new_page()
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self._navigation_timeout_ms,
                    )
                    self._require_allowed_origin(page.url)
                    handle = secrets.token_urlsafe(18)
                    selected = _PageHandle(
                        owner=owner,
                        context=context,
                        page=page,
                        expires_at=time.monotonic() + self._handle_ttl_seconds,
                    )
                    summary = await self._summary(handle, selected)
                    # Transfer ownership only after the caller can receive a usable handle.
                    selected.expires_at = time.monotonic() + self._handle_ttl_seconds
                    self._handles[handle] = selected
                    return summary
            except BaseException as exc:
                if context is not None and not await self._cleanup(context.close):
                    self._orphaned_contexts.append(context)
                if isinstance(exc, PublicToolError) or not isinstance(exc, Exception):
                    raise
                raise PublicToolError("The allowed page could not be opened.") from exc

    async def read_page(self, handle: str, *, owner: str) -> BrowserPageSummary:
        async with self._lock:
            await self._expire_handles()
            selected = self._owned_handle(handle, owner)
            try:
                with anyio.fail_after(self._navigation_timeout_ms / 1000):
                    summary = await self._summary(handle, selected)
            except TimeoutError as exc:
                await self._discard_handle(handle, selected)
                raise PublicToolError("The browser page read exceeded its time budget.") from exc
            except PublicToolError:
                await self._discard_handle(handle, selected)
                raise
            selected.expires_at = time.monotonic() + self._handle_ttl_seconds
            return summary

    async def close_page(self, handle: str, *, owner: str) -> BrowserCloseReceipt:
        async with self._lock:
            selected = self._handles.get(handle)
            if selected is None or selected.owner != owner:
                return BrowserCloseReceipt(handle=handle, closed=False)
            # Retain the handle for retry if close fails.
            if not await self._cleanup(selected.context.close):
                raise PublicToolError("The browser page could not be closed cleanly.")
            self._handles.pop(handle, None)
            return BrowserCloseReceipt(handle=handle, closed=True)

    async def aclose(self) -> None:
        # Shield the lock acquisition and all cleanup from enclosing AnyIO cancellation.
        with anyio.CancelScope(shield=True):
            async with self._lock:
                cleanup_failed = False
                handles = list(self._handles.values())
                orphaned_contexts = list(self._orphaned_contexts)
                self._handles.clear()
                self._orphaned_contexts.clear()
                for selected in handles:
                    if not await self._cleanup(selected.context.close):
                        cleanup_failed = True
                for context in orphaned_contexts:
                    if not await self._cleanup(context.close):
                        cleanup_failed = True
                if self._browser is not None:
                    if not await self._cleanup(self._browser.close):
                        cleanup_failed = True
                    self._browser = None
                if self._playwright is not None:
                    if not await self._cleanup(self._playwright.stop):
                        cleanup_failed = True
                    self._playwright = None
                if cleanup_failed:
                    raise RuntimeError("The browser runtime did not close cleanly.")

    async def _cleanup(self, action: Callable[[], Awaitable[None]]) -> bool:
        try:
            with anyio.fail_after(self._navigation_timeout_ms / 1000, shield=True):
                await action()
            return True
        except Exception:
            return False

    async def _ensure_started(self) -> None:
        if self._browser is not None:
            return
        try:
            from importlib import import_module

            module = import_module("playwright.async_api")
            async_playwright = cast(_AsyncPlaywright, module.__dict__["async_playwright"])
        except ImportError as exc:  # pragma: no cover - optional dependency gate
            raise PublicToolError("Browser support is not installed for this server.") from exc

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except BaseException as exc:
            if self._playwright is not None:
                await self._cleanup(self._playwright.stop)
                self._playwright = None
            if not isinstance(exc, Exception):
                raise
            raise PublicToolError("The isolated browser runtime could not start.") from exc

    async def _summary(self, handle: str, selected: _PageHandle) -> BrowserPageSummary:
        self._require_allowed_origin(selected.page.url)
        try:
            title = await selected.page.title()
            # Read at most twice the Python character budget in UTF-16 code units.
            # Python does the final code-point slice and computes the truncation flag.
            raw_text = await selected.page.evaluate(
                f"(document.body?.innerText ?? '').slice(0, {2 * (self._max_text_chars + 1)})"
            )
        except Exception as exc:
            raise PublicToolError("The browser page is no longer available.") from exc
        self._require_allowed_origin(selected.page.url)
        text = str(raw_text)
        bounded = text[: self._max_text_chars]
        return BrowserPageSummary(
            handle=handle,
            url=selected.page.url[: self._max_text_chars],
            url_truncated=len(selected.page.url) > self._max_text_chars,
            title=title[: self._max_text_chars],
            title_truncated=len(title) > self._max_text_chars,
            text=bounded,
            text_truncated=len(text) > self._max_text_chars,
            expires_in_seconds=self._handle_ttl_seconds,
        )

    async def _guard_request(self, route: _Route, request: _Request) -> None:
        try:
            self._require_allowed_origin(request.url)
        except PublicToolError:
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    def _require_allowed_origin(self, url: str) -> None:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if (
            parsed.username is not None
            or parsed.password is not None
            or origin not in self._allowed_origins
        ):
            raise PublicToolError("The page origin is not allowed by browser policy.")

    def _owned_handle(self, handle: str, owner: str) -> _PageHandle:
        selected = self._handles.get(handle)
        if selected is None or selected.owner != owner or selected.expires_at <= time.monotonic():
            raise PublicToolError("The browser page handle is not available.")
        return selected

    async def _expire_handles(self) -> None:
        now = time.monotonic()
        expired = [handle for handle, item in self._handles.items() if item.expires_at <= now]
        for handle in expired:
            item = self._handles[handle]
            self._handles.pop(handle, None)
            if await self._cleanup(item.context.close):
                continue
            self._orphaned_contexts.append(item.context)

    async def _discard_handle(self, handle: str, selected: _PageHandle) -> None:
        self._handles.pop(handle, None)
        if not await self._cleanup(selected.context.close):
            self._orphaned_contexts.append(selected.context)
