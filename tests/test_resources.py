from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import AnyUrl

from mcp.client.session import ClientSession
from mcp.shared.exceptions import McpError

from tests.mcp_test_utils import resource_text


@pytest.mark.anyio
async def test_resources_list_includes_filesystem_roots(
    client_session: ClientSession,
) -> None:
    listed = await client_session.list_resources()

    assert {str(resource.uri) for resource in listed.resources} == {"filesystem://roots"}


@pytest.mark.anyio
async def test_filesystem_roots_resource_reports_policy(
    client_session: ClientSession,
    workspace_root: Path,
) -> None:
    result = await client_session.read_resource(AnyUrl("filesystem://roots"))

    payload = json.loads(resource_text(result))

    assert payload["readOnly"] is True
    assert payload["allowedRoots"] == [str(workspace_root.resolve())]


@pytest.mark.anyio
async def test_missing_resource_does_not_succeed(
    client_session: ClientSession,
) -> None:
    with pytest.raises(McpError):
        await client_session.read_resource(AnyUrl("filesystem://does-not-exist"))


@pytest.mark.anyio
async def test_resource_templates_are_empty_unless_chapter4_adds_templates(
    client_session: ClientSession,
) -> None:
    result = await client_session.list_resource_templates()

    assert result.resourceTemplates == []
