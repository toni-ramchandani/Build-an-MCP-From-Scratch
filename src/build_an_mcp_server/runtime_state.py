from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from mcp.server.fastmcp import FastMCP

from .config import ServerSettings


Cleanup: TypeAlias = Callable[[], None | Awaitable[None]]


@dataclass
class RuntimeState:
    """Application-owned runtime state for one running MCP server.

    This is not an MCP protocol session and not a general memory store. It
    exists so adapters can register live handles and cleanup callbacks.
    """

    settings: ServerSettings
    browser_handles: dict[str, Any] = field(default_factory=dict)
    _cleanups: list[Cleanup] = field(default_factory=list)
    _closed: bool = False

    @property
    def closed(self) -> bool:
        return self._closed

    def add_cleanup(self, cleanup: Cleanup) -> None:
        if self._closed:
            raise RuntimeError("RuntimeState is already closed.")
        self._cleanups.append(cleanup)

    def remember_browser_handle(self, key: str, handle: Any) -> None:
        if self._closed:
            raise RuntimeError("RuntimeState is already closed.")
        self.browser_handles[key] = handle

    def get_browser_handle(self, key: str) -> Any | None:
        return self.browser_handles.get(key)

    def forget_browser_handle(self, key: str) -> Any | None:
        return self.browser_handles.pop(key, None)

    async def aclose(self) -> None:
        if self._closed:
            return

        self._closed = True
        self.browser_handles.clear()

        while self._cleanups:
            cleanup = self._cleanups.pop()
            result = cleanup()
            if inspect.isawaitable(result):
                await result


@dataclass(frozen=True)
class AppContext:
    """Typed lifespan context made available to MCP handlers."""

    settings: ServerSettings
    state: RuntimeState


def make_app_lifespan(settings: ServerSettings):
    """Build a FastMCP lifespan for application-owned runtime state."""

    @asynccontextmanager
    async def app_lifespan(
        server: FastMCP,
    ) -> AsyncIterator[AppContext]:
        state = RuntimeState(settings=settings)
        try:
            yield AppContext(settings=settings, state=state)
        finally:
            await state.aclose()

    return app_lifespan
