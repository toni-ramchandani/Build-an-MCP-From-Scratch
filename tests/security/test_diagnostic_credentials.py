from __future__ import annotations

import argparse
import json

import httpx2
import pytest
from httpx2 import AsyncClient
from mcp.shared.exceptions import MCPError
from mcp.types import ListToolsResult

from scripts import diagnostic_client


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "http://plain.example.com/mcp",
        "http://localhost:8000/mcp",
        "http://127.0.0.2:8000/mcp",
        "https://user:password@mcp.example.com/mcp",
        "https://mcp.example.com/mcp?access_token=synthetic-query-token",
        "https://mcp.example.com/mcp#fragment",
        "ftp://mcp.example.com/mcp",
        "/mcp",
        "http://[invalid/mcp",
    ],
)
async def test_bearer_destination_rejected_before_http_client_construction(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("MCP_DIAGNOSTIC_ACCESS_TOKEN", "synthetic-diagnostic-token")

    class UnexpectedClient(AsyncClient):
        def __init__(self, **kwargs: object) -> None:
            pytest.fail("HTTP client constructed before rejecting the destination")

    monkeypatch.setattr(diagnostic_client.httpx2, "AsyncClient", UnexpectedClient)
    with pytest.raises(MCPError):
        async with diagnostic_client._open_client(  # pyright: ignore[reportPrivateUsage]
            argparse.Namespace(transport="http", url=url)
        ):
            pytest.fail("unsafe bearer destination accepted")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "https://mcp.example.com/mcp",
        "https://127.0.0.1:8000/mcp",
        "http://127.0.0.1:8000/mcp",
        "http://[::1]:8000/mcp",
    ],
)
async def test_accepted_destination_sends_bearer_on_a_real_sdk_request(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    token = "synthetic-diagnostic-token"
    monkeypatch.setenv("MCP_DIAGNOSTIC_ACCESS_TOKEN", token)
    sent: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        body = json.loads(request.content)
        assert body["method"] == "tools/list"
        return httpx2.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": ListToolsResult(tools=[]).model_dump(
                    by_alias=True, mode="json", exclude_none=True
                ),
            },
        )

    class CapturingClient(AsyncClient):
        def __init__(
            self, *, trust_env: bool, follow_redirects: bool, headers: dict[str, str]
        ) -> None:
            assert trust_env is False and follow_redirects is False
            super().__init__(
                trust_env=trust_env,
                follow_redirects=follow_redirects,
                headers=headers,
                transport=httpx2.MockTransport(respond),
            )

    monkeypatch.setattr(diagnostic_client.httpx2, "AsyncClient", CapturingClient)
    async with diagnostic_client._open_client(  # pyright: ignore[reportPrivateUsage]
        argparse.Namespace(transport="http", url=url)
    ) as client:
        result = await client.list_tools()
        assert result.tools == []
    assert len(sent) == 1
    assert sent[0].url == httpx2.URL(url)
    assert sent[0].headers["Authorization"] == f"Bearer {token}"


@pytest.mark.anyio
@pytest.mark.parametrize("token", ["contains space", "line\nbreak", "\u2603", "x" * 16_385])
async def test_invalid_bearer_format_rejected_before_http_client_construction(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv("MCP_DIAGNOSTIC_ACCESS_TOKEN", token)

    class UnexpectedClient(AsyncClient):
        def __init__(self, **kwargs: object) -> None:
            pytest.fail("HTTP client constructed before rejecting the token")

    monkeypatch.setattr(diagnostic_client.httpx2, "AsyncClient", UnexpectedClient)
    with pytest.raises(MCPError, match="Invalid diagnostic access token format"):
        async with diagnostic_client._open_client(  # pyright: ignore[reportPrivateUsage]
            argparse.Namespace(transport="http", url="https://mcp.example.com/mcp")
        ):
            pytest.fail("invalid bearer format accepted")
