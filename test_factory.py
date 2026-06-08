from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.factory import create_server
from tests.mcp_test_utils import make_project_tree, resource_text, tool_names


def _settings(root: Path, *, read_only: bool = True) -> ServerSettings:
    return ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(root,),
        read_only=read_only,
        enable_github=False,
        enable_browser=False,
    )


def test_create_server_returns_fastmcp_server(server_settings: ServerSettings) -> None:
    server = create_server(server_settings)

    assert isinstance(server, FastMCP)


@pytest.mark.anyio
async def test_default_factory_exposes_filesystem_tools_and_prompts(
    workspace_root: Path,
) -> None:
    server = create_server(_settings(workspace_root, read_only=True))

    async with create_connected_server_and_client_session(server, raise_exceptions=True) as session:
        tools = await session.list_tools()
        resources = await session.list_resources()
        prompts = await session.list_prompts()

    names = tool_names(tools)
    assert "list_files" in names
    assert "read_file" in names
    assert "write_file" not in names
    assert {str(resource.uri) for resource in resources.resources} == {"filesystem://roots"}
    assert {prompt.name for prompt in prompts.prompts} >= {"review_file", "inspect_directory"}


@pytest.mark.anyio
async def test_write_file_is_registered_only_when_not_read_only(
    workspace_root: Path,
) -> None:
    server = create_server(_settings(workspace_root, read_only=False))

    async with create_connected_server_and_client_session(server, raise_exceptions=True) as session:
        tools = await session.list_tools()

    assert "write_file" in tool_names(tools)


@pytest.mark.anyio
async def test_filesystem_can_be_disabled_without_removing_prompts(tmp_path: Path) -> None:
    settings = ServerSettings(
        enable_filesystem=False,
        fs_allowed_dirs=(),
        read_only=True,
        enable_github=False,
        enable_browser=False,
    )
    server = create_server(settings)

    async with create_connected_server_and_client_session(server, raise_exceptions=True) as session:
        tools = await session.list_tools()
        resources = await session.list_resources()
        prompts = await session.list_prompts()

    assert "list_files" not in tool_names(tools)
    assert "read_file" not in tool_names(tools)
    assert resources.resources == []
    assert {prompt.name for prompt in prompts.prompts} >= {"review_file", "inspect_directory"}


@pytest.mark.anyio
async def test_repeated_server_creation_does_not_share_allowed_roots(
    tmp_path: Path,
) -> None:
    first_root = make_project_tree(tmp_path / "first")
    second_root = make_project_tree(tmp_path / "second")

    first_server = create_server(_settings(first_root))
    second_server = create_server(_settings(second_root))

    async with create_connected_server_and_client_session(first_server, raise_exceptions=True) as first:
        first_payload = json.loads(resource_text(await first.read_resource(AnyUrl("filesystem://roots"))))

    async with create_connected_server_and_client_session(second_server, raise_exceptions=True) as second:
        second_payload = json.loads(resource_text(await second.read_resource(AnyUrl("filesystem://roots"))))

    assert first_payload["allowedRoots"] == [str(first_root.resolve())]
    assert second_payload["allowedRoots"] == [str(second_root.resolve())]
