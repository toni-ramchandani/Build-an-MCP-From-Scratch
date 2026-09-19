from __future__ import annotations

import json
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from .errors import PublicToolError
from .models import BrowserCloseReceipt, BrowserPageSummary
from .runtime_state import AppContext


def register_browser_capabilities(
    mcp: MCPServer[AppContext],
    *,
    require_http_identity: bool,
) -> None:
    """Register the optional Chapter 8 state-and-isolation surface."""

    @mcp.tool(
        title="Open an isolated browser page",
        description=(
            "Open one allowlisted URL in a new isolated browser context "
            "and return bounded page text plus the opaque handle's inactivity lifetime."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        ),
    )
    async def open_browser_page(
        url: Annotated[str, Field(description="Absolute URL on an explicitly allowed origin.")],
        ctx: Context[AppContext],
    ) -> BrowserPageSummary:
        browser = _runtime(ctx)
        return await browser.open_page(url, owner=_owner(require_http_identity))

    @mcp.tool(
        title="Read an isolated browser page",
        description="Read bounded text from an unexpired browser page owned by this caller.",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    async def read_browser_page(
        handle: Annotated[str, Field(min_length=8, max_length=128)],
        ctx: Context[AppContext],
    ) -> BrowserPageSummary:
        browser = _runtime(ctx)
        return await browser.read_page(handle, owner=_owner(require_http_identity))

    @mcp.tool(
        title="Close an isolated browser page",
        description="Idempotently close one browser page handle owned by this caller.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def close_browser_page(
        handle: Annotated[str, Field(min_length=8, max_length=128)],
        ctx: Context[AppContext],
    ) -> BrowserCloseReceipt:
        browser = _runtime(ctx)
        return await browser.close_page(handle, owner=_owner(require_http_identity))


def _runtime(ctx: Context[AppContext]):
    browser = ctx.request_context.lifespan_context.runtime.browser
    if browser is None:
        raise PublicToolError("Browser capability is not available in this runtime.")
    return browser


def _owner(require_http_identity: bool) -> str:
    from mcp.server.auth.middleware.auth_context import get_access_token

    token = get_access_token()
    if token is None:
        if require_http_identity:
            raise PublicToolError("An authenticated caller identity is required for browser state.")
        return "local-process"
    return json.dumps([token.client_id, token.subject], separators=(",", ":"))
