from __future__ import annotations

import pytest
from mcp.client import Client


@pytest.mark.anyio
async def test_unchanged_tools_have_repeatable_discovery_order(mcp_client: Client) -> None:
    first = await mcp_client.list_tools()
    second = await mcp_client.list_tools()
    assert [item.name for item in first.tools] == [item.name for item in second.tools]
