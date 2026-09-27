from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ServerSettings(BaseSettings):
    """Fail-before-start configuration for the book's MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        enable_decoding=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    server_name: str = "Build an MCP from Scratch"
    enable_workspace: bool = True
    workspace_roots: tuple[Path, ...] = ()

    enable_github: bool = False
    github_token: SecretStr | None = None
    github_repositories: tuple[str, ...] = ()
    github_timeout_seconds: int = Field(default=10, ge=1, le=60)

    enable_mutation: bool = False

    enable_browser: bool = False
    browser_allowed_origins: tuple[str, ...] = ()
    browser_max_handles: int = Field(default=4, ge=1, le=16)
    browser_handle_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    browser_navigation_timeout_ms: int = Field(
        default=10_000,
        ge=1_000,
        le=60_000,
    )

    http_host: str = "127.0.0.1"
    http_port: int = Field(default=8000, ge=1, le=65535)
    http_require_auth: bool = False
    auth_issuer_url: AnyHttpUrl | None = None
    auth_resource_url: AnyHttpUrl | None = None
    auth_required_scopes: tuple[str, ...] = ("workspace:read",)

    max_file_read_bytes: int = Field(
        default=65_536,
        ge=1_024,
        le=1_048_576,
    )
    max_directory_entries: int = Field(
        default=200,
        ge=1,
        le=1_000,
    )
    max_write_bytes: int = Field(
        default=65_536,
        ge=1_024,
        le=1_048_576,
    )
    max_digest_bytes: int = Field(
        default=65_536,
        ge=1_024,
        le=1_048_576,
    )
    max_github_body_chars: int = Field(
        default=12_000,
        ge=1_000,
        le=100_000,
    )
    max_browser_text_chars: int = Field(
        default=32_768,
        ge=1_000,
        le=100_000,
    )
    max_http_request_bytes: int = Field(
        default=1_048_576,
        ge=65_536,
        le=4_194_304,
    )

    log_level: str = "INFO"

    @field_validator("workspace_roots", mode="before")
    @classmethod
    def _parse_workspace_roots(
        cls,
        value: object,
    ) -> tuple[Path, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            return tuple(Path(item.strip()) for item in value.split(os.pathsep) if item.strip())
        if isinstance(value, list | tuple | set):
            items = cast(Iterable[object], value)
            return tuple(Path(str(item)) for item in items)
        raise TypeError("workspace_roots must be a path-separated string or a sequence of paths")

    @field_validator(
        "github_repositories",
        "browser_allowed_origins",
        "auth_required_scopes",
        mode="before",
    )
    @classmethod
    def _parse_csv(
        cls,
        value: object,
    ) -> tuple[str, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        if isinstance(value, list | tuple | set):
            items = cast(Iterable[object], value)
            return tuple(str(item).strip() for item in items if str(item).strip())
        raise TypeError("value must be a comma-separated string or a sequence")

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(
        cls,
        value: str,
    ) -> str:
        normalized = value.upper()
        if normalized not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            raise ValueError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return normalized

    @model_validator(mode="after")
    def _validate_policy(self) -> ServerSettings:
        self.workspace_roots = self._validated_roots(self.workspace_roots)

        if self.enable_workspace and not self.workspace_roots:
            raise ValueError(
                "enable_workspace is true, but no explicit workspace_roots are configured"
            )

        if self.enable_mutation and not self.enable_workspace:
            raise ValueError("enable_mutation requires enable_workspace")

        repositories = tuple(dict.fromkeys(repo.lower() for repo in self.github_repositories))

        if any(not _REPOSITORY_PATTERN.fullmatch(repo) for repo in repositories):
            raise ValueError("github_repositories entries must use the owner/repository form")

        self.github_repositories = repositories

        missing_github_token = (
            self.github_token is None or not self.github_token.get_secret_value().strip()
        )

        if self.enable_github and (missing_github_token or not repositories):
            raise ValueError(
                "enable_github requires github_token and at least one allowed github_repository"
            )

        self.browser_allowed_origins = self._validated_origins(self.browser_allowed_origins)

        if self.enable_browser and not self.browser_allowed_origins:
            raise ValueError("enable_browser requires at least one exact browser_allowed_origin")

        if self.http_host not in _LOOPBACK_HOSTS:
            raise ValueError(
                "the repository HTTP entry point supports loopback "
                "only; remote deployment requires a separately "
                "approved origin/host policy"
            )

        if self.http_require_auth and (
            self.auth_issuer_url is None or self.auth_resource_url is None
        ):
            raise ValueError("http_require_auth requires auth_issuer_url and auth_resource_url")

        if self.http_require_auth and not self.auth_required_scopes:
            raise ValueError("http_require_auth requires at least one auth_required_scope")

        return self

    @staticmethod
    def _validated_roots(
        roots: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        resolved: list[Path] = []

        for configured in roots:
            if not configured.is_absolute():
                raise ValueError("every workspace root must be an absolute path")

            try:
                root = configured.expanduser().resolve(strict=True)
            except OSError as exc:
                raise ValueError("every workspace root must exist and resolve") from exc

            if not root.is_dir():
                raise ValueError("every workspace root must be a directory")

            if root not in resolved:
                resolved.append(root)

        return tuple(resolved)

    @staticmethod
    def _validated_origins(
        origins: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized: list[str] = []

        for origin in origins:
            parsed = urlsplit(origin)

            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("browser origins must use http or https")

            if (
                parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError(
                    "browser origins must be exact origins without path, query, or userinfo"
                )

            if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
                raise ValueError("non-loopback browser origins must use https")

            rendered = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

            if rendered not in normalized:
                normalized.append(rendered)

        return tuple(normalized)


def load_settings() -> ServerSettings:
    """Load `.env` and process environment values, then validate the full policy."""

    return ServerSettings()
