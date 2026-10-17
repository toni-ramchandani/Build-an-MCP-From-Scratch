from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

import anyio
import httpx2
import pytest
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from build_an_mcp_server.admission import AuthenticatedAdmission
from build_an_mcp_server.auth_verifier import JwtVerifier
from build_an_mcp_server.http_policy import HttpScopePolicy
from build_an_mcp_server.secure_http import create_secure_app
from tests.security.secure_helpers import SigningFixture, settings_for
from tests.security.test_http_auth import (
    BASE_URL,
    _headers,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)


def observe_callbacks(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls: dict[str, int] = {}

    def instrument(method_name: str) -> Callable[..., Any]:
        original: Any = getattr(MCPServer, method_name)

        def register(self: Any, *args: Any, **kwargs: Any) -> Callable[..., Any]:
            decorate: Any = original(self, *args, **kwargs)

            def accept(fn: Callable[..., Any]) -> Any:
                @wraps(fn)
                def observed(*values: Any, **named: Any) -> Any:
                    calls[fn.__name__] = calls.get(fn.__name__, 0) + 1
                    return fn(*values, **named)

                return decorate(observed)

            return accept

        return register

    for name in ("resource", "prompt", "tool"):
        monkeypatch.setattr(MCPServer, name, instrument(name))
    return calls


@pytest.mark.anyio
@pytest.mark.parametrize("surface", ["resource", "prompt", "write"])
async def test_scope_refusal_prevents_the_actual_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    calls = observe_callbacks(monkeypatch)
    signer = SigningFixture()
    settings = settings_for(
        tmp_path, security_profile="mutation-lab", enable_mutation=True, mutation_lab_confirmed=True
    )
    method, name, callback, params = {
        "resource": (
            "resources/read",
            "workspace://manifest",
            "workspace_manifest",
            {"uri": "workspace://manifest"},
        ),
        "prompt": (
            "prompts/get",
            "review_workspace_file",
            "review_workspace_file",
            {
                "name": "review_workspace_file",
                "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
            },
        ),
        "write": (
            "tools/call",
            "write_workspace_text",
            "write_workspace_text",
            {
                "name": "write_workspace_text",
                "arguments": {
                    "root_id": "root-1",
                    "relative_path": "notes.txt",
                    "content": "verified\n",
                    "expected_sha256": "absent",
                },
            },
        ),
    }[surface]
    app = create_secure_app(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks()))
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http,
    ):
        allowed = await http.post(
            "/mcp",
            headers=_headers(
                method, token=signer.token(scope="workspace:read workspace:write"), name=name
            ),
            json=_request(method, params),
        )
        assert allowed.status_code == 200 and "error" not in allowed.json()
        assert calls.get(callback) == 1
        target = settings.workspace_roots[0] / "notes.txt"
        if surface == "write":
            assert target.read_text() == "verified\n"
            target.unlink()
        calls.clear()
        scope = "workspace:read" if surface == "write" else "other"
        denied = await http.post(
            "/mcp",
            headers=_headers(method, token=signer.token(scope=scope), name=name),
            json=_request(method, params),
        )
        assert denied.status_code == 403
        assert calls == {}
        assert not target.exists()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "claim,value", [("exp", float("inf")), ("iat", float("-inf")), ("nbf", float("inf"))]
)
async def test_nonfinite_timestamp_returns_401_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, claim: str, value: float
) -> None:
    calls = observe_callbacks(monkeypatch)
    signer = SigningFixture()
    settings = settings_for(tmp_path)
    app = create_secure_app(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks()))
    )
    request = _request(
        "tools/call",
        {
            "name": "read_workspace_text",
            "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
        },
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http,
    ):
        allowed = await http.post(
            "/mcp",
            headers=_headers("tools/call", token=signer.token(), name="read_workspace_text"),
            json=request,
        )
        assert allowed.json()["result"]["isError"] is False
        assert calls == {"read_workspace_text": 1}
        calls.clear()
        changes: dict[str, Any] = {claim: value}
        token = signer.token(**changes)
        denied = await http.post(
            "/mcp",
            headers=_headers("tools/call", token=token, name="read_workspace_text"),
            json=request,
        )
        assert denied.status_code == 401 and calls == {}
        assert "approved" not in denied.text and token not in denied.text


