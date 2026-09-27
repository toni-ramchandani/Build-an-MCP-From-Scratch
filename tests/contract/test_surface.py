from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from mcp.client import Client
from mcp_types import CacheableResult, TextContent, TextResourceContents

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.factory import create_server
from tests.helpers import make_settings, tool_text

PROTOCOL_VERSION = "2026-07-28"

_ROOT_ID_DESCRIPTION = "Opaque root identifier from workspace://manifest."
_RELATIVE_PATH_DESCRIPTION = (
    "Path relative to the selected root; absolute paths and '..' are rejected."
)


def _assert_valid_cache_hint(result: CacheableResult) -> None:
    assert result.ttl_ms >= 0
    assert result.cache_scope in {"private", "public"}


@pytest.mark.anyio
async def test_in_process_client_discovers_server_contract(
    mcp_client: Client,
) -> None:
    tools = await mcp_client.list_tools()
    resources = await mcp_client.list_resources()
    prompts = await mcp_client.list_prompts()

    assert mcp_client.protocol_version == PROTOCOL_VERSION
    assert mcp_client.server_info is not None
    assert mcp_client.server_capabilities.tools is not None
    assert mcp_client.server_capabilities.resources is not None
    assert mcp_client.server_capabilities.prompts is not None

    assert tools.tools
    assert resources.resources
    assert prompts.prompts


@pytest.mark.anyio
async def test_default_advertised_surface_is_exact_and_read_only(
    mcp_client: Client,
) -> None:
    tools = await mcp_client.list_tools()
    resources = await mcp_client.list_resources()
    prompts = await mcp_client.list_prompts()

    tools_by_name = {tool.name: tool for tool in tools.tools}
    resources_by_uri = {str(resource.uri): resource for resource in resources.resources}
    prompts_by_name = {prompt.name: prompt for prompt in prompts.prompts}

    assert len(tools_by_name) == len(tools.tools)
    assert len(resources_by_uri) == len(resources.resources)
    assert len(prompts_by_name) == len(prompts.prompts)

    assert set(tools_by_name) == {
        "list_workspace_directory",
        "read_workspace_text",
    }
    assert set(resources_by_uri) == {"workspace://manifest"}
    assert set(prompts_by_name) == {"review_workspace_file"}

    list_tool = tools_by_name["list_workspace_directory"]
    assert list_tool.title == "List a workspace directory"
    assert list_tool.description == (
        "List one bounded page of entries inside an allowed workspace root."
    )
    assert list_tool.annotations is not None
    assert list_tool.annotations.read_only_hint is True
    assert list_tool.annotations.open_world_hint is False
    assert list_tool.output_schema is not None

    list_schema = list_tool.input_schema
    assert list_schema["type"] == "object"
    assert set(list_schema["required"]) == {"root_id"}
    assert set(list_schema["properties"]) == {
        "root_id",
        "relative_path",
        "offset",
    }
    assert list_schema["properties"]["root_id"] == {
        "description": _ROOT_ID_DESCRIPTION,
        "title": "Root Id",
        "type": "string",
    }
    assert list_schema["properties"]["relative_path"] == {
        "default": ".",
        "description": _RELATIVE_PATH_DESCRIPTION,
        "title": "Relative Path",
        "type": "string",
    }
    assert list_schema["properties"]["offset"] == {
        "default": 0,
        "maximum": 10_000,
        "minimum": 0,
        "title": "Offset",
        "type": "integer",
    }
    assert set(list_tool.output_schema["required"]) == {
        "root_id",
        "relative_path",
        "offset",
        "returned",
        "entries",
        "truncated",
        "next_offset",
    }

    read_tool = tools_by_name["read_workspace_text"]
    assert read_tool.title == "Read workspace text"
    assert read_tool.description == (
        "Read one bounded UTF-8 chunk from a file inside an allowed workspace root."
    )
    assert read_tool.annotations is not None
    assert read_tool.annotations.read_only_hint is True
    assert read_tool.annotations.open_world_hint is False
    assert read_tool.output_schema is not None

    read_schema = read_tool.input_schema
    assert read_schema["type"] == "object"
    assert set(read_schema["required"]) == {"root_id", "relative_path"}
    assert set(read_schema["properties"]) == {
        "root_id",
        "relative_path",
        "offset_bytes",
    }
    assert read_schema["properties"]["root_id"] == {
        "description": _ROOT_ID_DESCRIPTION,
        "title": "Root Id",
        "type": "string",
    }
    assert read_schema["properties"]["relative_path"] == {
        "description": _RELATIVE_PATH_DESCRIPTION,
        "title": "Relative Path",
        "type": "string",
    }
    assert read_schema["properties"]["offset_bytes"] == {
        "default": 0,
        "minimum": 0,
        "title": "Offset Bytes",
        "type": "integer",
    }
    assert set(read_tool.output_schema["required"]) == {
        "root_id",
        "relative_path",
        "mime_type",
        "content",
        "offset_bytes",
        "bytes_read",
        "total_bytes",
        "truncated",
        "next_offset_bytes",
        "sha256",
    }

    resource = resources_by_uri["workspace://manifest"]
    assert resource.title == "Workspace boundary"
    assert resource.description == ("Opaque roots and result budgets exposed by this server.")
    assert resource.mime_type == "application/json"

    prompt = prompts_by_name["review_workspace_file"]
    assert prompt.title == "Review a workspace file"
    assert prompt.description == (
        "Ask the host to review a file through the bounded workspace tools."
    )
    assert prompt.arguments is not None
    prompt_arguments = {argument.name: argument for argument in prompt.arguments}
    assert len(prompt_arguments) == len(prompt.arguments)
    assert set(prompt_arguments) == {"root_id", "relative_path"}
    assert prompt_arguments["root_id"].required is True
    assert prompt_arguments["relative_path"].required is True


