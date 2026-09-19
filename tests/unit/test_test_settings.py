from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.helpers import make_settings


def test_test_settings_ignore_process_and_dotenv_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "MCP_ENABLE_BROWSER=true\nMCP_MAX_DIRECTORY_ENTRIES=19\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MCP_MAX_DIRECTORY_ENTRIES", "17")
    monkeypatch.setenv("MCP_GITHUB_TOKEN", "ambient-secret-canary")
    monkeypatch.setenv("MCP_HTTP_HOST", "0.0.0.0")
    before = make_settings(enable_workspace=False)
    explicit = make_settings(enable_workspace=False, max_directory_entries=31)

    assert before.max_directory_entries == 200
    assert before.github_token is None
    assert before.enable_browser is False
    assert before.http_host == "127.0.0.1"
    assert explicit.max_directory_entries == 31


def test_test_settings_still_validate_explicit_policy() -> None:
    with pytest.raises(ValidationError, match="loopback only"):
        make_settings(enable_workspace=False, http_host="0.0.0.0")