@pytest.mark.anyio
@pytest.mark.parametrize("fault,status", [("duplicate", 400), ("oversize", 431)])
async def test_header_rejection_precedes_verification_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, status: int
) -> None:
    calls = observe_callbacks(monkeypatch)
    verified: list[str] = []
    original = JwtVerifier.verify_token

    async def observed(self: JwtVerifier, token: str) -> AccessToken | None:
        verified.append("entered")
        return await original(self, token)

    monkeypatch.setattr(JwtVerifier, "verify_token", observed)
    signer = SigningFixture()
    app = create_secure_app(
        settings_for(tmp_path),
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks())),
    )
    headers = _headers("tools/call", token=signer.token(), name="read_workspace_text")
    request = _request(
        "tools/call",
        {
            "name": "read_workspace_text",
            "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
        },
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http,
    ):
        allowed = await http.post("/mcp", headers=headers, json=request)
        assert allowed.json()["result"]["isError"] is False
        assert verified == ["entered"] and calls == {"read_workspace_text": 1}
        verified.clear()
        calls.clear()
        extra = (
            ("Authorization", "Bearer second-token")
            if fault == "duplicate"
            else ("X-Large", "x" * 24_577)
        )
        denied = await http.post("/mcp", headers=[*headers.items(), extra], json=request)
        assert denied.status_code == status
        assert verified == [] and calls == {}


@pytest.mark.anyio
async def test_global_admission_across_subjects_recovers(tmp_path: Path) -> None:
    signer = SigningFixture()
    settings = settings_for(tmp_path, ingress_slots=4, global_slots=2, principal_slots=1)
    app = create_secure_app(
        settings, transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks()))
    )
    route = next(route for route in app.routes if isinstance(route, Route) and route.path == "/mcp")
    assert isinstance(route, Route) and isinstance(route.app, HttpScopePolicy)
    admission = route.app.app
    assert isinstance(admission, AuthenticatedAdmission)
    original = admission.app
    entered: list[str] = []
    full, release = anyio.Event(), anyio.Event()

    async def held(scope: Scope, receive: Receive, send: Send) -> None:
        entered.append("entered")
        if len(entered) == 2:
            full.set()
        await release.wait()
        await original(scope, receive, send)

    admission.app = held
    responses: list[httpx2.Response] = []
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http,
    ):

        async def request(subject: str) -> httpx2.Response:
            return await http.post(
                "/mcp",
                headers=_headers("tools/list", token=signer.token(sub=subject)),
                json=_request("tools/list"),
            )

        async def occupy(subject: str) -> None:
            responses.append(await request(subject))

        async with anyio.create_task_group() as group:
            group.start_soon(occupy, "reader-a")
            group.start_soon(occupy, "reader-b")
            try:
                with anyio.fail_after(2):
                    await full.wait()
                assert admission.slots.active == 2 and len(admission.slots.by_principal) == 2
                denied = await request("reader-c")
                assert denied.status_code == 503 and len(entered) == 2
            finally:
                release.set()
        assert all(response.status_code == 200 for response in responses)
        assert admission.slots.active == 0 and admission.slots.by_principal == {}
        assert (await request("reader-c")).status_code == 200


@pytest.mark.anyio
async def test_ingress_refusal_precedes_verifier_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered: list[str] = []
    full, release = anyio.Event(), anyio.Event()
    original = JwtVerifier.verify_token

    async def held(self: JwtVerifier, token: str) -> AccessToken | None:
        entered.append("entered")
        if len(entered) == 2:
            full.set()
        await release.wait()
        return await original(self, token)

    monkeypatch.setattr(JwtVerifier, "verify_token", held)
    signer = SigningFixture()
    app = create_secure_app(
        settings_for(tmp_path, ingress_slots=2, global_slots=2),
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks())),
    )
    responses: list[httpx2.Response] = []
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http,
    ):

        async def request(subject: str) -> httpx2.Response:
            return await http.post(
                "/mcp",
                headers=_headers("tools/list", token=signer.token(sub=subject)),
                json=_request("tools/list"),
            )

        async def occupy(subject: str) -> None:
            responses.append(await request(subject))

        async with anyio.create_task_group() as group:
            group.start_soon(occupy, "reader-a")
            group.start_soon(occupy, "reader-b")
            try:
                with anyio.fail_after(2):
                    await full.wait()
                denied = await request("reader-c")
                assert denied.status_code == 503 and len(entered) == 2
            finally:
                release.set()
        assert all(response.status_code == 200 for response in responses)
        assert (await request("reader-c")).status_code == 200
        assert len(entered) == 3
