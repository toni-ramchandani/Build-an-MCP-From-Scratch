from __future__ import annotations

import pytest

from mcp.client.session import ClientSession


@pytest.mark.anyio
async def test_initialized_session_reports_server_capabilities(
    client_session: ClientSession,
) -> None:
    capabilities = client_session.get_server_capabilities()

    assert capabilities is not None
    assert capabilities.tools is not None
    assert capabilities.resources is not None
    assert capabilities.prompts is not None


@pytest.mark.anyio
async def test_initialized_session_can_list_declared_surfaces(
    client_session: ClientSession,
) -> None:
    tools = await client_session.list_tools()
    resources = await client_session.list_resources()
    prompts = await client_session.list_prompts()

    assert any(tool.name == "list_files" for tool in tools.tools)
    assert any(str(resource.uri) == "filesystem://roots" for resource in resources.resources)
    assert {prompt.name for prompt in prompts.prompts} >= {"review_file", "inspect_directory"}