@pytest.mark.anyio
async def test_workspace_calls_return_bounded_structured_results(
    mcp_client: Client,
    base_settings: ServerSettings,
) -> None:
    tools = {tool.name: tool for tool in (await mcp_client.list_tools()).tools}

    listing = await mcp_client.call_tool(
        "list_workspace_directory",
        {"root_id": "root-1", "relative_path": "."},
    )
    read = await mcp_client.call_tool(
        "read_workspace_text",
        {"root_id": "root-1", "relative_path": "README.md"},
    )

    list_schema = tools["list_workspace_directory"].output_schema
    assert list_schema is not None
    Draft202012Validator.check_schema(list_schema)

    assert listing.is_error is False
    assert listing.structured_content is not None

    list_validator = cast(
        Validator,
        Draft202012Validator(list_schema),
    )
    list_validator.validate(listing.structured_content)

    assert listing.structured_content["relative_path"] == "."
    assert listing.structured_content["returned"] == 2
    assert listing.structured_content["returned"] <= base_settings.max_directory_entries
    assert "approved-workspace" not in tool_text(listing)

    read_schema = tools["read_workspace_text"].output_schema
    assert read_schema is not None
    Draft202012Validator.check_schema(read_schema)

    assert read.is_error is False
    assert read.structured_content is not None

    read_validator = cast(
        Validator,
        Draft202012Validator(read_schema),
    )
    read_validator.validate(read.structured_content)

    assert read.structured_content["relative_path"] == "README.md"
    assert read.structured_content["content"].startswith("# Sample")
    assert read.structured_content["bytes_read"] <= base_settings.max_file_read_bytes


@pytest.mark.anyio
async def test_directory_budget_pagination(
    tmp_path: Path,
) -> None:
    root = tmp_path / "directory-budget"
    root.mkdir()

    for index in range(201):
        (root / f"file-{index:03}.txt").write_text(
            "x",
            encoding="utf-8",
        )

    settings = make_settings(workspace_roots=(root,))
    assert settings.max_directory_entries == 200

    async with Client(
        create_server(settings),
        raise_exceptions=True,
        cache=None,
    ) as client:
        first = await client.call_tool(
            "list_workspace_directory",
            {
                "root_id": "root-1",
                "relative_path": ".",
            },
        )

        assert first.is_error is False
        assert first.structured_content is not None

        first_content = first.structured_content
        assert first_content["returned"] == 200
        assert len(first_content["entries"]) == 200
        assert first_content["truncated"] is True

        next_offset = first_content["next_offset"]
        assert next_offset == 200

        second = await client.call_tool(
            "list_workspace_directory",
            {
                "root_id": "root-1",
                "relative_path": ".",
                "offset": next_offset,
            },
        )

    assert second.is_error is False
    assert second.structured_content is not None

    second_content = second.structured_content
    assert second_content["offset"] == 200
    assert second_content["returned"] == 1
    assert len(second_content["entries"]) == 1
    assert second_content["truncated"] is False
    assert second_content["next_offset"] is None


