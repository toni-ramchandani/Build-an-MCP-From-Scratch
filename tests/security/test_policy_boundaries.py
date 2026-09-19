from __future__ import annotations

from pathlib import Path

import pytest
from mcp.client import Client
from mcp.server.auth.provider import AccessToken

from build_an_mcp_server.errors import ConfigurationBoundaryError
from build_an_mcp_server.factory import create_server
from tests.helpers import make_settings

PROTOCOL_VERSION = "2026-07-28"


class RejectingVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        del token
        return None


def test_risky_http_surfaces_require_authenticated_transport(tmp_path: Path) -> None:
    mutation = make_settings(
        workspace_roots=(tmp_path,),
        enable_mutation=True,
    )
    with pytest.raises(ConfigurationBoundaryError, match="require authenticated HTTP"):
        create_server(mutation, boundary="http")

    browser = make_settings(
        workspace_roots=(tmp_path,),
        enable_browser=True,
        browser_allowed_origins=("https://example.com",),
    )
    with pytest.raises(ConfigurationBoundaryError, match="require authenticated HTTP"):
        create_server(browser, boundary="http")

    github = make_settings(
        workspace_roots=(tmp_path,),
        enable_github=True,
        github_token="not-a-real-token",
        github_repositories=("example/repository",),
    )
    with pytest.raises(ConfigurationBoundaryError, match="require authenticated HTTP"):
        create_server(github, boundary="http")


def test_verifier_is_rejected_outside_authenticated_http(tmp_path: Path) -> None:
    settings = make_settings(workspace_roots=(tmp_path,))
    with pytest.raises(ConfigurationBoundaryError, match="only for authenticated HTTP"):
        create_server(settings, boundary="stdio", token_verifier=RejectingVerifier())


@pytest.mark.anyio
async def test_write_metadata_is_explicit_and_default_discovery_omits_it(
    workspace_root: Path,
) -> None:
    default = make_settings(workspace_roots=(workspace_root,))
    enabled = make_settings(workspace_roots=(workspace_root,), enable_mutation=True)

    async with Client(create_server(default), mode=PROTOCOL_VERSION, cache=None) as client:
        default_names = {tool.name for tool in (await client.list_tools()).tools}
    async with Client(create_server(enabled), mode=PROTOCOL_VERSION, cache=None) as client:
        tools = await client.list_tools()

    assert "write_workspace_text" not in default_names
    write = next(tool for tool in tools.tools if tool.name == "write_workspace_text")
    assert write.annotations is not None
    assert write.annotations.read_only_hint is False
    assert write.annotations.destructive_hint is True
    assert write.annotations.idempotent_hint is False
    assert write.annotations.open_world_hint is False
