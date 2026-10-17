from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from .config import ServerSettings


class SecuritySettings(ServerSettings):
    """Explicit inputs for the authenticated, single-process HTTP construction."""

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=None,
        enable_decoding=False,
        extra="ignore",
        hide_input_in_errors=True,
    )
    security_profile: Literal["read-only", "mutation-lab"] = "read-only"
    http_require_auth: bool = True
    jwks_url: AnyHttpUrl
    allowed_client_ids: tuple[str, ...] = ()
    corpus_approval_file: Path | None = None
    mutation_lab_confirmed: bool = False
    ingress_slots: int = Field(default=16, ge=1, le=128)
    global_slots: int = Field(default=4, ge=1, le=32)
    principal_slots: int = Field(default=1, ge=1, le=8)
    request_deadline_seconds: float = Field(default=5, ge=0.1, le=30)
    jwks_cache_seconds: float = Field(default=60, ge=5, le=300)
    jwks_refresh_seconds: float = Field(default=5, ge=1, le=60)
    max_token_lifetime_seconds: int = Field(default=900, ge=60, le=3600)

    @field_validator("allowed_client_ids", mode="before")
    @classmethod
    def _clients(cls, value: object) -> tuple[str, ...]:
        return cls._parse_csv(value)

    @model_validator(mode="after")
    def _security_policy(self) -> SecuritySettings:
        if not self.http_require_auth or not self.enable_workspace:
            raise ValueError("the security profile requires authenticated workspace HTTP")
        if self.enable_github or self.enable_browser:
            raise ValueError("the security profile permits only the workspace surface")
        for url in (self.auth_issuer_url, self.auth_resource_url, self.jwks_url):
            if (
                url is None
                or url.scheme != "https"
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "security URLs require HTTPS without credentials, query or fragment"
                )
        if not self.allowed_client_ids or "workspace:read" not in self.auth_required_scopes:
            raise ValueError("approved clients and the workspace:read scope are required")
        if len(self.workspace_roots) != 1:
            raise ValueError("the security profile requires one approved workspace root")
        if self.principal_slots > self.global_slots or self.global_slots > self.ingress_slots:
            raise ValueError("principal slots must not exceed global slots or ingress slots")
        if self.jwks_refresh_seconds > self.jwks_cache_seconds:
            raise ValueError("key refresh spacing must not exceed cache lifetime")
        if self.security_profile == "read-only":
            if self.enable_mutation or self.corpus_approval_file is None:
                raise ValueError("read-only requires a corpus approval file and disabled mutation")
            approval = self.corpus_approval_file
            if not approval.is_absolute() or approval.resolve().is_relative_to(
                self.workspace_roots[0]
            ):
                raise ValueError("the approval file must be absolute and outside the corpus")
        elif not self.enable_mutation or not self.mutation_lab_confirmed:
            raise ValueError(
                "mutation-lab requires enabled mutation and explicit disposable-data confirmation"
            )
        return self
