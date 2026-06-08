from __future__ import annotations

import os
from pathlib import Path

import pytest

from build_an_mcp_server.config import ServerSettings


def test_filesystem_enabled_requires_allowed_roots() -> None:
    with pytest.raises(ValueError, match="FS_ALLOWED_DIRS"):
        ServerSettings(
            enable_filesystem=True,
            fs_allowed_dirs=(),
            enable_github=False,
            enable_browser=False,
        )


def test_filesystem_disabled_allows_empty_roots() -> None:
    settings = ServerSettings(
        enable_filesystem=False,
        fs_allowed_dirs=(),
        enable_github=False,
        enable_browser=False,
    )

    assert settings.enable_filesystem is False
    assert settings.fs_allowed_dirs == ()


def test_fs_allowed_dirs_parses_path_separator_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    monkeypatch.setenv("ENABLE_FILESYSTEM", "true")
    monkeypatch.setenv("FS_ALLOWED_DIRS", os.pathsep.join([str(first), str(second)]))
    monkeypatch.setenv("ENABLE_GITHUB", "false")
    monkeypatch.setenv("ENABLE_BROWSER", "false")

    settings = ServerSettings()

    assert settings.fs_allowed_dirs == (first.resolve(), second.resolve())


def test_read_only_parses_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_FILESYSTEM", "true")
    monkeypatch.setenv("FS_ALLOWED_DIRS", str(tmp_path))
    monkeypatch.setenv("READ_ONLY", "true")
    monkeypatch.setenv("ENABLE_GITHUB", "false")
    monkeypatch.setenv("ENABLE_BROWSER", "false")

    settings = ServerSettings()

    assert settings.read_only is True


def test_github_enabled_requires_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        ServerSettings(
            enable_filesystem=True,
            fs_allowed_dirs=(tmp_path,),
            enable_github=True,
            github_token=None,
            enable_browser=False,
        )


def test_github_disabled_does_not_require_token(tmp_path: Path) -> None:
    settings = ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(tmp_path,),
        enable_github=False,
        github_token=None,
        enable_browser=False,
    )

    assert settings.enable_github is False
    assert settings.github_token is None


def test_secret_value_is_not_in_unrelated_validation_error() -> None:
    fake_secret = "ghp_fake_secret_that_must_not_be_printed"

    with pytest.raises(ValueError) as exc_info:
        ServerSettings(
            enable_filesystem=True,
            fs_allowed_dirs=(),
            enable_github=True,
            github_token=fake_secret,
            enable_browser=False,
        )

    assert fake_secret not in str(exc_info.value)
