from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from build_an_mcp_server.browser_runtime import BrowserRuntime
from build_an_mcp_server.errors import PublicToolError


class FakeRoute:
    def __init__(self) -> None:
        self.aborted = False
        self.continued = False

    async def abort(self, error_code: str | None = None) -> None:
        assert error_code == "blockedbyclient"
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


class FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class FakePage:
    def __init__(self, text: str) -> None:
        self.url = "about:blank"
        self._text = text
        self.expression = ""

    async def goto(self, url: str, *, wait_until: str, timeout: int) -> object:
        assert wait_until == "domcontentloaded"
        assert timeout == 1_000
        self.url = url
        return object()

    async def title(self) -> str:
        return "Example"

    async def evaluate(self, expression: str) -> object:
        self.expression = expression
        return self._text


class FakeContext:
    def __init__(self, page: FakePage, *, fail_route: bool = False) -> None:
        self.page = page
        self.fail_route = fail_route
        self.closed = False
        self.route_handler: Callable[[Any, Any], Awaitable[None]] | None = None

    async def route(
        self,
        url: str,
        handler: Callable[[Any, Any], Awaitable[None]],
    ) -> None:
        assert url == "**/*"
        if self.fail_route:
            raise RuntimeError("provider detail")
        self.route_handler = handler

    async def new_page(self) -> FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, contexts: list[FakeContext], *, fail_close: bool = False) -> None:
        self.contexts = contexts
        self.fail_close = fail_close
        self.closed = False

    async def new_context(
        self,
        *,
        accept_downloads: bool,
        service_workers: str,
        viewport: dict[str, int],
    ) -> FakeContext:
        assert accept_downloads is False
        assert service_workers == "block"
        assert viewport == {"width": 1280, "height": 720}
        return self.contexts.pop(0)

    async def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("provider detail")


class FakePlaywright:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def make_runtime(browser: FakeBrowser, *, max_handles: int = 2) -> BrowserRuntime:
    runtime = BrowserRuntime(
        allowed_origins=("https://example.com",),
        max_handles=max_handles,
        handle_ttl_seconds=30,
        navigation_timeout_ms=1_000,
        max_text_chars=10,
    )
    untyped_runtime = cast(Any, runtime)
    untyped_runtime._browser = browser
    return runtime


@pytest.mark.anyio
async def test_browser_handles_are_owned_bounded_and_explicitly_closed() -> None:
    page = FakePage("0123456789extra")
    context = FakeContext(page)
    runtime = make_runtime(FakeBrowser([context]))

    opened = await runtime.open_page("https://example.com/docs", owner="caller-a")

    assert opened.text == "0123456789"
    assert opened.text_truncated is True
    assert opened.expires_in_seconds == 30
    assert ".slice(0, 22)" in page.expression
    with pytest.raises(PublicToolError, match="not available"):
        await runtime.read_page(opened.handle, owner="caller-b")
    wrong_owner = await runtime.close_page(opened.handle, owner="caller-b")
    assert wrong_owner.closed is False
    assert context.closed is False
    closed = await runtime.close_page(opened.handle, owner="caller-a")
    assert closed.closed is True
    assert context.closed is True


@pytest.mark.anyio
async def test_browser_metadata_is_bounded_with_explicit_truncation_flags() -> None:
    class LargeMetadataPage(FakePage):
        async def title(self) -> str:
            return "T" * 20

    page = LargeMetadataPage("short")
    context = FakeContext(page)
    runtime = make_runtime(FakeBrowser([context]))

    opened = await runtime.open_page("https://example.com/" + "p" * 20, owner="caller-a")

    assert opened.url == "https://ex"
    assert opened.url_truncated is True
    assert opened.title == "T" * 10
    assert opened.title_truncated is True
    await runtime.aclose()


@pytest.mark.anyio
async def test_browser_read_failure_reclaims_the_handle() -> None:
    class TogglePage(FakePage):
        failed = False

        async def title(self) -> str:
            if self.failed:
                raise RuntimeError("provider detail")
            return await super().title()

    page = TogglePage("short")
    first = FakeContext(page)
    second = FakeContext(FakePage("replacement"))
    runtime = make_runtime(FakeBrowser([first, second]), max_handles=1)

    opened = await runtime.open_page("https://example.com", owner="caller-a")
    page.failed = True
    with pytest.raises(PublicToolError, match="no longer available"):
        await runtime.read_page(opened.handle, owner="caller-a")

    assert first.closed is True
    reopened = await runtime.open_page("https://example.com", owner="caller-a")
    assert reopened.handle != opened.handle
    await runtime.aclose()


@pytest.mark.anyio
async def test_browser_rejects_cross_origin_requests_and_expires_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr("build_an_mcp_server.browser_runtime.time.monotonic", lambda: now)
    page = FakePage("short")
    context = FakeContext(page)
    runtime = make_runtime(FakeBrowser([context]))

    with pytest.raises(PublicToolError, match="origin"):
        await runtime.open_page("https://other.example", owner="caller-a")

    opened = await runtime.open_page("https://example.com", owner="caller-a")
    assert context.route_handler is not None
    route = FakeRoute()
    await context.route_handler(route, FakeRequest("https://other.example/script.js"))
    assert route.aborted is True
    assert route.continued is False

    now = 131.0
    with pytest.raises(PublicToolError, match="not available"):
        await runtime.read_page(opened.handle, owner="caller-a")
    assert context.closed is True


@pytest.mark.anyio
async def test_browser_setup_and_cleanup_failures_close_every_reachable_layer() -> None:
    failed_context = FakeContext(FakePage("short"), fail_route=True)
    runtime = make_runtime(FakeBrowser([failed_context]))

    with pytest.raises(PublicToolError, match="could not be opened"):
        await runtime.open_page("https://example.com", owner="caller-a")
    assert failed_context.closed is True

    browser = FakeBrowser([], fail_close=True)
    playwright = FakePlaywright()
    runtime = make_runtime(browser)
    untyped_runtime = cast(Any, runtime)
    untyped_runtime._playwright = playwright
    with pytest.raises(RuntimeError, match="did not close cleanly"):
        await runtime.aclose()
    assert browser.closed is True
    assert playwright.stopped is True
