from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.helpers import server_environment

PROTOCOL_VERSION = "2026-07-28"
SECRET_CANARY = "chapter-six-secret-canary"
TRACEBACK_MARKER = "Traceback (most recent call last)"


def _modern_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "runtime-raw-test",
                    "version": "0.2.0",
                },
            }
        },
    }


def _single_jsonrpc_response(stdout: str) -> dict[str, Any]:
    lines = stdout.splitlines()
    assert len(lines) == 1, (
        f"expected exactly one protocol response on stdout; observed {len(lines)} lines"
    )

    try:
        response: object = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise AssertionError("stdout contained non-JSON protocol data") from exc

    assert isinstance(response, dict)
    return cast(dict[str, Any], response)


def test_server_environment_does_not_inherit_ambient_mcp_settings(
    workspace_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_GITHUB_TOKEN", SECRET_CANARY)
    monkeypatch.setenv("MCP_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_UNRELATED_SECRET", SECRET_CANARY)

    environment = server_environment(workspace_root)

    assert environment["MCP_WORKSPACE_ROOTS"] == str(workspace_root)
    assert environment["MCP_ENABLE_GITHUB"] == "false"
    assert "MCP_GITHUB_TOKEN" not in environment
    assert "MCP_HTTP_HOST" not in environment
    assert "MCP_UNRELATED_SECRET" not in environment


@pytest.mark.runtime
def test_diagnostic_stdio_environment_is_feature_scoped(
    workspace_root: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    probe = (
        "import json; "
        "from scripts.diagnostic_client import _mcp_environment; "
        "print(json.dumps(_mcp_environment(), sort_keys=True))"
    )
    environment = server_environment(workspace_root)
    environment.update(
        {
            "MCP_MAX_DIGEST_BYTES": "131072",
            "MCP_GITHUB_TOKEN": SECRET_CANARY,
            "MCP_GITHUB_REPOSITORIES": "invalid-repository-shape",
            "MCP_HTTP_HOST": "0.0.0.0",
        }
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    forwarded = json.loads(completed.stdout)
    assert forwarded["MCP_WORKSPACE_ROOTS"] == str(workspace_root)
    assert forwarded["MCP_ENABLE_GITHUB"] == "false"
    assert forwarded["MCP_MAX_DIGEST_BYTES"] == "131072"
    assert "MCP_GITHUB_TOKEN" not in forwarded
    assert "MCP_GITHUB_REPOSITORIES" not in forwarded
    assert "MCP_HTTP_HOST" not in forwarded

    enabled_environment = dict(environment)
    enabled_environment["MCP_ENABLE_GITHUB"] = "true"
    enabled_environment["MCP_GITHUB_REPOSITORIES"] = "owner/repository"

    enabled = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo_root,
        env=enabled_environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert enabled.returncode == 0, enabled.stderr
    enabled_forwarded = json.loads(enabled.stdout)
    assert enabled_forwarded["MCP_GITHUB_TOKEN"] == SECRET_CANARY
    assert enabled_forwarded["MCP_GITHUB_REPOSITORIES"] == "owner/repository"


@pytest.mark.runtime
@pytest.mark.anyio
async def test_sdk_client_crosses_real_stdio_process(
    workspace_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_GITHUB_TOKEN", SECRET_CANARY)
    monkeypatch.setenv("MCP_UNRELATED_SECRET", SECRET_CANARY)

    runtime_cwd = tmp_path / "stdio-runtime"
    runtime_cwd.mkdir()
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "build_an_mcp_server.server"],
        env=server_environment(workspace_root),
        cwd=runtime_cwd,
    )
    diagnostics_path = tmp_path / "stdio.stderr"

    with diagnostics_path.open("w", encoding="utf-8") as diagnostics:
        async with Client(
            stdio_client(parameters, errlog=diagnostics),
            mode=PROTOCOL_VERSION,
            cache=None,
        ) as client:
            protocol_version = client.protocol_version
            tools = await client.list_tools()
            resources = await client.list_resources()
            prompts = await client.list_prompts()
            result = await client.call_tool(
                "read_workspace_text",
                {"root_id": "root-1", "relative_path": "README.md"},
            )

    diagnostics_text = diagnostics_path.read_text(encoding="utf-8")

    assert protocol_version == PROTOCOL_VERSION
    assert {tool.name for tool in tools.tools} == {
        "list_workspace_directory",
        "read_workspace_text",
    }
    assert {str(resource.uri) for resource in resources.resources} == {"workspace://manifest"}
    assert {prompt.name for prompt in prompts.prompts} == {"review_workspace_file"}
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["relative_path"] == "README.md"
    assert SECRET_CANARY not in diagnostics_text
    assert str(workspace_root) not in diagnostics_text
    assert TRACEBACK_MARKER not in diagnostics_text


@pytest.mark.runtime
def test_raw_stdio_is_one_json_object_per_line_without_handshake(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    request = _modern_request()
    runtime_cwd = tmp_path / "raw-stdio-runtime"
    runtime_cwd.mkdir()
    completed = subprocess.run(
        [sys.executable, "-m", "build_an_mcp_server.server"],
        cwd=runtime_cwd,
        env=server_environment(workspace_root),
        input=json.dumps(request, separators=(",", ":")) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    response = _single_jsonrpc_response(completed.stdout)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert {tool["name"] for tool in response["result"]["tools"]} == {
        "list_workspace_directory",
        "read_workspace_text",
    }
    assert "initialize" not in completed.stdout


@pytest.mark.runtime
def test_raw_stdio_detector_rejects_startup_stdout_pollution(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    request = _modern_request()
    runtime_cwd = tmp_path / "polluted-stdio-runtime"
    runtime_cwd.mkdir()
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "polluted_stdio_entry.py"

    completed = subprocess.run(
        [sys.executable, str(fixture)],
        cwd=runtime_cwd,
        env=server_environment(workspace_root),
        input=json.dumps(request, separators=(",", ":")) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    with pytest.raises(AssertionError, match="expected exactly one protocol response"):
        _single_jsonrpc_response(completed.stdout)


@pytest.mark.runtime
def test_diagnostic_client_runs_against_stdio(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    caller_cwd = tmp_path / "diagnostic-caller"
    caller_cwd.mkdir()
    (caller_cwd / ".env").write_text("MCP_HTTP_HOST=0.0.0.0\n", encoding="utf-8")

    environment = server_environment(workspace_root)
    environment.update(
        {
            "MCP_GITHUB_TOKEN": SECRET_CANARY,
            "MCP_GITHUB_REPOSITORIES": "invalid-repository-shape",
            "MCP_HTTP_HOST": "0.0.0.0",
        }
    )
    script = repo_root / "scripts" / "diagnostic_client.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--transport",
            "stdio",
            "--read",
            "README.md",
        ],
        cwd=caller_cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

    lines = completed.stdout.splitlines()
    assert len(lines) == 9
    assert lines[:7] == [
        "transport: stdio",
        "protocol: 2026-07-28",
        "tools: list_workspace_directory, read_workspace_text",
        "resources: workspace://manifest",
        "prompts: review_workspace_file",
        "read.is_error: False",
        "read.relative_path: README.md",
    ]
    assert lines[7].startswith("read.bytes_read: ")
    assert int(lines[7].removeprefix("read.bytes_read: ")) >= 0
    assert lines[8] == "read.truncated: False"

    assert SECRET_CANARY not in completed.stdout
    assert SECRET_CANARY not in completed.stderr
    assert str(workspace_root) not in completed.stdout
    assert str(workspace_root) not in completed.stderr
    assert TRACEBACK_MARKER not in completed.stderr


@pytest.mark.parametrize("stdout", ["{}\n\n", "\n{}\n"])
def test_stdout_detector_rejects_blank_frames(stdout: str) -> None:
    with pytest.raises(AssertionError, match="expected exactly one protocol response"):
        _single_jsonrpc_response(stdout)
