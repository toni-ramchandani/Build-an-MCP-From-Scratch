from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio
from mcp.server import MCPServer

from .config import ServerSettings

if TYPE_CHECKING:
    from .browser_runtime import BrowserRuntime


logger = logging.getLogger(__name__)
Cleanup = Callable[[], None | Awaitable[None]]
BrowserFactory = Callable[[ServerSettings], "BrowserRuntime"]


@dataclass
class RuntimeState:
    """Application-owned state; never an MCP protocol session."""

    browser: BrowserRuntime | None = None
    cleanup_failures: list[str] = field(default_factory=list[str])
    _cleanups: list[Cleanup] = field(default_factory=list[Cleanup])
    _closed: bool = False

    @property
    def closed(self) -> bool:
        return self._closed

    def add_cleanup(self, cleanup: Cleanup) -> None:
        if self._closed:
            raise RuntimeError("RuntimeState is already closed")
        self._cleanups.append(cleanup)

    async def aclose(self) -> None:
        if self._closed:
            return
        # Each async cleanup gets a bounded shield. Ordinary exceptions never
        # prevent the remaining callbacks from running. Synchronous callbacks
        # must themselves be nonblocking; Python cannot forcibly stop them.
        cancelled: BaseException | None = None
        with anyio.CancelScope(shield=True):
            self._closed = True
            while self._cleanups:
                cleanup = self._cleanups.pop()
                try:
                    with anyio.fail_after(30, shield=True):
                        result = cleanup()
                        if inspect.isawaitable(result):
                            await result
                except BaseException as exc:
                    if not isinstance(exc, Exception):
                        cancelled = exc
                        continue
                    failure = type(exc).__name__
                    self.cleanup_failures.append(failure)
                    logger.error("Runtime cleanup failed type=%s", failure)
        if cancelled is not None:
            raise cancelled


@dataclass(frozen=True)
class AppContext:
    settings: ServerSettings
    runtime: RuntimeState


def make_app_lifespan(
    settings: ServerSettings,
    *,
    browser_factory: BrowserFactory | None = None,
    additional_cleanups: tuple[Cleanup, ...] = (),
):
    """Build the single application lifespan shared by all transports."""

    @asynccontextmanager
    async def app_lifespan(server: MCPServer[AppContext]) -> AsyncGenerator[AppContext, None]:
        del server
        runtime = RuntimeState()
        for cleanup in additional_cleanups:
            runtime.add_cleanup(cleanup)
        if settings.enable_browser:
            if browser_factory is None:
                from .browser_runtime import BrowserRuntime

                runtime.browser = BrowserRuntime.from_settings(settings)
            else:
                runtime.browser = browser_factory(settings)
            runtime.add_cleanup(runtime.browser.aclose)

        try:
            yield AppContext(settings=settings, runtime=runtime)
        finally:
            await runtime.aclose()

    return app_lifespan
