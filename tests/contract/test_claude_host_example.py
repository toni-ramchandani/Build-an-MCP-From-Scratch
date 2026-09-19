from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "scripts" / "claude-desktop.mcp.json.example"


def test_claude_desktop_example_is_current_and_secret_safe() -> None:
    expected = {
        "mcpServers": {
            "build-an-mcp-server": {
                "command": "<ABSOLUTE_PATH_TO_UV>",
                "args": [
                    "run",
                    "--frozen",
                    "--project",
                    "<ABSOLUTE_PATH_TO_REPOSITORY>",
                    "--directory",
                    "<ABSOLUTE_PATH_TO_CANARY_WORKSPACE>",
                    "build-an-mcp-server",
                ],
                "env": {
                    "MCP_ENABLE_WORKSPACE": "true",
                    "MCP_WORKSPACE_ROOTS": "<ABSOLUTE_PATH_TO_CANARY_WORKSPACE>",
                    "MCP_ENABLE_MUTATION": "false",
                    "MCP_ENABLE_GITHUB": "false",
                    "MCP_ENABLE_BROWSER": "false",
                },
            }
        }
    }

    text = EXAMPLE.read_text(encoding="utf-8")
    assert json.loads(text) == expected

    forbidden = (
        "ENABLE_FILESYSTEM",
        "FS_ALLOWED_DIRS",
        "READ_ONLY",
        "read_file",
        "list_files",
        "MCP_GITHUB_TOKEN",
        "MCP_BROWSER_ALLOWED_ORIGINS",
    )
    for token in forbidden:
        assert token not in text
