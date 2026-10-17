from __future__ import annotations

import base64
import threading
from pathlib import Path
from typing import Any, cast

import anyio
import httpx2
import pytest
from anyio.to_thread import run_sync
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from build_an_mcp_server.admission import WorkSlots
from build_an_mcp_server.models import TextFileRead
from build_an_mcp_server.secure_http import create_secure_app
from build_an_mcp_server.workspace import WorkspaceAdapter
from tests.security.secure_helpers import RESOURCE, SigningFixture, settings_for
from tests.security.test_http_auth import (
    BASE_URL,
    PROTOCOL_VERSION,
    _headers,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
    _write_request,  # pyright: ignore[reportPrivateUsage]
)


@pytest.mark.anyio
async def test_real_verifier_sdk_read_and_denial_before_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = SigningFixture()
    settings = settings_for(tmp_path)
    app = create_secure_app(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks()))
    )
    calls: list[str] = []
    original = WorkspaceAdapter.read_text

    def observed(
        self: WorkspaceAdapter, root_id: str, relative_path: str, *, offset_bytes: int
    ) -> TextFileRead:
        calls.append(relative_path)
        return original(self, root_id, relative_path, offset_bytes=offset_bytes)

    monkeypatch.setattr(WorkspaceAdapter, "read_text", observed)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {signer.token()}"},
        ) as http,
    ):
        async with Client(
            streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
            mode=PROTOCOL_VERSION,
            cache=None,
        ) as client:
            result = await client.call_tool(
                "read_workspace_text", {"root_id": "root-1", "relative_path": "canary.txt"}
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["content"] == "approved\n"
        assert calls == ["canary.txt"]
        calls.clear()
        requests: list[tuple[str, dict[str, Any], str | None, int]] = [
            (
                "tools/call",
                {
                    "name": "read_workspace_text",
                    "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
                },
                "read_workspace_text",
                401,
            ),
            ("resources/read", {"uri": "workspace://manifest"}, "workspace://manifest", 403),
            (
                "prompts/get",
                {
                    "name": "review_workspace_file",
                    "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
                },
                "review_workspace_file",
                403,
            ),
        ]
        for method, params, name, status in requests:
            token = (
                signer.token(aud="https://other.example/mcp")
                if status == 401
                else signer.token(scope="other")
            )
            response = await http.post(
                "/mcp",
                headers=_headers(method, token=token, name=name),
                json=_request(method, params),
            )
            assert response.status_code == status
            assert "approved" not in response.text and token not in response.text
            assert str(settings.workspace_roots[0]) not in response.text
        assert calls == []
        metadata = await http.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["resource"] == RESOURCE
        for header, value, expected_status in (
            ("Origin", "https://untrusted.example", 403),
            ("Host", "untrusted.example", 421),
        ):
            token = signer.token()
            headers = _headers("tools/call", token=token, name="read_workspace_text") | {
                header: value
            }
            denied = await http.post(
                "/mcp",
                headers=headers,
                json=_request(
                    "tools/call",
                    {
                        "name": "read_workspace_text",
                        "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
                    },
                ),
            )
            assert denied.status_code == expected_status
            assert calls == []
            assert "approved" not in denied.text
            assert token not in denied.text
            assert str(settings.workspace_roots[0]) not in denied.text


@pytest.mark.anyio
async def test_authenticated_mutation_routing_and_reset(tmp_path: Path) -> None:
    signer = SigningFixture()
    settings = settings_for(
        tmp_path, security_profile="mutation-lab", enable_mutation=True, mutation_lab_confirmed=True
    )
    app = create_secure_app(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks()))
    )
    root = settings.workspace_roots[0]
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as client,
    ):
        encoded = "=?base64?" + base64.b64encode(b"write_workspace_text").decode() + "?="
        for name, expected in (
            ("write_workspace_text", 403),
            (encoded, 403),
            ("read_workspace_text", 400),
        ):
            response = await client.post(
                "/mcp",
                headers=_headers("tools/call", token=signer.token(), name=name),
                json=_write_request("notes.txt"),
            )
            assert response.status_code == expected
            assert sorted(p.name for p in root.iterdir()) == ["canary.txt"]
        response = await client.post(
            "/mcp",
            headers=_headers(
                "tools/call",
                token=signer.token(scope="workspace:read workspace:write"),
                name="write_workspace_text",
            ),
            json=_write_request("notes.txt"),
        )
        assert response.json()["result"]["isError"] is False
        assert (root / "notes.txt").read_text() == "verified\n"
    (root / "notes.txt").unlink()
    readonly = settings_for(tmp_path)
    fresh = create_secure_app(
        readonly, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks()))
    )
    async with (
        fresh.router.lifespan_context(fresh),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=fresh), base_url=BASE_URL) as client,
    ):
        response = await client.post(
            "/mcp",
            headers=_headers("tools/list", token=signer.token()),
            json=_request("tools/list"),
        )
        assert "write_workspace_text" not in {x["name"] for x in response.json()["result"]["tools"]}
        denied = await client.post(
            "/mcp",
            headers=_headers(
                "tools/call",
                token=signer.token(scope="workspace:read workspace:write"),
                name="write_workspace_text",
            ),
            json=_write_request("notes.txt"),
        )
        assert "error" in denied.json()
        assert not (root / "notes.txt").exists()


@pytest.mark.anyio
async def test_deadline_does_not_release_running_worker_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signer = SigningFixture()
    settings = settings_for(tmp_path, request_deadline_seconds=0.1)
    app = create_secure_app(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks()))
    )
    started, release = threading.Event(), threading.Event()
    original = WorkspaceAdapter.read_text

    def blocked(
        self: WorkspaceAdapter, root_id: str, relative_path: str, *, offset_bytes: int
    ) -> TextFileRead:
        started.set()
        assert release.wait(3)
        return original(self, root_id, relative_path, offset_bytes=offset_bytes)

    monkeypatch.setattr(WorkspaceAdapter, "read_text", blocked)
    replies: list[httpx2.Response] = []
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as client,
    ):

        async def read() -> None:
            replies.append(
                await client.post(
                    "/mcp",
                    headers=_headers(
                        "tools/call", token=signer.token(), name="read_workspace_text"
                    ),
                    json=_request(
                        "tools/call",
                        {
                            "name": "read_workspace_text",
                            "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
                        },
                    ),
                )
            )

        slots = cast(WorkSlots, app.state.work_slots)
        async with anyio.create_task_group() as group:
            group.start_soon(read)
            try:
                assert await run_sync(started.wait, 2)
                await anyio.sleep(0.15)
                assert slots.active == 1
                denied = await client.post(
                    "/mcp",
                    headers=_headers("tools/list", token=signer.token(client_id="second-client")),
                    json=_request("tools/list"),
                )
                assert denied.status_code == 503
            finally:
                release.set()
        assert replies[0].status_code == 504
        assert slots.active == 0 and slots.by_principal == {}
        recovered = await client.post(
            "/mcp",
            headers=_headers("tools/list", token=signer.token()),
            json=_request("tools/list"),
        )
        assert recovered.status_code == 200
