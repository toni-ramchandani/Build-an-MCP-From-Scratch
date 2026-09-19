from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import server_environment


@pytest.mark.runtime
@pytest.mark.parametrize("missing_name", [True, False], ids=["missing-name", "negative-offset"])
def test_tool_request_and_argument_failure_boundaries(
    workspace_root: Path, tmp_path: Path, missing_name: bool
) -> None:
    params: dict[str, object] = {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        },
        "arguments": {
            "root_id": "root-1",
            "relative_path": "README.md",
            "offset_bytes": 0 if missing_name else -1,
        },
    }
    if not missing_name:
        params["name"] = "read_workspace_text"
    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": params}
    completed = subprocess.run(
        [sys.executable, "-m", "build_an_mcp_server.server"],
        cwd=tmp_path,
        env=server_environment(workspace_root),
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    response = json.loads(completed.stdout)
    assert response["id"] == 7
    if missing_name:
        assert "result" not in response
        assert response["error"]["code"] == -32602
    else:
        assert "error" not in response
        assert response["result"]["isError"] is True
        assert "offset_bytes" in json.dumps(response["result"]["content"])


@pytest.mark.runtime
def test_unknown_tool_is_a_top_level_protocol_error(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    request: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            },
            "name": "does_not_exist",
            "arguments": {},
        },
    }
    completed = subprocess.run(
        [sys.executable, "-m", "build_an_mcp_server.server"],
        cwd=tmp_path,
        env=server_environment(workspace_root),
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    response = json.loads(completed.stdout)
    assert response == {
        "jsonrpc": "2.0",
        "id": 8,
        "error": {
            "code": -32602,
            "message": "Unknown tool: does_not_exist",
            "data": {"name": "does_not_exist"},
        },
    }
