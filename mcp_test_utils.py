from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.client.session import ClientSession
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, TextContent


def tool_names(result: object) -> set[str]:
    return {tool.name for tool in result.tools}


def prompt_names(result: object) -> set[str]:
    return {prompt.name for prompt in result.prompts}


def tool_text(result: CallToolResult) -> str:
    return "\n".join(
        item.text
        for item in result.content
        if isinstance(item, TextContent)
    )


def resource_text(result: object) -> str:
    return "\n".join(
        item.text
        for item in result.contents
        if getattr(item, "text", None) is not None
    )


def make_project_tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "readme.md").write_text(
        "# Project\nA sample project.\n",
        encoding="utf-8",
    )
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "main.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )
    return root


async def assert_tool_call_does_not_succeed(
    session: ClientSession,
    name: str,
    arguments: Mapping[str, Any],
) -> None:
    """Assert that a bad tool call is not reported as a successful tool result.

    The MCP specification distinguishes protocol/request errors from tool
    execution errors. The Python SDK can surface some failures as McpError and
    others as CallToolResult(isError=True), depending on which layer rejects
    the request. Both are acceptable here; a successful result is not.
    """

    try:
        result = await session.call_tool(name, dict(arguments))
    except McpError:
        return

    assert isinstance(result, CallToolResult)
    assert result.isError is True
