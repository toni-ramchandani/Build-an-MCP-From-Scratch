import os

import pytest

# This unit test exercises the private formatting boundary directly.
from scripts.diagnostic_client import (
    _sanitized_error_message,  # pyright: ignore[reportPrivateUsage]
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        monkeypatch.delenv(key)


def test_each_configured_workspace_root_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    roots = ("/private/canary-one", "/private/canary-two")
    monkeypatch.setenv("MCP_WORKSPACE_ROOTS", os.pathsep.join(roots))
    for root in roots:
        message = _sanitized_error_message(RuntimeError(f"failed at {root}/file.txt"))
        assert message == "failed at <redacted>/file.txt"


def test_secret_is_replaced_before_whitespace_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "demo  secret\n tail"
    monkeypatch.setenv("MCP_TEST_TOKEN", secret)
    message = _sanitized_error_message(RuntimeError(f"token {secret} failed"))
    assert message == "token <redacted> failed"


def test_longest_sensitive_value_is_replaced_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TEST_TOKEN", "demo-value")
    monkeypatch.setenv("MCP_TEST_SECRET", "demo-value-long")
    message = _sanitized_error_message(RuntimeError("demo-value-long demo-value"))
    assert message == "<redacted> <redacted>"


def test_diagnostic_error_is_single_line_and_bounded() -> None:
    assert _sanitized_error_message(RuntimeError("\n \t")) == "runtime connection failed"
    assert _sanitized_error_message(RuntimeError("a\n  b")) == "a b"
    assert len(_sanitized_error_message(RuntimeError("x" * 300))) == 240
