from __future__ import annotations

from pathlib import Path

import pytest
from mcp.client import Client

from build_an_mcp_server.factory import create_server
from build_an_mcp_server.github_capabilities import GitHubReader
from build_an_mcp_server.models import (
    GitHubIssueContext,
    GitHubRepositorySummary,
)
from tests.helpers import make_settings

WORKSPACE_TOOLS: frozenset[str] = frozenset(
    {
        "list_workspace_directory",
        "read_workspace_text",
    }
)

GITHUB_TOOLS: frozenset[str] = frozenset(
    {
        "get_github_repository_summary",
        "get_github_issue_context",
    }
)

WORKSPACE_RESOURCES: frozenset[str] = frozenset(
    {
        "workspace://manifest",
    }
)

WORKSPACE_PROMPTS: frozenset[str] = frozenset(
    {
        "review_workspace_file",
    }
)

EMPTY_SURFACE: frozenset[str] = frozenset()


class NoIoGitHubReader:
    """Fail if discovery accidentally performs provider I/O."""

    def repository_summary(
        self,
        repository: str,
    ) -> GitHubRepositorySummary:
        del repository
        raise AssertionError("GitHub provider I/O must not occur during discovery")

    def issue_context(
        self,
        repository: str,
        number: int,
    ) -> GitHubIssueContext:
        del repository, number
        raise AssertionError("GitHub provider I/O must not occur during discovery")


@pytest.mark.anyio
@pytest.mark.parametrize(  # A
    (
        "enable_workspace",
        "enable_github",
        "expected_tools",
        "expected_resources",
        "expected_prompts",
    ),
    [
        pytest.param(
            True,
            False,
            WORKSPACE_TOOLS,
            WORKSPACE_RESOURCES,
            WORKSPACE_PROMPTS,
            id="workspace-only",
        ),
        pytest.param(
            False,
            False,
            EMPTY_SURFACE,
            EMPTY_SURFACE,
            EMPTY_SURFACE,
            id="no-optional-surfaces",
        ),
        pytest.param(
            True,
            True,
            WORKSPACE_TOOLS | GITHUB_TOOLS,
            WORKSPACE_RESOURCES,
            WORKSPACE_PROMPTS,
            id="workspace-plus-github",
        ),
        pytest.param(
            False,
            True,
            GITHUB_TOOLS,
            EMPTY_SURFACE,
            EMPTY_SURFACE,
            id="github-only",
        ),
    ],
)
async def test_policy_shapes_discovery(
    workspace_root: Path,
    enable_workspace: bool,
    enable_github: bool,
    expected_tools: frozenset[str],
    expected_resources: frozenset[str],
    expected_prompts: frozenset[str],
) -> None:
    settings = make_settings(  # B
        enable_workspace=enable_workspace,
        workspace_roots=((workspace_root,) if enable_workspace else ()),
        enable_github=enable_github,
        github_token=("secret-token" if enable_github else None),
        github_repositories=(("example/repository",) if enable_github else ()),
    )

    github_reader: GitHubReader | None = (  # C
        NoIoGitHubReader() if enable_github else None
    )

    async with Client(
        create_server(
            settings,
            github_reader=github_reader,
        ),
        raise_exceptions=True,
        cache=None,
    ) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()

    assert {  # D
        tool.name for tool in tools.tools
    } == expected_tools

    assert {str(resource.uri) for resource in resources.resources} == expected_resources

    assert {prompt.name for prompt in prompts.prompts} == expected_prompts
