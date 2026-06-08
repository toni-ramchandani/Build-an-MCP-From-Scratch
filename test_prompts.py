from __future__ import annotations

import pytest

from mcp.client.session import ClientSession
from mcp.shared.exceptions import McpError

from tests.mcp_test_utils import prompt_names


@pytest.mark.anyio
async def test_prompts_list_includes_chapter4_prompts(
    client_session: ClientSession,
) -> None:
    listed = await client_session.list_prompts()

    assert prompt_names(listed) >= {"review_file", "inspect_directory"}


@pytest.mark.anyio
async def test_review_file_prompt_returns_messages(
    client_session: ClientSession,
) -> None:
    result = await client_session.get_prompt(
        "review_file",
        arguments={"path": "readme.md"},
    )

    assert result.messages
    assert len(result.messages) == 2
    assert all(message.role == "user" for message in result.messages)


@pytest.mark.anyio
async def test_inspect_directory_prompt_returns_messages(
    client_session: ClientSession,
) -> None:
    result = await client_session.get_prompt(
        "inspect_directory",
        arguments={"path": "."},
    )

    assert result.messages
    assert len(result.messages) == 2
    assert all(message.role == "user" for message in result.messages)


@pytest.mark.anyio
async def test_unknown_prompt_does_not_succeed(
    client_session: ClientSession,
) -> None:
    with pytest.raises(McpError):
        await client_session.get_prompt("definitely_not_registered", arguments={})


@pytest.mark.anyio
async def test_prompt_missing_required_argument_does_not_succeed(
    client_session: ClientSession,
) -> None:
    with pytest.raises(McpError):
        await client_session.get_prompt("review_file", arguments={})
