from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult

from build_an_mcp_server import github_utils
from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.factory import create_server
from tests.mcp_test_utils import tool_names, tool_text


def _settings(
    root: Path,
    *,
    enable_github: bool = False,
    github_token: str | None = None,
    enable_browser: bool = False,
) -> ServerSettings:
    return ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(root,),
        read_only=True,
        enable_github=enable_github,
        github_token=github_token,
        enable_browser=enable_browser,
    )


@asynccontextmanager
async def _session_for(settings: ServerSettings) -> AsyncIterator[ClientSession]:
    server: FastMCP = create_server(settings)
    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=True,
    ) as session:
        yield session


def test_missing_github_token_fails_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        _settings(tmp_path, enable_github=True, github_token=None)


@pytest.mark.anyio
async def test_browser_tools_are_absent_unless_enabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path, enable_browser=False)

    async with _session_for(settings) as session:
        listed = await session.list_tools()

    names = tool_names(listed)
    assert "browser_health_check" not in names
    assert not any(name.startswith("browser_") for name in names)


@pytest.mark.anyio
async def test_failed_github_call_returns_tool_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_get_github_client(token: str | None = None) -> object:
        raise RuntimeError("simulated GitHub adapter failure")

    monkeypatch.setattr(github_utils, "get_github_client", fail_get_github_client)

    settings = _settings(
        tmp_path,
        enable_github=True,
        github_token="fake-token-for-default-test",
    )

    async with _session_for(settings) as session:
        result = await session.call_tool(
            "get_repository_info",
            {"owner": "modelcontextprotocol", "repo": "python-sdk"},
        )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert "fake-token-for-default-test" not in tool_text(result)
