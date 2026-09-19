from __future__ import annotations

import logging
from collections.abc import Callable, Collection
from typing import Any, Protocol, cast

from .errors import PublicToolError
from .models import GitHubIssueContext, GitHubRepositorySummary

logger = logging.getLogger(__name__)


class _GitHubClient(Protocol):
    def get_repo(self, full_name_or_id: str) -> Any: ...


class _GitHubAuth(Protocol):
    @staticmethod
    def Token(token: str) -> object: ...


class _OwnedGitHubClient(_GitHubClient, Protocol):
    def close(self) -> None: ...


class _GitHubFactory(Protocol):
    def __call__(self, *, auth: object, timeout: int) -> _OwnedGitHubClient: ...


class GitHubAdapter:
    """Small read-only provider adapter with an explicit repository allowlist."""

    def __init__(
        self,
        token: str,
        repositories: Collection[str],
        *,
        max_body_chars: int,
        timeout_seconds: int = 10,
        client: _GitHubClient | None = None,
    ) -> None:
        self._close_owned_client: Callable[[], None] | None = None
        if client is None:
            try:
                from importlib import import_module

                module = import_module("github")
                auth = cast(_GitHubAuth, module.__dict__["Auth"])
                github = cast(_GitHubFactory, module.__dict__["Github"])
            except ImportError as exc:  # pragma: no cover - optional dependency gate
                raise RuntimeError(
                    "GitHub is enabled, but the optional 'github' dependency is not installed."
                ) from exc
            owned_client = github(auth=auth.Token(token), timeout=timeout_seconds)
            client = owned_client
            self._close_owned_client = owned_client.close

        self._client = client
        self._repositories = frozenset(repository.lower() for repository in repositories)
        self._max_body_chars = max_body_chars

    def close(self) -> None:
        """Release only a provider client constructed by this adapter."""
        if self._close_owned_client is not None:
            self._close_owned_client()

    def repository_summary(self, repository: str) -> GitHubRepositorySummary:
        selected = self._allowed_repository(repository)
        try:
            item = self._client.get_repo(selected)
            visibility = getattr(item, "visibility", None) or (
                "private" if item.private else "public"
            )
            return GitHubRepositorySummary(
                repository=item.full_name,
                description=item.description,
                default_branch=item.default_branch,
                primary_language=item.language,
                visibility=visibility,
                archived=item.archived,
                open_issues_count=item.open_issues_count,
                updated_at=item.updated_at.isoformat(),
            )
        except Exception as exc:
            self._record_failure("repository_summary", exc)
            raise PublicToolError(
                "The allowed GitHub repository is currently unavailable."
            ) from exc

    def issue_context(self, repository: str, number: int) -> GitHubIssueContext:
        selected = self._allowed_repository(repository)
        try:
            issue = self._client.get_repo(selected).get_issue(number=number)
            raw_body = issue.body or ""
            body = raw_body[: self._max_body_chars]
            return GitHubIssueContext(
                repository=issue.repository.full_name,
                number=issue.number,
                kind="pull_request" if issue.pull_request is not None else "issue",
                title=issue.title,
                state=issue.state,
                author=issue.user.login if issue.user is not None else None,
                labels=sorted(label.name for label in issue.labels),
                body=body,
                body_truncated=len(body) < len(raw_body),
                html_url=issue.html_url,
            )
        except Exception as exc:
            self._record_failure("issue_context", exc)
            raise PublicToolError("The requested GitHub item is currently unavailable.") from exc

    def _allowed_repository(self, repository: str) -> str:
        selected = repository.lower()
        if selected not in self._repositories:
            raise PublicToolError("The requested GitHub repository is not allowed.")
        return selected

    @staticmethod
    def _record_failure(operation: str, error: Exception) -> None:
        raw_status = getattr(error, "status", None)
        status = raw_status if type(raw_status) is int and 100 <= raw_status <= 599 else None
        logger.warning(
            "GitHub adapter failure operation=%s type=%s status=%s",
            operation,
            type(error).__name__,
            status,
        )
