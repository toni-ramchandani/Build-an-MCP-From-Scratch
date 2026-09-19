from __future__ import annotations

import pytest
from mcp import MCPError
from mcp.client import Client
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS


@pytest.mark.anyio
async def test_unknown_tool_is_a_protocol_invalid_params_error_at_both_client_levels(
    mcp_client: Client,
) -> None:
    """The application guard closes the SDK/spec discrepancy for this server."""

    for call in (
        mcp_client.call_tool("does_not_exist", {}),
        mcp_client.session.call_tool("does_not_exist", {}),
    ):
        with pytest.raises(MCPError) as exc_info:
            await call
        assert exc_info.value.error.code == INVALID_PARAMS
        assert exc_info.value.error.data == {"name": "does_not_exist"}


@pytest.mark.anyio
async def test_unknown_resource_uses_invalid_params(
    mcp_client: Client,
) -> None:
    uri = "workspace://does-not-exist"

    with pytest.raises(MCPError) as exc_info:
        await mcp_client.read_resource(uri)

    assert exc_info.value.error.code == INVALID_PARAMS
    assert exc_info.value.error.data == {"uri": uri}


@pytest.mark.anyio
async def test_unknown_prompt_sdk_behavior_is_recorded(
    mcp_client: Client,
) -> None:
    """Record pinned SDK mapping without promoting it to application policy."""

    with pytest.raises(MCPError) as exc_info:
        await mcp_client.get_prompt(
            "does_not_exist",
            {},
        )

    assert exc_info.value.error.code == INTERNAL_ERROR
    assert exc_info.value.error.message == "Unknown prompt: does_not_exist"


@pytest.mark.anyio
async def test_missing_prompt_argument_sdk_behavior_is_recorded(
    mcp_client: Client,
) -> None:
    """Keep the observed mapping explicit until the pinned SDK changes."""

    with pytest.raises(MCPError) as exc_info:
        await mcp_client.get_prompt(
            "review_workspace_file",
            {"root_id": "root-1"},
        )

    assert exc_info.value.error.code == INTERNAL_ERROR
    assert "Missing required arguments" in exc_info.value.error.message
    assert "relative_path" in exc_info.value.error.message
