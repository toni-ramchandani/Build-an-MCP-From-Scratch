from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import AnyUrl

from mcp.shared.memory import create_connected_server_and_client_session

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.factory import create_server
from tests.mcp_test_utils import resource_text, tool_names


@pytest.mark.anyio
async def test_read_only_policy_is_visible(client_session) -> None:
    result = await client_session.read_resource(AnyUrl("filesystem://roots"))
    payload = json.loads(resource_text(result))

    assert payload["readOnly"] is True
    assert payload["allowedRoots"]


@pytest.mark.anyio
async def test_write_tools_are_absent_in_read_only_mode(client_session) -> None:
    listed = await client_session.list_tools()
    names = tool_names(listed)

    assert "write_file" not in names
    assert "delete_file" not in names
    assert "rename_file" not in names


@pytest.mark.anyio
async def test_write_file_is_present_when_read_only_is_false(
    workspace_root: Path,
) -> None:
    settings = ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(workspace_root,),
        read_only=False,
        enable_github=False,
        enable_browser=False,
    )
    server = create_server(settings)

    async with create_connected_server_and_client_session(server, raise_exceptions=True) as session:
        listed = await session.list_tools()

    assert "write_file" in tool_names(listed)


@pytest.mark.anyio
async def test_browser_tools_are_absent_by_default(client_session) -> None:
    listed = await client_session.list_tools()
    names = tool_names(listed)

    assert "browser_health_check" not in names
    assert not any(name.startswith("browser_") for name in names)


@pytest.mark.anyio
async def test_github_tools_are_absent_by_default(client_session) -> None:
    listed = await client_session.list_tools()
    names = tool_names(listed)

    assert "get_repository_info" not in names


@pytest.mark.anyio
async def test_github_tool_is_present_when_enabled_with_token(
    workspace_root: Path,
) -> None:
    settings = ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(workspace_root,),
        read_only=True,
        enable_github=True,
        github_token="fake-token-for-registration-only",
        enable_browser=False,
    )
    server = create_server(settings)

    async with create_connected_server_and_client_session(server, raise_exceptions=True) as session:
        listed = await session.list_tools()

    assert "get_repository_info" in tool_names(listed)


@pytest.mark.anyio
async def test_negotiated_capabilities_match_public_surfaces(client_session) -> None:
    capabilities = client_session.get_server_capabilities()

    assert capabilities is not None
    assert capabilities.tools is not None
    assert capabilities.resources is not None
    assert capabilities.prompts is not None

    assert (await client_session.list_tools()).tools
    assert (await client_session.list_resources()).resources
    assert (await client_session.list_prompts()).prompts
