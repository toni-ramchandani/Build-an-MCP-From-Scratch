from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from build_an_mcp_server.config import (
    ServerSettings,
    load_settings,
)
from tests.helpers import make_settings


def test_workspace_requires_an_explicit_existing_root() -> None:
    expected_message = "enable_workspace is true, but no explicit workspace_roots are configured"

    with pytest.raises(
        ValidationError,
        match=expected_message,
    ):
        make_settings()


def test_workspace_root_must_be_absolute_and_exist(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValidationError,
        match="absolute path",
    ):
        make_settings(workspace_roots=(Path("relative"),))

    with pytest.raises(
        ValidationError,
        match="exist and resolve",
    ):
        make_settings(workspace_roots=(tmp_path / "missing",))


def test_workspace_root_must_be_directory(
    tmp_path: Path,
) -> None:
    configured_file = tmp_path / "not-a-directory.txt"
    configured_file.write_text(
        "not a workspace root",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="must be a directory",
    ):
        make_settings(workspace_roots=(configured_file,))


def test_safe_default_surface_uses_only_workspace(
    tmp_path: Path,
) -> None:
    settings = make_settings(workspace_roots=(tmp_path,))

    assert settings.enable_workspace is True
    assert settings.enable_github is False
    assert settings.github_timeout_seconds == 10
    assert settings.enable_mutation is False
    assert settings.enable_browser is False
    assert settings.http_host == "127.0.0.1"
    assert settings.max_write_bytes == 65_536
    assert settings.max_digest_bytes == 65_536


def test_github_requires_secret_and_repository_allowlist(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValidationError,
        match="github_token",
    ):
        make_settings(
            workspace_roots=(tmp_path,),
            enable_github=True,
            github_repositories=("owner/repository",),
        )

    with pytest.raises(
        ValidationError,
        match="github_token",
    ):
        make_settings(
            workspace_roots=(tmp_path,),
            enable_github=True,
            github_token="",
            github_repositories=("owner/repository",),
        )

    with pytest.raises(
        ValidationError,
        match="github_token",
    ):
        make_settings(
            workspace_roots=(tmp_path,),
            enable_github=True,
            github_token="not-a-real-token",
        )

    settings = make_settings(
        workspace_roots=(tmp_path,),
        enable_github=True,
        github_token="not-a-real-token",
        github_repositories=(
            "Owner/Repository",
            "owner/repository",
        ),
    )

    assert settings.github_repositories == ("owner/repository",)
    assert "not-a-real-token" not in repr(settings)


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://example.com/path",
        "file:///tmp/page.html",
        "https://user@example.com",
        "https://:password@example.com",
    ],
)
def test_browser_origin_policy_rejects_unsafe_or_non_origin_values(
    tmp_path: Path,
    origin: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="browser origin",
    ):
        make_settings(
            workspace_roots=(tmp_path,),
            enable_browser=True,
            browser_allowed_origins=(origin,),
        )


def test_non_loopback_http_is_rejected_until_deployment_policy_exists(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValidationError,
        match="loopback only",
    ):
        make_settings(
            workspace_roots=(tmp_path,),
            http_host="0.0.0.0",
        )

    with pytest.raises(
        ValidationError,
        match="loopback only",
    ):
        make_settings(
            workspace_roots=(tmp_path,),
            http_host="0.0.0.0",
            http_require_auth=True,
            auth_issuer_url=("https://issuer.example.com"),
            auth_resource_url=("https://mcp.example.com"),
        )


def test_load_settings_reads_only_mcp_prefixed_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    for name in tuple(os.environ):
        if name.startswith("MCP_"):
            monkeypatch.delenv(name)

    (tmp_path / ".env").write_text(
        "\n".join(
            [
                f"MCP_WORKSPACE_ROOTS={root}",
                "MCP_SERVER_NAME=Configured from dotenv",
                "UNRELATED_SETTING=ignored",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.workspace_roots == (root.resolve(),)
    assert settings.server_name == "Configured from dotenv"


def test_settings_source_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(os.environ):
        if name.startswith("MCP_"):
            monkeypatch.delenv(name)

    (tmp_path / ".env").write_text(
        ("MCP_ENABLE_WORKSPACE=false\nMCP_SERVER_NAME=dotenv-name\n"),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "MCP_SERVER_NAME",
        "environment-name",
    )

    from_environment = load_settings()

    from_constructor = ServerSettings(
        server_name="constructor-name",
        enable_workspace=False,
    )

    assert from_environment.server_name == "environment-name"
    assert from_constructor.server_name == "constructor-name"
