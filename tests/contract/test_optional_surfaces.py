from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from mcp.client import Client

from build_an_mcp_server.browser_runtime import BrowserRuntime
from build_an_mcp_server.factory import create_server
from build_an_mcp_server.github_adapter import GitHubAdapter
from build_an_mcp_server.models import (
    BrowserCloseReceipt,
    BrowserPageSummary,
    GitHubIssueContext,
    GitHubRepositorySummary,
)
from tests.helpers import make_settings, tool_text

PROTOCOL_VERSION = "2026-07-28"

TOKEN_CANARY = "secret-token-canary"
PRIVATE_PATH_CANARY = "C:/private-workspace-canary/customer-secret.txt"
TRACEBACK_CANARY = "sensitive_traceback_function_canary"
PROVIDER_PAYLOAD_CANARY = 'provider-response-canary:{"private":"value"}'


class FakeGitHubReader:
    def repository_summary(
        self,
        repository: str,
    ) -> GitHubRepositorySummary:
        return GitHubRepositorySummary(
            repository=repository,
            description="Repository context",
            default_branch="main",
            primary_language="Python",
            visibility="public",
            archived=False,
            open_issues_count=2,
            updated_at="2026-08-17T00:00:00+00:00",
        )

    def issue_context(
        self,
        repository: str,
        number: int,
    ) -> GitHubIssueContext:
        return GitHubIssueContext(
            repository=repository,
            number=number,
            kind="issue",
            title="Example",
            state="open",
            author="reader",
            labels=["book"],
            body="Bounded body",
            body_truncated=False,
            html_url=f"https://github.com/{repository}/issues/{number}",
        )


class RecordingGitHubClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_repo(self, full_name_or_id: str) -> Any:
        self.calls.append(full_name_or_id)
        raise AssertionError("provider I/O must not occur")


class CanaryProviderError(RuntimeError):
    status = 503


class FailingGitHubClient:
    def get_repo(self, full_name_or_id: str) -> Any:
        del full_name_or_id
        raise CanaryProviderError(
            " ".join(
                (
                    TOKEN_CANARY,
                    PRIVATE_PATH_CANARY,
                    TRACEBACK_CANARY,
                    PROVIDER_PAYLOAD_CANARY,
                )
            )
        )


class FakeBrowserRuntime:
    def __init__(self) -> None:
        self.closed = False

    async def open_page(
        self,
        url: str,
        *,
        owner: str,
    ) -> BrowserPageSummary:
        assert owner == "local-process"
        return BrowserPageSummary(
            handle="opaque-handle-1",
            url=url,
            url_truncated=False,
            title="Example",
            title_truncated=False,
            text="Bounded page",
            text_truncated=False,
            expires_in_seconds=300,
        )

    async def read_page(
        self,
        handle: str,
        *,
        owner: str,
    ) -> BrowserPageSummary:
        assert handle == "opaque-handle-1"
        return await self.open_page(
            "https://example.com",
            owner=owner,
        )

    async def close_page(
        self,
        handle: str,
        *,
        owner: str,
    ) -> BrowserCloseReceipt:
        assert owner == "local-process"
        return BrowserCloseReceipt(
            handle=handle,
            closed=True,
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_mutation_is_discoverable_only_when_explicitly_enabled(
    workspace_root: Path,
) -> None:
    settings = make_settings(
        workspace_roots=(workspace_root,),
        enable_mutation=True,
        max_write_bytes=1_024,
    )

    async with Client(
        create_server(settings),
        mode=PROTOCOL_VERSION,
        cache=None,
    ) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        manifest = await client.read_resource("workspace://manifest")
        result = await client.call_tool(
            "write_workspace_text",
            {
                "root_id": "root-1",
                "relative_path": "notes.txt",
                "content": "reviewed\n",
                "expected_sha256": "absent",
            },
        )

    assert "write_workspace_text" in names
    assert (
        '"read_only": false' in manifest.contents[0].text  # type: ignore[union-attr]
    )
    assert result.is_error is False
    assert (workspace_root / "notes.txt").read_text(encoding="utf-8") == "reviewed\n"


@pytest.mark.anyio
async def test_github_surface_is_small_read_only_and_provider_independent(
    workspace_root: Path,
) -> None:
    settings = make_settings(
        workspace_roots=(workspace_root,),
        enable_github=True,
        github_token="secret-token",
        github_repositories=("example/repository",),
    )

    async with Client(
        create_server(
            settings,
            github_reader=FakeGitHubReader(),
        ),
        raise_exceptions=True,
        cache=None,
    ) as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "get_github_repository_summary",
            {"repository": "example/repository"},
        )

    tools_by_name = {tool.name: tool for tool in tools.tools}

    assert len(tools_by_name) == len(tools.tools)
    assert set(tools_by_name) == {
        "list_workspace_directory",
        "read_workspace_text",
        "get_github_repository_summary",
        "get_github_issue_context",
    }

    summary_tool = tools_by_name["get_github_repository_summary"]
    assert summary_tool.title == "Get repository summary"
    assert summary_tool.description == (
        "Return stable metadata for one configured GitHub repository."
    )
    assert summary_tool.annotations is not None
    assert summary_tool.annotations.read_only_hint is True
    assert summary_tool.annotations.open_world_hint is True
    assert summary_tool.output_schema is not None

    assert set(summary_tool.input_schema["required"]) == {"repository"}
    assert set(summary_tool.input_schema["properties"]) == {"repository"}
    assert summary_tool.input_schema["properties"]["repository"]["type"] == "string"
    assert set(summary_tool.output_schema["required"]) == {
        "repository",
        "description",
        "default_branch",
        "primary_language",
        "visibility",
        "archived",
        "open_issues_count",
        "updated_at",
    }

    issue_tool = tools_by_name["get_github_issue_context"]
    assert issue_tool.title == "Get issue or pull-request context"
    assert issue_tool.description == (
        "Return bounded context for one issue or pull request in an allowed repository."
    )
    assert issue_tool.annotations is not None
    assert issue_tool.annotations.read_only_hint is True
    assert issue_tool.annotations.open_world_hint is True
    assert issue_tool.output_schema is not None

    assert set(issue_tool.input_schema["required"]) == {"repository", "number"}
    assert set(issue_tool.input_schema["properties"]) == {"repository", "number"}
    assert issue_tool.input_schema["properties"]["repository"]["type"] == "string"
    assert issue_tool.input_schema["properties"]["number"]["type"] == "integer"
    assert issue_tool.input_schema["properties"]["number"]["minimum"] == 1
    assert set(issue_tool.output_schema["required"]) == {
        "repository",
        "number",
        "kind",
        "title",
        "state",
        "author",
        "labels",
        "body",
        "body_truncated",
        "html_url",
    }

    assert result.structured_content is not None
    assert result.structured_content["repository"] == "example/repository"
    assert "secret-token" not in tool_text(result)


