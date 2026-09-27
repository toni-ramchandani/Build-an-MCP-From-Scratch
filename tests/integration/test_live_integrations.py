from __future__ import annotations

import os

import pytest
from mcp.client import Client

from build_an_mcp_server.factory import create_server
from tests.helpers import make_settings

LIVE_INTEGRATION_GATE = "RUN_LIVE_INTEGRATIONS"


def _require_live_gate() -> None:
    if os.environ.get(LIVE_INTEGRATION_GATE) != "1":
        pytest.skip(f"set {LIVE_INTEGRATION_GATE}=1 to permit live integration I/O")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"set {name} to run this live integration test")
    return value


def _first_required_csv_value(name: str) -> str:
    first = _required(name).split(",", maxsplit=1)[0].strip()
    if not first:
        pytest.skip(f"set {name} to a non-empty first value")
    return first


@pytest.mark.integration
@pytest.mark.anyio
async def test_live_github_read_only_boundary() -> None:
    _require_live_gate()

    pytest.importorskip(
        "github",
        reason=("install the github extra to run the live GitHub integration test"),
    )

    token = _required("MCP_GITHUB_TOKEN")
    repository = _first_required_csv_value("MCP_GITHUB_REPOSITORIES")

    settings = make_settings(
        enable_workspace=False,
        enable_github=True,
        github_token=token,
        github_repositories=(repository,),
    )

    async with Client(
        create_server(settings),
        raise_exceptions=True,
        cache=None,
    ) as client:
        result = await client.call_tool(
            "get_github_repository_summary",
            {"repository": repository},
        )

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["repository"].lower() == repository.lower()
    assert token not in result.model_dump_json()


@pytest.mark.integration
@pytest.mark.anyio
async def test_live_isolated_browser_boundary() -> None:
    _require_live_gate()

    pytest.importorskip(
        "playwright",
        reason=("install the browser extra to run the live browser integration test"),
    )

    url = _required("MCP_BROWSER_TEST_URL")
    origin = _first_required_csv_value("MCP_BROWSER_ALLOWED_ORIGINS")

    settings = make_settings(
        enable_workspace=False,
        enable_browser=True,
        browser_allowed_origins=(origin,),
    )

    async with Client(
        create_server(settings),
        raise_exceptions=True,
        cache=None,
    ) as client:
        opened = await client.call_tool(
            "open_browser_page",
            {"url": url},
        )
        assert opened.structured_content is not None

        closed = await client.call_tool(
            "close_browser_page",
            {"handle": opened.structured_content["handle"]},
        )

    assert opened.is_error is False
    assert closed.is_error is False
    assert closed.structured_content is not None
    assert closed.structured_content["closed"] is True
