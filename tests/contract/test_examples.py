from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.client import Client

from examples.ch02.minimal_add_server import server
from tests.helpers import server_environment

PROTOCOL_VERSION = "2026-07-28"


def test_inspector_example_is_valid_and_uses_the_locked_server_command() -> None:
    path = Path(__file__).resolve().parents[2] / "scripts/inspector-stdio.mcp.json.example"
    config = json.loads(path.read_text(encoding="utf-8"))
    server_config = config["mcpServers"]["build-an-mcp-server"]

    assert server_config["type"] == "stdio"
    assert server_config["command"] == "<ABSOLUTE_PATH_TO_UV>"
    assert server_config["args"] == [
        "run",
        "--frozen",
        "--project",
        "<ABSOLUTE_PATH_TO_REPOSITORY>",
        "--directory",
        "<ABSOLUTE_PATH_TO_CANARY_WORKSPACE>",
        "build-an-mcp-server",
    ]
    assert server_config["env"]["MCP_ENABLE_MUTATION"] == "false"


@pytest.mark.anyio
async def test_chapter_2_minimal_tool_example() -> None:
    async with Client(server, mode=PROTOCOL_VERSION, cache=None) as client:
        tools = await client.list_tools()
        result = await client.call_tool("add", {"a": 20, "b": 22})

    assert [tool.name for tool in tools.tools] == ["add"]
    assert tools.tools[0].annotations is not None
    assert tools.tools[0].annotations.read_only_hint is True
    assert tools.tools[0].annotations.idempotent_hint is True
    assert tools.tools[0].annotations.open_world_hint is False
    assert result.is_error is False
    assert result.structured_content == {"result": 42}


@pytest.mark.runtime
def test_chapter_3_raw_trace_example(workspace_root: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "examples.ch03.raw_stdio_trace",
            "--root",
            str(workspace_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=server_environment(workspace_root),
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"method": "tools/list"' in completed.stdout
    assert '"name": "read_workspace_text"' in completed.stdout
    assert "initialize" not in completed.stdout
