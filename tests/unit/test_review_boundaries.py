from __future__ import annotations

from pathlib import Path

import pytest

from examples.ch03.raw_stdio_trace import _server_environment  # pyright: ignore[reportPrivateUsage]
from scripts.diagnostic_client import _mcp_environment  # pyright: ignore[reportPrivateUsage]


def test_raw_trace_excludes_ambient_configuration(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_GITHUB_TOKEN", "ambient-secret")
    environment = _server_environment(workspace_root)
    assert "MCP_HTTP_HOST" not in environment
    assert "MCP_GITHUB_TOKEN" not in environment
    assert environment["MCP_WORKSPACE_ROOTS"] == str(workspace_root)


def test_diagnostic_preserves_read_digest_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLE_MUTATION", "false")
    monkeypatch.setenv("MCP_MAX_WRITE_BYTES", "1024")
    assert _mcp_environment()["MCP_MAX_WRITE_BYTES"] == "1024"
