from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
import pytest

from examples.ch07.live_auth import (
    LabRejected,
    callback_code,
    checked_url,
    discover,
    obtain_token,
    pinned_endpoint,
)

ISSUER = "https://book.example.auth0.com/"
RESOURCE = "https://mcp.example.com/mcp"


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example/mcp",
        "https://u:p@example.com/mcp",
        "https://example.com/?x=1",
        "https://example.com/#token",
        "http://localhost:8000/mcp",
    ],
)
def test_bearer_target_rejects_unsafe_destination(url: str) -> None:
    with pytest.raises(LabRejected):
        checked_url(url, loopback=True)


def test_callback_rejects_mixup_and_duplicate_code() -> None:
    valid = {"code": "one-use-code", "state": "expected", "iss": ISSUER}
    assert callback_code("/callback?" + urlencode(valid), "expected", ISSUER) == "one-use-code"
    for change in (
        {"iss": "https://different.example/"},
        {"iss": ISSUER.rstrip("/")},
        {"state": "different"},
        {"state": ""},
        {"code": ""},
    ):
        with pytest.raises(LabRejected):
            callback_code("/callback?" + urlencode(valid | change), "expected", ISSUER)
    with pytest.raises(LabRejected):
        callback_code("/callback?" + urlencode(valid) + "&code=second", "expected", ISSUER)
    with pytest.raises(LabRejected):
        callback_code("//attacker.example/callback?" + urlencode(valid), "expected", ISSUER)


def test_endpoints_remain_pinned_to_the_selected_issuer() -> None:
    assert pinned_endpoint(ISSUER + "oauth/token", ISSUER) == ISSUER + "oauth/token"
    with pytest.raises(LabRejected):
        pinned_endpoint("https://attacker.example/token", ISSUER)


def test_wrong_resource_metadata_does_not_trigger_issuer_requests() -> None:
    visits: list[str] = []

    def transport(request: httpx2.Request) -> httpx2.Response:
        visits.append(str(request.url))
        if request.url.path == "/mcp":
            return httpx2.Response(
                401,
                headers={
                    "www-authenticate": (
                        'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"'
                    )
                },
            )
        return httpx2.Response(
            200,
            json={
                "resource": RESOURCE,
                "authorization_servers": ["https://attacker.example/"],
                "scopes_supported": ["workspace:read"],
            },
        )

    async def scenario() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(transport)) as client:
            with pytest.raises(LabRejected, match="protected_resource_identity"):
                await discover(client, "http://127.0.0.1:8000/mcp", RESOURCE, ISSUER)

    asyncio.run(scenario())
    assert len(visits) == 2
    assert all(url.startswith("http://127.0.0.1:8000/") for url in visits)


def test_pkce_resource_and_no_token_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    authorization: dict[str, list[str]] = {}
    token_form: dict[str, list[str]] = {}

    def browser(url: str, state: str, issuer: str) -> str:
        authorization.update(parse_qs(urlsplit(url).query))
        assert authorization["state"] == [state]
        assert issuer == ISSUER
        return "one-use-code"

    def transport(request: httpx2.Request) -> httpx2.Response:
        token_form.update(parse_qs(request.content.decode()))
        return httpx2.Response(
            200, json={"access_token": "secret-bearer-canary", "token_type": "Bearer"}
        )

    monkeypatch.setattr("examples.ch07.live_auth.browser_code", browser)

    async def scenario() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(transport)) as client:
            token = await obtain_token(
                client,
                ISSUER,
                "reader-client",
                RESOURCE,
                "workspace:read",
                ISSUER + "authorize",
                ISSUER + "oauth/token",
            )
            assert token == "secret-bearer-canary"

    asyncio.run(scenario())
    assert authorization["resource"] == token_form["resource"] == [RESOURCE]
    assert authorization["code_challenge_method"] == ["S256"]
    assert token_form["grant_type"] == ["authorization_code"]
    assert "client_secret" not in token_form
    assert len(token_form["code_verifier"][0]) >= 43
    import base64
    import hashlib

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(token_form["code_verifier"][0].encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert authorization["code_challenge"] == [expected]
    output = capsys.readouterr()
    assert "secret-bearer-canary" not in output.out + output.err
    assert "one-use-code" not in output.out + output.err
