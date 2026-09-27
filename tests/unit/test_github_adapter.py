from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from build_an_mcp_server.errors import PublicToolError
from build_an_mcp_server.github_adapter import GitHubAdapter


class FakeGitHubClient:
    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self.calls: list[str] = []

    def get_repo(self, full_name_or_id: str) -> Any:
        self.calls.append(full_name_or_id)
        return self.repository


def _repository() -> SimpleNamespace:
    issue = SimpleNamespace(
        number=7,
        pull_request=None,
        title="Bound the result",
        state="open",
        user=SimpleNamespace(login="reader"),
        labels=[SimpleNamespace(name="book"), SimpleNamespace(name="mcp")],
        body="abcdefgh",
        html_url="https://github.com/example/repository/issues/7",
        repository=SimpleNamespace(full_name="example/repository"),
    )

    def get_issue(number: int) -> SimpleNamespace | None:
        return issue if number == 7 else None

    return SimpleNamespace(
        full_name="example/repository",
        description="Example",
        default_branch="main",
        language="Python",
        visibility="public",
        private=False,
        archived=False,
        open_issues_count=1,
        updated_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
        get_issue=get_issue,
    )


def test_adapter_normalizes_provider_objects_and_bounds_body() -> None:
    client = FakeGitHubClient(_repository())
    adapter = GitHubAdapter(
        "secret-token",
        ("example/repository",),
        max_body_chars=4,
        client=client,
    )

    summary = adapter.repository_summary("Example/Repository")
    issue = adapter.issue_context("example/repository", 7)

    assert summary.repository == "example/repository"
    assert summary.updated_at == "2026-08-17T00:00:00+00:00"
    assert issue.body == "abcd"
    assert issue.body_truncated is True
    assert issue.labels == ["book", "mcp"]


def test_adapter_rejects_unlisted_repository_before_provider_io() -> None:
    client = FakeGitHubClient(_repository())
    adapter = GitHubAdapter(
        "secret-token",
        ("example/repository",),
        max_body_chars=100,
        client=client,
    )

    with pytest.raises(PublicToolError, match="not allowed"):
        adapter.repository_summary("other/repository")

    assert client.calls == []


def test_provider_failure_is_sanitized() -> None:
    class ProviderFailure(RuntimeError):
        status = 503

    class FailingClient:
        def get_repo(self, full_name_or_id: str) -> Any:
            del full_name_or_id
            raise ProviderFailure("secret-token and raw provider payload")

    adapter = GitHubAdapter(
        "secret-token",
        ("example/repository",),
        max_body_chars=100,
        client=FailingClient(),
    )

    with pytest.raises(PublicToolError) as captured:
        adapter.repository_summary("example/repository")

    assert str(captured.value) == "The allowed GitHub repository is currently unavailable."
    assert "secret-token" not in str(captured.value)
