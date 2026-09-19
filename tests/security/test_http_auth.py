from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.transport_security import TransportSecuritySettings

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.http_server import create_http_app
from tests.helpers import make_settings

PROTOCOL_VERSION = "2026-07-28"
BASE_URL = "http://127.0.0.1:8000"


class StaticTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        scopes = {
            "read-token": ["workspace:read"],
            "write-token": ["workspace:read", "workspace:write"],
            "wrong-scope": ["other"],
        }.get(token)
        if scopes is None:
            return None
        return AccessToken(
            token=token,
            client_id="book-test-client",
            subject="reader",
            scopes=scopes,
            expires_at=int(time.time()) + 300,
            resource="https://mcp.example.com",
        )


def _settings(root: Path) -> ServerSettings:
    return make_settings(
        workspace_roots=(root,),
        enable_mutation=True,
        http_require_auth=True,
        auth_issuer_url="https://issuer.example.com",
        auth_resource_url="https://mcp.example.com",
        auth_required_scopes=("workspace:read",),
    )


def _request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(params or {})
    payload["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {
            "name": "security-test",
            "version": "0.2.0",
        },
    }
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": payload}


def _headers(method: str, *, token: str | None = None, name: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Mcp-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _write_request(relative_path: str) -> dict[str, Any]:
    return _request(
        "tools/call",
        {
            "name": "write_workspace_text",
            "arguments": {
                "root_id": "root-1",
                "relative_path": relative_path,
                "content": "verified\n",
                "expected_sha256": "absent",
            },
        },
    )


@pytest.mark.anyio
async def test_http_bearer_gate_and_operation_scope_challenge(workspace_root: Path) -> None:
    app = create_http_app(
        _settings(workspace_root),
        token_verifier=StaticTokenVerifier(),
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    transport = httpx2.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        unauthenticated = await client.post(
            "/mcp",
            headers=_headers("tools/list"),
            json=_request("tools/list"),
        )
        wrong_scope = await client.post(
            "/mcp",
            headers=_headers("tools/list", token="wrong-scope"),
            json=_request("tools/list"),
        )
        read_allowed = await client.post(
            "/mcp",
            headers=_headers("tools/list", token="read-token"),
            json=_request("tools/list"),
        )
        write_denied = await client.post(
            "/mcp",
            headers=_headers(
                "tools/call",
                token="read-token",
                name="write_workspace_text",
            ),
            json=_write_request("denied.txt"),
        )
        encoded_name = base64.b64encode(b"write_workspace_text").decode("ascii")
        encoded_write_denied = await client.post(
            "/mcp",
            headers=_headers(
                "tools/call",
                token="read-token",
                name=f"=?base64?{encoded_name}?=",
            ),
            json=_write_request("encoded-denied.txt"),
        )
        mismatch_denied = await client.post(
            "/mcp",
            headers=_headers(
                "tools/call",
                token="read-token",
                name="read_workspace_text",
            ),
            json=_write_request("mismatch-denied.txt"),
        )
        write_allowed = await client.post(
            "/mcp",
            headers=_headers(
                "tools/call",
                token="write-token",
                name="write_workspace_text",
            ),
            json=_write_request("allowed.txt"),
        )
        public_metadata = await client.get("/.well-known/oauth-protected-resource")

    unauthenticated_challenge = unauthenticated.headers["www-authenticate"]
    wrong_scope_challenge = wrong_scope.headers["www-authenticate"]
    write_challenge = write_denied.headers["www-authenticate"]

    assert unauthenticated.status_code == 401
    assert 'scope="workspace:read"' in unauthenticated_challenge
    assert "resource_metadata=" in unauthenticated_challenge
    assert wrong_scope.status_code == 403
    assert 'error="insufficient_scope"' in wrong_scope_challenge
    assert 'scope="workspace:read"' in wrong_scope_challenge
    assert read_allowed.status_code == 200
    assert {tool["name"] for tool in read_allowed.json()["result"]["tools"]} >= {
        "read_workspace_text",
        "write_workspace_text",
    }
    assert write_denied.status_code == 403
    assert write_denied.json()["error"] == "insufficient_scope"
    assert 'error="insufficient_scope"' in write_challenge
    assert 'scope="workspace:read workspace:write"' in write_challenge
    assert "resource_metadata=" in write_challenge
    assert encoded_write_denied.status_code == 403
    assert mismatch_denied.status_code == 400
    assert write_allowed.status_code == 200
    assert write_allowed.json()["result"]["isError"] is False
    assert public_metadata.status_code == 200
    assert public_metadata.json()["resource"] == "https://mcp.example.com/"
    assert not (workspace_root / "denied.txt").exists()
    assert not (workspace_root / "encoded-denied.txt").exists()
    assert not (workspace_root / "mismatch-denied.txt").exists()
    assert (workspace_root / "allowed.txt").read_text() == "verified\n"
    rendered_failures = (
        str(write_denied.headers)
        + str(write_denied.json())
        + str(encoded_write_denied.headers)
        + str(encoded_write_denied.json())
    )
    assert "read-token" not in rendered_failures
