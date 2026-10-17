from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx2
import pytest
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError

from build_an_mcp_server.auth_verifier import JwtVerifier
from build_an_mcp_server.corpus_policy import CorpusRejected, validate_corpus
from tests.security.secure_helpers import JWKS, RESOURCE, SigningFixture, settings_for


@pytest.mark.anyio
@pytest.mark.parametrize("private_parameter", ["d", "p", "q", "dp", "dq", "qi", "oth"])
async def test_verifier_rejects_private_rsa_parameters(
    tmp_path: Path, private_parameter: str
) -> None:
    signer = SigningFixture()
    document = signer.jwks()
    private_jwk = json.loads(RSAAlgorithm.to_jwk(signer.key))
    document["keys"][0][private_parameter] = private_jwk.get(
        private_parameter, [{"r": "AQ", "d": "AQ", "t": "AQ"}]
    )
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=document))
    ) as client:
        verifier = JwtVerifier(settings_for(tmp_path), client)
        assert await verifier.verify_token(signer.token()) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"enable_mutation": True},
        {"enable_browser": True},
        {"enable_github": True},
        {"http_require_auth": False},
        {"auth_resource_url": "http://mcp.example.com/mcp"},
        {"allowed_client_ids": ()},
        {"auth_required_scopes": ()},
        {"principal_slots": 5},
        {"jwks_cache_seconds": 5, "jwks_refresh_seconds": 6},
        {"security_profile": "mutation-lab", "enable_mutation": True},
    ],
)
def test_profile_rejects_incomplete_or_incompatible_inputs(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        settings_for(tmp_path, **changes)


@pytest.mark.parametrize(
    "fault",
    ["extra", "excluded", "changed", "missing", "symlink", "directory", "oversize", "binary"],
)
def test_corpus_rejects_entire_invalid_generation(tmp_path: Path, fault: str) -> None:
    settings = settings_for(tmp_path)
    root, approval = settings.workspace_roots[0], settings.corpus_approval_file
    assert approval is not None
    assert validate_corpus(root, approval) == "g1"
    if fault == "extra":
        (root / "extra.txt").write_text("not approved")
    elif fault == "excluded":
        (root / "private.txt").write_text("synthetic-secret")
    elif fault == "changed":
        (root / "canary.txt").write_text("different")
    elif fault == "missing":
        (root / "canary.txt").unlink()
    elif fault == "symlink":
        (root / "linked.txt").symlink_to(root / "canary.txt")
    elif fault == "directory":
        (root / "unapproved").mkdir()
    elif fault == "oversize":
        (root / "canary.txt").write_bytes(b"x" * 65537)
    else:
        (root / "canary.txt").write_bytes(b"\xff")
    with pytest.raises(CorpusRejected, match="approval policy"):
        validate_corpus(root, approval)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "https://another.example.com/mcp"},
        {"iss": "https://other.example.com/tenant"},
        {"exp": 1},
        {"nbf": int(time.time()) + 3600},
        {"sub": ""},
        {"client_id": "unapproved"},
        {"scope": ["workspace:read"]},
        {"scope": "workspace:read\nworkspace:write"},
        {"iat": True},
        {"exp": int(time.time()) + 7200},
        {"aud": [RESOURCE]},
    ],
)
async def test_real_verifier_rejects_claim_failures(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    signer = SigningFixture()
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=signer.jwks()))
    ) as client:
        verifier = JwtVerifier(settings_for(tmp_path), client)
        assert await verifier.verify_token(signer.token(**changes)) is None


@pytest.mark.anyio
async def test_verifier_trusts_only_configured_keys_and_requires_claims(tmp_path: Path) -> None:
    signer, other = SigningFixture(), SigningFixture()
    visited: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        visited.append(str(request.url))
        return httpx2.Response(200, json=signer.jwks())

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        verifier = JwtVerifier(settings_for(tmp_path), client)
        accepted = await verifier.verify_token(signer.token())
        assert accepted is not None and accepted.subject == "reader-1"
        assert accepted.resource == RESOURCE
        assert await verifier.verify_token(other.token()) is None
        for missing in ("iss", "sub", "aud", "exp", "iat", "client_id", "scope"):
            assert await verifier.verify_token(signer.token(omit=missing)) is None
        for header in (
            {"typ": "JWT"},
            {"jku": "https://untrusted.example/keys"},
            {"kid": "unknown"},
        ):
            assert await verifier.verify_token(signer.token(headers=header)) is None
        assert await verifier.verify_token("x" * 16385) is None
        assert visited == [JWKS]


@pytest.mark.anyio
async def test_rotation_cooldown_expiry_and_outage(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    old, new = SigningFixture("old"), SigningFixture("new")
    now = [100.0]
    calls = 0
    payload: dict[str, Any] = old.jwks()
    status = 200

    def respond(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(status, json=payload)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        verifier = JwtVerifier(settings_for(tmp_path), client, clock=lambda: now[0])
        assert await verifier.verify_token(old.token()) is not None
        for n in range(20):
            assert await verifier.verify_token(old.token(headers={"kid": f"unknown-{n}"})) is None
        assert calls == 1
        payload = new.jwks()
        now[0] += 5
        assert await verifier.verify_token(new.token()) is not None
        assert await verifier.verify_token(old.token()) is None
        status = 503
        now[0] += 60
        for _ in range(5):
            assert await verifier.verify_token(new.token()) is None
        assert calls == 3
        assert caplog.text.count("verification_dependency_unavailable") == 1
        assert new.token() not in caplog.text
        status = 200
        now[0] += 5
        assert await verifier.verify_token(new.token()) is not None


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["redirect", "large", "bad_json", "many_keys", "timeout"])
async def test_key_dependency_is_bounded_and_fails_closed(tmp_path: Path, fault: str) -> None:
    signer = SigningFixture()
    calls = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        if fault == "timeout":
            raise httpx2.ReadTimeout("synthetic-key-secret", request=request)
        if fault == "redirect":
            return httpx2.Response(302, headers={"Location": "https://untrusted.example/keys"})
        if fault == "large":
            return httpx2.Response(200, content=b"x" * 65537)
        if fault == "bad_json":
            return httpx2.Response(200, content=b"not json")
        document = signer.jwks()
        return httpx2.Response(200, content=json.dumps({"keys": document["keys"] * 9}))

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(respond), follow_redirects=False
    ) as client:
        verifier = JwtVerifier(settings_for(tmp_path), client)
        assert await verifier.verify_token(signer.token()) is None
        assert calls == 1
