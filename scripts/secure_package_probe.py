"""Controlled signed-token probe of the installed secure application.

This fixture substitutes issuer key delivery. It proves neither live issuance
nor an external TLS edge. Invoked in isolated mode by verify_installed.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx2
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from mcp.client import Client
from mcp.client.stdio import get_default_environment
from mcp.client.streamable_http import streamable_http_client

from build_an_mcp_server.models import TextFileRead
from build_an_mcp_server.secure_http import create_secure_app
from build_an_mcp_server.security_config import SecuritySettings
from build_an_mcp_server.workspace import WorkspaceAdapter


async def probe(console: str, directory: Path) -> None:
    import build_an_mcp_server

    assert build_an_mcp_server.__file__ is not None
    assert Path(build_an_mcp_server.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    rejected = subprocess.run(
        [console], env=get_default_environment(), capture_output=True, timeout=5, check=False
    )
    assert rejected.returncode == 2
    assert b"security_configuration_rejected" in rejected.stderr
    root = directory / "secure-corpus"
    root.mkdir()
    data = b"secure-package-canary\n"
    (root / "canary.txt").write_bytes(data)
    approval = directory / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "generation": "installed-g1",
                "files": {"canary.txt": hashlib.sha256(data).hexdigest()},
                "excluded": [],
            }
        )
    )
    settings = cast(Any, SecuritySettings)(
        workspace_roots=(root,),
        corpus_approval_file=approval,
        auth_issuer_url="https://issuer.example.com/tenant",
        auth_resource_url="https://mcp.example.com/mcp",
        jwks_url="https://issuer.example.com/keys",
        allowed_client_ids=("installed-client",),
        enable_github=False,
        enable_browser=False,
        enable_mutation=False,
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="installed-key", alg="RS256", use="sig")
    app = create_secure_app(
        settings,
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"keys": [jwk]})),
    )
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": str(settings.auth_issuer_url),
        "aud": str(settings.auth_resource_url),
        "sub": "installed-reader",
        "client_id": "installed-client",
        "scope": "workspace:read",
        "iat": now,
        "exp": now + 300,
    }

    def token(**changes: object) -> str:
        return jwt.encode(
            claims | changes,
            key,
            algorithm="RS256",
            headers={"typ": "at+jwt", "kid": "installed-key"},
        )

    calls: list[str] = []
    original_read = WorkspaceAdapter.read_text

    def observed_read(
        self: WorkspaceAdapter, root_id: str, relative_path: str, *, offset_bytes: int
    ) -> TextFileRead:
        calls.append(relative_path)
        return original_read(self, root_id, relative_path, offset_bytes=offset_bytes)

    with patch.object(WorkspaceAdapter, "read_text", observed_read):
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as http,
        ):
            http.headers["Authorization"] = f"Bearer {token()}"
            async with Client(
                streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http),
                mode="2026-07-28",
                cache=None,
            ) as client:
                result = await client.call_tool(
                    "read_workspace_text", {"root_id": "root-1", "relative_path": "canary.txt"}
                )
                assert not result.is_error and result.structured_content is not None
                assert result.structured_content["content"] == data.decode()
            assert calls == ["canary.txt"]
            calls.clear()
            for access_token, status in (
                (token(aud="https://other.example/mcp"), 401),
                (token(scope="other"), 403),
            ):
                response = await http.post(
                    "http://127.0.0.1:8000/mcp",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json, text/event-stream",
                        "Mcp-Protocol-Version": "2026-07-28",
                        "Mcp-Method": "tools/call",
                        "Mcp-Name": "read_workspace_text",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "read_workspace_text",
                            "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
                            "_meta": {
                                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                "io.modelcontextprotocol/clientCapabilities": {},
                                "io.modelcontextprotocol/clientInfo": {
                                    "name": "package-probe",
                                    "version": "1",
                                },
                            },
                        },
                    },
                )
                assert response.status_code == status
                assert calls == []
                assert "canary" not in response.text and access_token not in response.text
    print(
        "installed secure app: signed-token read and refusal probes passed; "
        "issuer delivery controlled"
    )


if __name__ == "__main__":
    asyncio.run(probe(sys.argv[1], Path(sys.argv[2])))
