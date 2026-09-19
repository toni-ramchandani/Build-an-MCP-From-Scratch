from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from mcp.client import Client

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.factory import create_server
from tests.helpers import make_settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "approved-workspace"
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text(
        "# Sample\nA bounded workspace.\n",
        encoding="utf-8",
    )
    (root / "src" / "app.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def base_settings(workspace_root: Path) -> ServerSettings:
    return make_settings(
        workspace_roots=(workspace_root,),
        max_file_read_bytes=1_024,
        max_directory_entries=20,
        max_write_bytes=1_024,
    )


@pytest.fixture
async def mcp_client(
    base_settings: ServerSettings,
) -> AsyncIterator[Client]:
    server = create_server(base_settings)
    async with Client(
        server,
        raise_exceptions=True,
        cache=None,
    ) as client:
        yield client
