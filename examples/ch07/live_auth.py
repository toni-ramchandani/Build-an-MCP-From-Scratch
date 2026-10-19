"""One pre-registered Auth0 PKCE lab; tokens stay in process memory.

This selected, pinned-issuer exercise is not a general-purpose OAuth client.
Protected-resource metadata is mapped explicitly to a loopback backend for the
local lab. A production client must use the actual protected HTTPS endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.metadata
import json
import logging
import platform
import re
import secrets
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

PROTOCOL = "2026-07-28"
REDIRECT = "http://127.0.0.1:8765/callback"
CANARY = b"chapter-seven-security-canary\n"
MAX_DOCUMENT = 65_536


class LabRejected(Exception):
    """A lab boundary did not meet its explicitly selected contract."""


def checked_url(value: str, *, loopback: bool = False) -> str:
    target = urlsplit(value)
    if (
        not target.hostname
        or target.username
        or target.password
        or target.query
        or target.fragment
        or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
        or not (
            target.scheme == "https"
            or (loopback and target.scheme == "http" and target.hostname in {"127.0.0.1", "::1"})
        )
    ):
        raise LabRejected("url_policy")
    _ = target.port
    return value


def pinned_endpoint(value: object, issuer: str) -> str:
    if not isinstance(value, str):
        raise LabRejected("issuer_endpoint")
    checked_url(value)
    if urlsplit(value).netloc != urlsplit(issuer).netloc:
        raise LabRejected("issuer_endpoint")
    return value


def callback_code(path: str, expected_state: str, issuer: str) -> str:
    target = urlsplit(path)
    if (
        target.scheme
        or target.netloc
        or target.fragment
        or target.path != "/callback"
        or len(path) > 8192
    ):
        raise LabRejected("callback_path")
    values = parse_qs(target.query, keep_blank_values=True, max_num_fields=8)
    if any(len(v) != 1 for v in values.values()):
        raise LabRejected("callback_duplicates")
    # Exact comparison follows RFC 9207; no URL normalization of the returned iss.
    if values.get("iss") != [issuer]:
        raise LabRejected("callback_issuer")
    state = values.get("state", [""])[0]
    if not state.isascii() or not secrets.compare_digest(state, expected_state):
        raise LabRejected("callback_state")
    if "error" in values:
        raise LabRejected("authorization_refused")
    code = values.get("code", [""])[0]
    if not code or len(code) > 4096 or not code.isascii():
        raise LabRejected("callback_code")
    return code


def browser_code(authorization_url: str, state: str, issuer: str) -> str:
    result: list[str] = []
    finished = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass  # Callback queries contain authorization codes and state.

        def do_GET(self) -> None:
            try:
                if self.headers.get_all("Host") != ["127.0.0.1:8765"]:
                    raise LabRejected("callback_host")
                code = callback_code(self.path, state, issuer)
                if finished.is_set():
                    raise LabRejected("callback_replayed")
            except (LabRejected, ValueError):
                status, body = 400, b"Authorization callback refused."
            else:
                result.append(code)
                finished.set()
                status, body = 200, b"Authorization received. Return to the terminal."
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

    class CallbackServer(HTTPServer):
        def get_request(self) -> tuple[Any, Any]:
            connection, address = super().get_request()
            connection.settimeout(2)
            return connection, address

        def handle_error(self, request: Any, client_address: Any) -> None:
            pass

    with CallbackServer(("127.0.0.1", 8765), Callback) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            if not webbrowser.open(authorization_url):
                raise LabRejected("browser_not_available")
            if not finished.wait(300):
                raise LabRejected("callback_timeout")
            return result[0]
        finally:
            server.shutdown()
            thread.join(timeout=3)


async def bounded_response(
    client: httpx2.AsyncClient, method: str, url: str, **kwargs: Any
) -> tuple[int, httpx2.Headers, bytes]:
    async with client.stream(method, url, **kwargs) as response:
        data = bytearray()
        async for part in response.aiter_bytes():
            if len(data) + len(part) > MAX_DOCUMENT:
                raise LabRejected("response_budget")
            data.extend(part)
        return response.status_code, httpx2.Headers(response.headers), bytes(data)


async def document(
    client: httpx2.AsyncClient, method: str, url: str, **kwargs: Any
) -> dict[str, Any]:
    status, _, data = await bounded_response(client, method, url, **kwargs)
    if status != 200:
        raise LabRejected("metadata_or_token_response")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise LabRejected("response_document")
    return cast(dict[str, Any], value)


async def discover(
    client: httpx2.AsyncClient, server: str, resource: str, issuer: str
) -> tuple[str, str]:
    status, headers, _ = await bounded_response(client, "GET", server)
    if status != 401:
        raise LabRejected("missing_authentication_challenge")
    advertised = re.findall(r'resource_metadata="([^"]+)"', headers.get("www-authenticate", ""))
    public = urlsplit(resource)
    expected = urlunsplit(
        (
            public.scheme,
            public.netloc,
            "/.well-known/oauth-protected-resource" + public.path,
            "",
            "",
        )
    )
    if advertised != [expected]:
        raise LabRejected("resource_metadata_location")
    # Explicit lab mapping: only this verified path is fetched at the local backend.
    backend = urlsplit(server)
    local_metadata = urlunsplit((backend.scheme, backend.netloc, urlsplit(expected).path, "", ""))
    prm = await document(client, "GET", local_metadata)
    if prm.get("resource") != resource or prm.get("authorization_servers") != [issuer]:
        raise LabRejected("protected_resource_identity")
    if "workspace:read" not in prm.get("scopes_supported", []):
        raise LabRejected("protected_resource_scope")
    metadata = await document(client, "GET", issuer + ".well-known/openid-configuration")
    if metadata.get("issuer") != issuer:
        raise LabRejected("metadata_issuer")
    if "S256" not in metadata.get("code_challenge_methods_supported", []):
        raise LabRejected("pkce_not_advertised")
    authorization_endpoint = pinned_endpoint(metadata.get("authorization_endpoint"), issuer)
    token_endpoint = pinned_endpoint(metadata.get("token_endpoint"), issuer)
    pinned_endpoint(metadata.get("jwks_uri"), issuer)
    return authorization_endpoint, token_endpoint


async def obtain_token(
    client: httpx2.AsyncClient,
    issuer: str,
    client_id: str,
    resource: str,
    scope: str,
    authorization_endpoint: str,
    token_endpoint: str,
) -> str:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    state = secrets.token_urlsafe(32)
    authorization_url = (
        authorization_endpoint
        + "?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "scope": scope,
                "resource": resource,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "prompt": "login",
            }
        )
    )
    print("Complete the authorization in your local browser; no token will be printed.")
    code = await asyncio.to_thread(browser_code, authorization_url, state, issuer)
    result = await document(
        client,
        "POST",
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code": code,
            "code_verifier": verifier,
            "resource": resource,
        },
    )
    token = result.get("access_token")
    if (
        result.get("token_type", "").lower() != "bearer"
        or not isinstance(token, str)
        or not token
        or len(token) > 16_384
        or not token.isascii()
        or any(ord(c) < 33 or ord(c) > 126 for c in token)
    ):
        raise LabRejected("access_token_format")
    return token


async def observed_read(server: str, token: str) -> dict[str, object]:
    async with (
        httpx2.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=20,
            headers={"Authorization": f"Bearer {token}"},
        ) as http,
        Client(streamable_http_client(server, http_client=http), mode=PROTOCOL, cache=None) as mcp,
    ):
        tools = await mcp.list_tools()
        resources = await mcp.list_resources()
        prompts = await mcp.list_prompts()
        names = sorted(t.name for t in tools.tools)
        if names != ["list_workspace_directory", "read_workspace_text"]:
            raise LabRejected("read_only_surface")
        result = await mcp.call_tool(
            "read_workspace_text", {"root_id": "root-1", "relative_path": "canary.txt"}
        )
        content = result.structured_content
        if result.is_error or not isinstance(content, dict):
            raise LabRejected("authenticated_read")
        content = cast(dict[str, Any], content)
        if (
            content.get("content") != CANARY.decode("utf-8")
            or content.get("sha256") != hashlib.sha256(CANARY).hexdigest()
            or content.get("bytes_read") != len(CANARY)
        ):
            raise LabRejected("synthetic_corpus_identity")
        return {
            "protocol": mcp.protocol_version,
            "tools": names,
            "resources": sorted(str(r.uri) for r in resources.resources),
            "prompts": sorted(p.name for p in prompts.prompts),
            "read_is_error": False,
            "bytes_read": len(CANARY),
            "canary_sha256": hashlib.sha256(CANARY).hexdigest(),
        }


async def refusal(client: httpx2.AsyncClient, server: str, token: str, expected: int) -> int:
    status, response_headers, body = await bounded_response(
        client,
        "POST",
        server,
        headers={
            "Authorization": f"Bearer {token}",
            "MCP-Protocol-Version": PROTOCOL,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "read_workspace_text",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 71,
            "method": "tools/call",
            "params": {
                "name": "read_workspace_text",
                "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
            },
        },
    )
    if (
        status != expected
        or CANARY in body
        or token.encode("ascii") in body
        or token in str(response_headers)
    ):
        raise LabRejected("refusal_outcome")
    return status


def candidate_identity() -> tuple[str, str]:
    root = Path(__file__).resolve().parents[2]
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
    )
    if status.stdout.strip():
        raise LabRejected("commit_or_stash_source_changes_first")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return revision, hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()


async def run(args: argparse.Namespace) -> dict[str, object]:
    revision, lock_digest = candidate_identity()
    issuer, resource = checked_url(args.issuer), checked_url(args.resource)
    server = checked_url(args.server_url, loopback=True)
    if urlsplit(issuer).path != "/" or not issuer.endswith("/"):
        raise LabRejected("auth0_issuer_requires_trailing_slash")
    if args.scope not in {"workspace:read", "workspace:probe"}:
        raise LabRejected("selected_lab_scope")
    token_resource = checked_url(args.token_resource or resource)
    async with httpx2.AsyncClient(trust_env=False, follow_redirects=False, timeout=20) as http:
        authorization_endpoint, token_endpoint = await discover(http, server, resource, issuer)
        token = await obtain_token(
            http,
            issuer,
            args.client_id,
            token_resource,
            args.scope,
            authorization_endpoint,
            token_endpoint,
        )
        if args.expect_status == 200:
            observed = await observed_read(server, token)
            observed["malformed_token_http_status"] = await refusal(
                http, server, "invalid.lab.token", 401
            )
        else:
            observed = {
                "refusal_http_status": await refusal(http, server, token, args.expect_status),
                "canary_not_returned": True,
            }
    if candidate_identity() != (revision, lock_digest):
        raise LabRejected("source_changed_during_run")
    return {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "external_issuer_browser_code_pkce_and_mcp_network",
        "issuer": issuer,
        "client_id": args.client_id,
        "resource": resource,
        "token_resource": token_resource,
        "requested_scope": args.scope,
        "redirect_uri": REDIRECT,
        "server_url": server,
        "source_revision": revision,
        "lock_sha256": lock_digest,
        "python": platform.python_version(),
        "mcp": importlib.metadata.version("mcp"),
        "profile": "read-only",
        "fixture_generation": "synthetic-g1",
        "resource_metadata_checked": True,
        "issuer_metadata_checked": True,
        "authorization_response_issuer_and_state_checked": True,
        "resource_in_authorization_and_token_requests": True,
        "pkce": "S256",
        "observed": observed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--resource", default="https://mcp.example.com/mcp")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--scope", default="workspace:read")
    parser.add_argument("--token-resource")
    parser.add_argument("--expect-status", type=int, choices=[200, 401, 403], default=200)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)  # Dependency exception paths may retain credentials.
    try:
        if args.evidence.exists():
            raise LabRejected("evidence_exists")
        evidence = asyncio.run(run(args))
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        with args.evidence.open("x", encoding="utf-8") as output:
            json.dump(evidence, output, indent=2)
            output.write("\n")
    except Exception as exc:
        category = str(exc) if isinstance(exc, LabRejected) else "local_or_network_failure"
        print(f"live_auth_failed: {category}", file=sys.stderr)
        return 2
    print("live_auth_passed: sanitized evidence saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
