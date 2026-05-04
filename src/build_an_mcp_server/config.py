from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    """Validated startup policy for the MCP server runtime."""

    server_name: str = Field(
        default="Build an MCP from Scratch",
        alias="SERVER_NAME",
    )

    enable_filesystem: bool = Field(default=True, alias="ENABLE_FILESYSTEM")
    enable_github: bool = Field(default=False, alias="ENABLE_GITHUB")
    enable_browser: bool = Field(default=False, alias="ENABLE_BROWSER")
    read_only: bool = Field(default=False, alias="READ_ONLY")

    fs_allowed_dirs: tuple[Path, ...] = Field(
        default_factory=tuple,
        alias="FS_ALLOWED_DIRS",
    )
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        enable_decoding=False,
    )

    @field_validator("fs_allowed_dirs", mode="before")
    @classmethod
    def _parse_fs_allowed_dirs(cls, value: object) -> tuple[Path, ...]:
        if value is None or value == "":
            return ()

        if isinstance(value, str):
            parts = [
                item.strip()
                for item in value.split(os.pathsep)
                if item.strip()
            ]
            return tuple(Path(item) for item in parts)

        if isinstance(value, (list, tuple, set)):
            return tuple(Path(item) for item in value)

        raise TypeError(
            "FS_ALLOWED_DIRS must be a path-separated string or a list of paths."
        )

    @model_validator(mode="after")
    def _validate_runtime_policy(self) -> "ServerSettings":
        resolved_roots = tuple(
            path.expanduser().resolve()
            for path in self.fs_allowed_dirs
        )

        if self.enable_filesystem and not resolved_roots:
            resolved_roots = (Path.cwd().resolve(),)

        self.fs_allowed_dirs = resolved_roots

        if self.enable_github and not self.github_token:
            raise ValueError(
                "ENABLE_GITHUB is true, but GITHUB_TOKEN is not configured."
            )

        return self


def load_settings() -> ServerSettings:
    """Load and validate runtime settings once at startup."""

    return ServerSettings()
