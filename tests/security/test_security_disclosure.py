from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
from pydantic import ValidationError

from build_an_mcp_server import secure_http
from build_an_mcp_server.security_config import SecuritySettings
from tests.security.secure_helpers import SigningFixture, settings_for
from tests.security.test_http_auth import (
    BASE_URL,
    _headers,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)

TOKEN_CANARY = "synthetic-token-disclosure-canary"
PRIVATE_PATH_CANARY = "private-path-disclosure-canary"
TRACEBACK_CANARY = "traceback-disclosure-canary"
PAYLOAD_CANARY = "upstream-payload-disclosure-canary"
CANARIES = (TOKEN_CANARY, PRIVATE_PATH_CANARY, TRACEBACK_CANARY, PAYLOAD_CANARY)


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["timeout", "malformed_document"])
async def test_verifier_failure_exports_only_safe_diagnostics(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, fault: str
) -> None:
    signer = SigningFixture()
    access_token = signer.token(sub=TOKEN_CANARY)
    payload = "|".join(CANARIES)
    visits: list[str] = []

    def failed_keys(request: httpx2.Request) -> httpx2.Response:
        visits.append(str(request.url))
        if fault == "timeout":
            raise httpx2.ReadTimeout(payload, request=request)
        return httpx2.Response(200, content=payload)

    app = secure_http.create_secure_app(
        settings_for(tmp_path), transport=httpx2.MockTransport(failed_keys)
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http,
    ):
        response = await http.post(
            "/mcp",
            headers=_headers("tools/call", token=access_token, name="read_workspace_text"),
            json=_request(
                "tools/call",
                {
                    "name": "read_workspace_text",
                    "arguments": {"root_id": "root-1", "relative_path": "canary.txt"},
                },
            ),
        )
    evidence = "\n".join((response.text, str(response.headers), caplog.text))
    assert response.status_code == 401
    assert len(visits) == 1
    assert "approved" not in response.text
    for canary in (*CANARIES, access_token, str(tmp_path)):
        assert canary not in evidence
    assert caplog.text.count("verification_dependency_unavailable") == 1


def test_secure_startup_does_not_export_raw_validation_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(ValidationError) as rejected:
        settings_for(tmp_path, jwks_url="https://issuer.example/keys?" + "|".join(CANARIES))
    error = rejected.value
    # This proves that serializing the raw validation object would expose inputs.
    assert all(canary in error.json() for canary in CANARIES)

    def invalid_settings() -> SecuritySettings:
        raise error

    monkeypatch.setattr(secure_http, "SecuritySettings", invalid_settings)
    with pytest.raises(SystemExit) as stopped:
        secure_http.main()
    captured = capsys.readouterr()
    evidence = "\n".join((captured.out, captured.err, caplog.text))
    assert stopped.value.code == 2
    assert captured.out == ""
    assert caplog.text.count("security_configuration_rejected") == 1
    assert "Traceback (most recent call last)" not in evidence
    for canary in (*CANARIES, str(tmp_path)):
        assert canary not in evidence
