from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, cast

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from build_an_mcp_server.security_config import SecuritySettings

ISSUER = "https://issuer.example.com/tenant"
RESOURCE = "https://mcp.example.com/mcp"
JWKS = "https://issuer.example.com/keys"


class ExplicitSecuritySettings(SecuritySettings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def settings_for(tmp_path: Path, **changes: object) -> SecuritySettings:
    root = tmp_path / "corpus"
    root.mkdir(exist_ok=True)
    (root / "canary.txt").write_text("approved\n", encoding="utf-8")
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "generation": "g1",
                "files": {"canary.txt": hashlib.sha256(b"approved\n").hexdigest()},
                "excluded": ["private.txt"],
            }
        )
    )
    values: dict[str, object] = {
        "workspace_roots": (root,),
        "enable_github": False,
        "enable_browser": False,
        "enable_mutation": False,
        "auth_issuer_url": ISSUER,
        "auth_resource_url": RESOURCE,
        "auth_required_scopes": ("workspace:read",),
        "jwks_url": JWKS,
        "allowed_client_ids": ("reader-client", "second-client"),
        "corpus_approval_file": approval,
    }
    values.update(changes)
    return cast(SecuritySettings, cast(Any, ExplicitSecuritySettings)(**values))


class SigningFixture:
    def __init__(self, kid: str = "test-key") -> None:
        self.kid = kid
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict[str, Any]:
        key: dict[str, object] = json.loads(RSAAlgorithm.to_jwk(self.key.public_key()))
        key.update(kid=self.kid, alg="RS256", use="sig", key_ops=["verify"])
        return {"keys": [key]}

    def token(
        self, *, headers: dict[str, Any] | None = None, omit: str | None = None, **changes: object
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": RESOURCE,
            "sub": "reader-1",
            "client_id": "reader-client",
            "iat": now,
            "exp": now + 300,
            "scope": "workspace:read",
        }
        claims.update(changes)
        if omit is not None:
            del claims[omit]
        return jwt.encode(
            claims,
            self.key,
            algorithm="RS256",
            headers={"typ": "at+jwt", "kid": self.kid} | (headers or {}),
        )
