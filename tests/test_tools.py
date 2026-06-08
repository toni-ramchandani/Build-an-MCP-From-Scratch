from __future__ import annotations

from pathlib import Path

import pytest

from mcp.client.session import ClientSession
from mcp.types import CallToolResult

from tests.mcp_test_utils import assert_tool_call_does_not_succeed, tool_names, tool_text


@pytest.mark.anyio
async def test_filesystem_tools_are_discoverable(
    client_session: ClientSession,
) -> None:
    result = await client_session.list_tools()

    names = tool_names(result)
    assert "list_files" in names
    assert "read_file" in names
    assert "write_file" not in names


@pytest.mark.anyio
async def test_read_file_tool_schema_requires_path(
    client_session: ClientSession,
) -> None:
    listed = await client_session.list_tools()
    read_file = next(tool for tool in listed.tools if tool.name == "read_file")

    schema = read_file.inputSchema
    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert "path" in schema.get("required", [])


@pytest.mark.anyio
async def test_read_file_returns_text_and_structured_content(
    client_session: ClientSession,
    workspace_root: Path,
) -> None:
    target = workspace_root / "readme.md"

    result = await client_session.call_tool(
        "read_file",
        {"path": str(target)},
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is not True
    assert "# Project" in tool_text(result)

    structured = result.structuredContent
    assert isinstance(structured, dict)
    assert structured["path"] == str(target)
    assert structured["content"] == "# Project\nA sample project.\n"
    assert structured["bytesRead"] == len(structured["content"].encode("utf-8"))
    assert structured["mimeType"] in {"text/markdown", "text/plain"}


@pytest.mark.anyio
async def test_list_files_returns_structured_directory_listing(
    client_session: ClientSession,
    workspace_root: Path,
) -> None:
    result = await client_session.call_tool(
        "list_files",
        {"path": str(workspace_root)},
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is not True
    structured = result.structuredContent
    assert isinstance(structured, dict)
    assert structured["path"] == str(workspace_root)
    assert structured["count"] == 2
    assert [entry["name"] for entry in structured["entries"]] == ["src", "readme.md"]


@pytest.mark.anyio
async def test_missing_file_returns_tool_execution_error(
    client_session: ClientSession,
    workspace_root: Path,
) -> None:
    missing = workspace_root / "missing.txt"

    result = await client_session.call_tool(
        "read_file",
        {"path": str(missing)},
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert "missing.txt" in tool_text(result)


@pytest.mark.anyio
async def test_outside_path_returns_tool_execution_error(
    client_session: ClientSession,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("do not read\n", encoding="utf-8")

    result = await client_session.call_tool(
        "read_file",
        {"path": str(outside)},
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert "outside" in tool_text(result).lower()


@pytest.mark.anyio
async def test_read_file_missing_required_argument_does_not_succeed(
    client_session: ClientSession,
) -> None:
    await assert_tool_call_does_not_succeed(client_session, "read_file", {})


@pytest.mark.anyio
async def test_read_file_invalid_argument_type_does_not_succeed(
    client_session: ClientSession,
) -> None:
    await assert_tool_call_does_not_succeed(
        client_session,
        "read_file",
        {"path": 123},
    )


@pytest.mark.anyio
async def test_unknown_tool_does_not_succeed(
    client_session: ClientSession,
) -> None:
    await assert_tool_call_does_not_succeed(
        client_session,
        "definitely_not_registered",
        {},
    )
