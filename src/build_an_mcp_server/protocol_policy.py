from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS


class UnknownToolProtocolGuard:
    """Map an unknown ``tools/call`` name to the MCP protocol error category.

    The pinned SDK's high-level handler normally converts an unknown tool into
    an ``isError`` tool result. MCP 2026-07-28 classifies an unknown tool name
    as an invalid-parameters JSON-RPC error instead. This guard is deliberately
    narrow and runs before the SDK's tool handler so the application does not
    need to patch private SDK dispatch code.
    """

    def __init__(self, tool_names: Callable[[], Awaitable[Collection[str]]]) -> None:
        self._tool_names = tool_names

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if ctx.method == "tools/call":
            params = ctx.params or {}
            name = params.get("name")
            if isinstance(name, str) and name not in await self._tool_names():
                raise MCPError(
                    code=INVALID_PARAMS,
                    message=f"Unknown tool: {name}",
                    data={"name": name},
                )
        return await call_next(ctx)