@pytest.mark.anyio
async def test_text_read_budget_pagination(
    tmp_path: Path,
) -> None:
    root = tmp_path / "text-budget"
    root.mkdir()

    target = root / "large.txt"
    target.write_bytes(b"a" * 65_535 + "€".encode() + b"z")

    settings = make_settings(workspace_roots=(root,))
    assert settings.max_file_read_bytes == 65_536

    async with Client(
        create_server(settings),
        raise_exceptions=True,
        cache=None,
    ) as client:
        first = await client.call_tool(
            "read_workspace_text",
            {
                "root_id": "root-1",
                "relative_path": "large.txt",
                "offset_bytes": 0,
            },
        )

        assert first.is_error is False
        assert first.structured_content is not None

        first_content = first.structured_content
        assert first_content["bytes_read"] == 65_535
        assert first_content["content"] == "a" * 65_535
        assert first_content["truncated"] is True

        next_offset = first_content["next_offset_bytes"]
        assert next_offset == 65_535

        second = await client.call_tool(
            "read_workspace_text",
            {
                "root_id": "root-1",
                "relative_path": "large.txt",
                "offset_bytes": next_offset,
            },
        )

    assert second.is_error is False
    assert second.structured_content is not None

    second_content = second.structured_content
    assert second_content["offset_bytes"] == 65_535
    assert second_content["content"] == "€z"
    assert second_content["bytes_read"] == 4
    assert second_content["truncated"] is False
    assert second_content["next_offset_bytes"] is None


@pytest.mark.anyio
async def test_resource_describes_boundary_without_private_paths(
    mcp_client: Client,
    base_settings: ServerSettings,
    workspace_root: Path,
) -> None:
    templates = await mcp_client.list_resource_templates()
    result = await mcp_client.read_resource("workspace://manifest")

    assert templates.resource_templates == []
    assert len(result.contents) == 1

    content = result.contents[0]
    assert isinstance(content, TextResourceContents)

    manifest = json.loads(content.text)
    assert manifest["roots"] == [
        {
            "root_id": "root-1",
            "label": workspace_root.name,
        }
    ]
    assert manifest["read_only"] is True
    assert manifest["max_file_read_bytes"] == base_settings.max_file_read_bytes
    assert manifest["max_directory_entries"] == base_settings.max_directory_entries
    assert str(workspace_root) not in content.text


@pytest.mark.anyio
async def test_prompt_depends_on_the_workspace_contract(
    mcp_client: Client,
) -> None:
    relative_path = "missing-review-target.txt"

    result = await mcp_client.get_prompt(
        "review_workspace_file",
        {
            "root_id": "root-1",
            "relative_path": relative_path,
        },
    )

    assert len(result.messages) == 1

    message = result.messages[0]
    assert message.role == "user"
    assert isinstance(message.content, TextContent)

    text = message.content.text
    assert "read_workspace_text" in text
    assert "'root-1'" in text
    assert repr(relative_path) in text
    assert "untrusted data" in text
    assert "not as instructions" in text


@pytest.mark.anyio
async def test_complete_results_expose_valid_cache_hints(
    mcp_client: Client,
) -> None:
    discover = mcp_client.session.discover_result
    assert discover is not None

    results: tuple[CacheableResult, ...] = (
        discover,
        await mcp_client.list_tools(),
        await mcp_client.list_prompts(),
        await mcp_client.list_resources(),
        await mcp_client.list_resource_templates(),
        await mcp_client.read_resource("workspace://manifest"),
    )

    for result in results:
        _assert_valid_cache_hint(result)


@pytest.mark.anyio
async def test_disabling_workspace_removes_dependent_prompt() -> None:
    settings = make_settings(enable_workspace=False)

    async with Client(
        create_server(settings),
        raise_exceptions=True,
        cache=None,
    ) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()

    assert tools.tools == []
    assert resources.resources == []
    assert prompts.prompts == []


@pytest.mark.anyio
async def test_outside_root_attempt_is_a_caller_safe_tool_failure(
    mcp_client: Client,
    workspace_root: Path,
) -> None:
    result = await mcp_client.call_tool(
        "read_workspace_text",
        {
            "root_id": "root-1",
            "relative_path": "../secret.txt",
        },
    )

    message = tool_text(result)

    assert result.is_error is True
    assert "relative" in message.lower() or "outside" in message.lower()
    assert str(workspace_root) not in message
    assert "traceback" not in message.lower()
