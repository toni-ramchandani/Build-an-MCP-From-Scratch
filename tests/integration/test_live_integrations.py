from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.factory import create_server
from tests.mcp_test_utils import tool_text


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}


def _require_integration() -> None:
    if not _env_enabled("RUN_INTEGRATION"):
        pytest.skip("set RUN_INTEGRATION=1 to run live integration tests")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


@asynccontextmanager
async def _session_for(settings: ServerSettings) -> AsyncIterator[ClientSession]:
    server: FastMCP = create_server(settings)
    async with create_connected_server_and_client_session(server, raise_exceptions=True) as session:
        yield session


@pytest.mark.anyio
async def test_live_github_repository_info(tmp_path: Path) -> None:
    _require_integration()
    if not _env_enabled("ENABLE_GITHUB"):
        pytest.skip("set ENABLE_GITHUB=1 to run GitHub integration test")

    token = _require_env("GITHUB_TOKEN")

    settings = ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(tmp_path,),
        read_only=True,
        enable_github=True,
        github_token=token,
        enable_browser=False,
    )

    async with _session_for(settings) as session:
        result = await session.call_tool(
            "get_repository_info",
            {"owner": "modelcontextprotocol", "repo": "python-sdk"},
        )

    assert isinstance(result, CallToolResult)
    assert result.isError is not True
    assert "modelcontextprotocol/python-sdk" in tool_text(result).lower()


@pytest.mark.anyio
async def test_live_browser_health_check(tmp_path: Path) -> None:
    _require_integration()
    if not _env_enabled("ENABLE_BROWSER"):
        pytest.skip("set ENABLE_BROWSER=1 to run browser integration test")

    pytest.importorskip("playwright")

    settings = ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(tmp_path,),
        read_only=True,
        enable_github=False,
        enable_browser=True,
    )

    async with _session_for(settings) as session:
        result = await session.call_tool("browser_health_check", {})

    assert isinstance(result, CallToolResult)
    assert result.isError is not True
