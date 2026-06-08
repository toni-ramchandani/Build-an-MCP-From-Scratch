from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.factory import create_server
from tests.mcp_test_utils import make_project_tree


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    return make_project_tree(tmp_path / "project")


@pytest.fixture
def server_settings(workspace_root: Path) -> ServerSettings:
    return ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(workspace_root,),
        read_only=True,
        enable_github=False,
        enable_browser=False,
    )


@pytest.fixture
def mcp_server(server_settings: ServerSettings) -> FastMCP:
    return create_server(server_settings)


@pytest.fixture
async def client_session(
    mcp_server: FastMCP,
) -> AsyncIterator[ClientSession]:
    async with create_connected_server_and_client_session(
        mcp_server,
        raise_exceptions=True,
    ) as session:
        yield session
