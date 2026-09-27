from __future__ import annotations

from typing import Annotated, Protocol

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .models import GitHubIssueContext, GitHubRepositorySummary


class GitHubReader(Protocol):
    def repository_summary(self, repository: str) -> GitHubRepositorySummary: ...

    def issue_context(self, repository: str, number: int) -> GitHubIssueContext: ...


def register_github_capabilities(mcp: MCPServer, reader: GitHubReader) -> None:
    """Register the small optional read-only GitHub surface owned by Chapter 4."""

    @mcp.tool(
        title="Get repository summary",
        description="Return stable metadata for one configured GitHub repository.",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    def get_github_repository_summary(repository: str) -> GitHubRepositorySummary:
        return reader.repository_summary(repository)

    @mcp.tool(
        title="Get issue or pull-request context",
        description=(
            "Return bounded context for one issue or pull request in an allowed repository."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    def get_github_issue_context(
        repository: str,
        number: Annotated[int, Field(ge=1)],
    ) -> GitHubIssueContext:
        return reader.issue_context(repository, number)