@pytest.mark.anyio
async def test_unlisted_github_repository_is_a_caller_safe_tool_failure() -> None:
    provider = RecordingGitHubClient()

    adapter = GitHubAdapter(
        "secret-token",
        ("example/repository",),
        max_body_chars=100,
        client=provider,
    )

    settings = make_settings(
        enable_workspace=False,
        enable_github=True,
        github_token="secret-token",
        github_repositories=("example/repository",),
    )

    async with Client(
        create_server(
            settings,
            github_reader=adapter,
        ),
        mode=PROTOCOL_VERSION,
        cache=None,
    ) as client:
        result = await client.call_tool(
            "get_github_repository_summary",
            {"repository": "other/repository"},
        )

    assert result.is_error is True
    assert tool_text(result) == (
        "Error executing tool "
        "get_github_repository_summary: "
        "The requested GitHub repository is not allowed."
    )
    assert provider.calls == []


@pytest.mark.anyio
async def test_github_provider_failure_is_redacted_at_mcp_boundary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        "WARNING",
        logger="build_an_mcp_server.github_adapter",
    )

    adapter = GitHubAdapter(  # A
        TOKEN_CANARY,
        ("example/repository",),
        max_body_chars=100,
        client=FailingGitHubClient(),
    )

    settings = make_settings(
        enable_workspace=False,
        enable_github=True,
        github_token=TOKEN_CANARY,
        github_repositories=("example/repository",),
    )

    async with Client(
        create_server(
            settings,
            github_reader=adapter,
        ),
        mode=PROTOCOL_VERSION,
        cache=None,
    ) as client:
        result = await client.call_tool(  # B
            "get_github_repository_summary",
            {"repository": "example/repository"},
        )

    public_text = tool_text(result)
    evidence = "\n".join(  # C
        (
            public_text,
            result.model_dump_json(),
            caplog.text,
        )
    )

    assert result.is_error is True
    assert result.structured_content is None
    assert public_text == (
        "Error executing tool "
        "get_github_repository_summary: "
        "The allowed GitHub repository is currently "
        "unavailable."
    )

    for canary in (  # D
        TOKEN_CANARY,
        PRIVATE_PATH_CANARY,
        TRACEBACK_CANARY,
        PROVIDER_PAYLOAD_CANARY,
    ):
        assert canary not in evidence

    assert "operation=repository_summary" in caplog.text
    assert "type=CanaryProviderError" in caplog.text
    assert "status=503" in caplog.text


@pytest.mark.anyio
async def test_browser_surface_uses_lifespan_owned_runtime(
    workspace_root: Path,
) -> None:
    fake = FakeBrowserRuntime()

    settings = make_settings(
        workspace_roots=(workspace_root,),
        enable_browser=True,
        browser_allowed_origins=("https://example.com",),
    )

    server = create_server(
        settings,
        browser_factory=lambda _: cast(
            BrowserRuntime,
            fake,
        ),
    )

    async with Client(
        server,
        mode=PROTOCOL_VERSION,
        cache=None,
    ) as client:
        tools = await client.list_tools()

        names = {tool.name for tool in tools.tools}

        opened = await client.call_tool(
            "open_browser_page",
            {"url": "https://example.com"},
        )

        closed = await client.call_tool(
            "close_browser_page",
            {"handle": "opaque-handle-1"},
        )

    assert {
        "open_browser_page",
        "read_browser_page",
        "close_browser_page",
    }.issubset(names)

    assert opened.structured_content is not None
    assert opened.structured_content["handle"] == "opaque-handle-1"
    assert opened.structured_content["expires_in_seconds"] == 300

    assert closed.structured_content is not None
    assert closed.structured_content["closed"] is True

    close_tool = next(tool for tool in tools.tools if tool.name == "close_browser_page")

    assert close_tool.annotations is not None
    assert close_tool.annotations.destructive_hint is True
    assert close_tool.annotations.idempotent_hint is True
    assert fake.closed is True
