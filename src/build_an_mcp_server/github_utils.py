from __future__ import annotations

from typing import Any

from github import Github, GithubException
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from .config import ServerSettings


def get_github_client(token: str | None = None) -> Github:
    """Return an authenticated GitHub client."""

    if not token:
        raise ValueError("GITHUB_TOKEN is required when GitHub is enabled.")
    return Github(token)


def register_github_capabilities(
    mcp: FastMCP,
    settings: ServerSettings,
) -> None:
    """Register a small GitHub capability group for the Chapter 4 runtime."""

    @mcp.tool()
    def get_repository_info(owner: str, repo: str) -> CallToolResult:
        try:
            github = get_github_client(settings.github_token)
            repository = github.get_repo(f"{owner}/{repo}")
            data: dict[str, Any] = {
                "name": repository.name,
                "full_name": repository.full_name,
                "description": repository.description,
                "html_url": repository.html_url,
                "language": repository.language,
                "stargazers_count": repository.stargazers_count,
                "open_issues_count": repository.open_issues_count,
                "default_branch": repository.default_branch,
                "updated_at": repository.updated_at.isoformat(),
            }
        except GithubException as exc:
            message = exc.data.get("message", str(exc)) if hasattr(exc, "data") else str(exc)
            return _tool_error(f"GitHub request failed: {message}")
        except Exception as exc:
            return _tool_error(str(exc))

        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"{data['full_name']}: {data.get('description') or 'No description'}",
                )
            ],
            structuredContent=data,
        )


def _tool_error(message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        isError=True,
    )
