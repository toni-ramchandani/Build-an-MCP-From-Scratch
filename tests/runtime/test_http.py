from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from tests.helpers import server_environment

PROTOCOL_VERSION = "2026-07-28"
UNSUPPORTED_PROTOCOL_VERSION = "2099-01-01"

HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION_ERROR = -32022
PARSE_ERROR = -32700

SECRET_CANARY = "chapter-six-secret-canary"
TRACEBACK_MARKER = "Traceback (most recent call last)"


@dataclass
class HttpRuntime:
    url: str
    process: subprocess.Popen[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    kill_escalated: bool = False


@dataclass(frozen=True)
class HeaderMismatchCase:
    label: str
    body: dict[str, Any]
    headers: dict[str, str]
    request_id: int
    message: str


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_server(
    process: subprocess.Popen[str],
    port: int,
) -> None:
    deadline = time.monotonic() + 10

    while time.monotonic() < deadline:
        returncode = process.poll()
        if returncode is not None:
            raise AssertionError(f"HTTP server exited before becoming ready with code {returncode}")

        try:
            with socket.create_connection(
                ("127.0.0.1", port),
                timeout=0.2,
            ):
                return
        except OSError:
            time.sleep(0.05)

    raise AssertionError("HTTP server did not listen within 10 seconds")


def _stop_server(
    process: subprocess.Popen[str],
) -> tuple[str, str, bool]:
    kill_escalated = False

    if process.poll() is None:
        process.terminate()

    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        kill_escalated = True
        process.kill()
        stdout, stderr = process.communicate(timeout=5)

    return stdout, stderr, kill_escalated


def _capture_stop(runtime: HttpRuntime) -> None:
    stdout, stderr, kill_escalated = _stop_server(runtime.process)

    runtime.stdout = stdout
    runtime.stderr = stderr
    runtime.returncode = runtime.process.returncode
    runtime.kill_escalated = kill_escalated


@contextmanager
def _http_server(
    workspace_root: Path,
    tmp_path: Path,
) -> Generator[HttpRuntime, None, None]:
    port = _free_port()

    runtime_cwd = tmp_path / "http-runtime"
    runtime_cwd.mkdir()

    process = subprocess.Popen(
        [sys.executable, "-m", "build_an_mcp_server.http_server"],
        cwd=runtime_cwd,
        env=server_environment(workspace_root, port=port),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    runtime = HttpRuntime(
        url=f"http://127.0.0.1:{port}/mcp",
        process=process,
    )

    try:
        try:
            _wait_for_server(process, port)
        except Exception as exc:
            _capture_stop(runtime)
            raise AssertionError(
                f"{exc}\n"
                f"stdout={runtime.stdout}\n"
                f"stderr={runtime.stderr}\n"
                f"kill_escalated={runtime.kill_escalated}"
            ) from exc

        yield runtime
    finally:
        if runtime.returncode is None:
            _capture_stop(runtime)


def _request(
    method: str,
    *,
    request_id: int = 9,
    protocol_version: str = PROTOCOL_VERSION,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": protocol_version,
        "io.modelcontextprotocol/clientCapabilities": {},
    }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": request_params,
    }


def _headers(
    method: str,
    *,
    protocol_version: str = PROTOCOL_VERSION,
    name: str | None = None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": protocol_version,
        "Mcp-Method": method,
    }

    if name is not None:
        headers["Mcp-Name"] = name

    return headers


async def _post_json(
    http_client: httpx2.AsyncClient,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
) -> httpx2.Response:
    return await http_client.post(
        url,
        headers=headers,
        content=json.dumps(body, separators=(",", ":")),
    )


def _json_object(response: httpx2.Response) -> dict[str, Any]:
    payload: object = response.json()

    assert isinstance(payload, dict)

    return cast(dict[str, Any], payload)


def _assert_jsonrpc_result(
    response: httpx2.Response,
    *,
    request_id: int,
) -> dict[str, Any]:
    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == ("application/json")

    payload = _json_object(response)

    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == request_id
    assert "result" in payload
    assert "error" not in payload

    return payload


def _assert_jsonrpc_error(
    response: httpx2.Response,
    *,
    status_code: int,
    request_id: int | None,
    error_code: int,
) -> dict[str, Any]:
    assert response.status_code == status_code
    assert response.headers["content-type"].split(";", 1)[0] == ("application/json")

    payload = _json_object(response)

    assert payload["jsonrpc"] == "2.0"
    assert payload.get("id") == request_id

    error_value = payload.get("error")
    assert isinstance(error_value, dict)

    error = cast(dict[str, Any], error_value)

    assert error["code"] == error_code
    assert isinstance(error.get("message"), str)

    return error


def _assert_runtime_clean(
    runtime: HttpRuntime,
    workspace_root: Path,
) -> None:
    assert runtime.returncode is not None
    assert runtime.kill_escalated is False
    assert str(workspace_root) not in runtime.stdout
    assert str(workspace_root) not in runtime.stderr
    assert "traceback" not in runtime.stderr.lower()


def _header_mismatch_cases() -> tuple[HeaderMismatchCase, ...]:
    version_body = _request(
        "tools/list",
        request_id=101,
        protocol_version="2025-11-25",
    )
    version_headers = _headers("tools/list")

    blank_version_body = _request(
        "tools/list",
        request_id=102,
    )
    blank_version_headers = _headers("tools/list")
    blank_version_headers["MCP-Protocol-Version"] = ""

    missing_method_body = _request(
        "tools/list",
        request_id=103,
    )
    missing_method_headers = _headers("tools/list")
    del missing_method_headers["Mcp-Method"]

    mismatched_method_body = _request(
        "tools/list",
        request_id=104,
    )
    mismatched_method_headers = _headers("tools/list")
    mismatched_method_headers["Mcp-Method"] = "resources/list"

    call_params = {
        "name": "read_workspace_text",
        "arguments": {
            "root_id": "root-1",
            "relative_path": "README.md",
        },
    }

    missing_name_body = _request(
        "tools/call",
        request_id=105,
        params=call_params,
    )
    missing_name_headers = _headers(
        "tools/call",
        name="read_workspace_text",
    )
    del missing_name_headers["Mcp-Name"]

    mismatched_name_body = _request(
        "tools/call",
        request_id=106,
        params=call_params,
    )
    mismatched_name_headers = _headers(
        "tools/call",
        name="list_workspace_directory",
    )

    return (
        HeaderMismatchCase(
            label="version-header-body-mismatch",
            body=version_body,
            headers=version_headers,
            request_id=101,
            message=(
                "mcp-protocol-version header does not match the request envelope's protocol version"
            ),
        ),
        HeaderMismatchCase(
            label="blank-protocol-version-header",
            body=blank_version_body,
            headers=blank_version_headers,
            request_id=102,
            message=(
                "mcp-protocol-version header does not match the request envelope's protocol version"
            ),
        ),
        HeaderMismatchCase(
            label="missing-method-header",
            body=missing_method_body,
            headers=missing_method_headers,
            request_id=103,
            message=("mcp-method header does not match the request body's method"),
        ),
        HeaderMismatchCase(
            label="mismatched-method-header",
            body=mismatched_method_body,
            headers=mismatched_method_headers,
            request_id=104,
            message=("mcp-method header does not match the request body's method"),
        ),
        HeaderMismatchCase(
            label="missing-name-header",
            body=missing_name_body,
            headers=missing_name_headers,
            request_id=105,
            message=("mcp-name header does not match the request body's 'name' parameter"),
        ),
        HeaderMismatchCase(
            label="mismatched-name-header",
            body=mismatched_name_body,
            headers=mismatched_name_headers,
            request_id=106,
            message=("mcp-name header does not match the request body's 'name' parameter"),
        ),
    )


HEADER_MISMATCH_CASES = _header_mismatch_cases()


@pytest.mark.runtime
@pytest.mark.anyio
async def test_native_streamable_http_process(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    with _http_server(workspace_root, tmp_path) as runtime:
        async with httpx2.AsyncClient(trust_env=False) as http_client:
            transport = streamable_http_client(
                runtime.url,
                http_client=http_client,
            )

            async with Client(
                transport,
                mode=PROTOCOL_VERSION,
                cache=None,
            ) as client:
                protocol_version = client.protocol_version
                tools = await client.list_tools()
                resources = await client.list_resources()
                prompts = await client.list_prompts()
                result = await client.call_tool(
                    "read_workspace_text",
                    {
                        "root_id": "root-1",
                        "relative_path": "README.md",
                    },
                )

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

    _assert_runtime_clean(runtime, workspace_root)


@pytest.mark.runtime
@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    HEADER_MISMATCH_CASES,
    ids=[case.label for case in HEADER_MISMATCH_CASES],
)
async def test_streamable_http_rejects_header_mismatches(
    workspace_root: Path,
    tmp_path: Path,
    case: HeaderMismatchCase,
) -> None:
    with _http_server(workspace_root, tmp_path) as runtime:
        async with httpx2.AsyncClient(trust_env=False) as http_client:
            response = await _post_json(
                http_client,
                runtime.url,
                case.body,
                case.headers,
            )

    error = _assert_jsonrpc_error(
        response,
        status_code=400,
        request_id=case.request_id,
        error_code=HEADER_MISMATCH,
    )

    assert error["message"] == case.message
    assert str(workspace_root) not in response.text

    _assert_runtime_clean(runtime, workspace_root)


@pytest.mark.runtime
@pytest.mark.anyio
async def test_streamable_http_rejects_unsupported_matching_version(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    request_id = 201

    body = _request(
        "tools/list",
        request_id=request_id,
        protocol_version=UNSUPPORTED_PROTOCOL_VERSION,
    )
    headers = _headers(
        "tools/list",
        protocol_version=UNSUPPORTED_PROTOCOL_VERSION,
    )

    with _http_server(workspace_root, tmp_path) as runtime:
        async with httpx2.AsyncClient(trust_env=False) as http_client:
            response = await _post_json(
                http_client,
                runtime.url,
                body,
                headers,
            )

    error = _assert_jsonrpc_error(
        response,
        status_code=400,
        request_id=request_id,
        error_code=UNSUPPORTED_PROTOCOL_VERSION_ERROR,
    )

    assert error["message"] == "Unsupported protocol version"

    data_value = error.get("data")
    assert isinstance(data_value, dict)

    data = cast(dict[str, Any], data_value)

    assert data["requested"] == UNSUPPORTED_PROTOCOL_VERSION

    supported_value = data.get("supported")
    assert isinstance(supported_value, list)
    assert PROTOCOL_VERSION in supported_value

    assert str(workspace_root) not in response.text

    _assert_runtime_clean(runtime, workspace_root)


@pytest.mark.runtime
@pytest.mark.anyio
async def test_streamable_http_malformed_json_is_parse_error(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    with _http_server(workspace_root, tmp_path) as runtime:
        async with httpx2.AsyncClient(trust_env=False) as http_client:
            response = await http_client.post(
                runtime.url,
                headers=_headers("tools/list"),
                content=b"not-json",
            )

    error = _assert_jsonrpc_error(
        response,
        status_code=400,
        request_id=None,
        error_code=PARSE_ERROR,
    )

    assert error["message"] == "Parse error"
    assert str(workspace_root) not in response.text

    _assert_runtime_clean(runtime, workspace_root)


@pytest.mark.runtime
@pytest.mark.anyio
async def test_streamable_http_rejects_hostile_origin(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    request_id = 301

    body = _request(
        "tools/list",
        request_id=request_id,
    )
    headers = _headers("tools/list")
    headers["Origin"] = "https://untrusted.example"

    with _http_server(workspace_root, tmp_path) as runtime:
        async with httpx2.AsyncClient(trust_env=False) as http_client:
            response = await _post_json(
                http_client,
                runtime.url,
                body,
                headers,
            )

    assert response.status_code == 403
    assert str(workspace_root) not in response.text

    _assert_runtime_clean(runtime, workspace_root)


@pytest.mark.runtime
@pytest.mark.anyio
async def test_streamable_http_modern_requests_do_not_require_session_state(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    first_id = 401
    second_id = 402

    first_body = _request(
        "tools/list",
        request_id=first_id,
    )
    second_body = _request(
        "tools/list",
        request_id=second_id,
    )

    first_headers = _headers("tools/list")
    second_headers = _headers("tools/list")
    second_headers["Mcp-Session-Id"] = "stale-session-canary"

    with _http_server(workspace_root, tmp_path) as runtime:
        async with httpx2.AsyncClient(trust_env=False) as http_client:
            first = await _post_json(
                http_client,
                runtime.url,
                first_body,
                first_headers,
            )
            second = await _post_json(
                http_client,
                runtime.url,
                second_body,
                second_headers,
            )

    _assert_jsonrpc_result(
        first,
        request_id=first_id,
    )
    _assert_jsonrpc_result(
        second,
        request_id=second_id,
    )

    assert first.headers.get("Mcp-Session-Id") is None
    assert second.headers.get("Mcp-Session-Id") is None

    assert str(workspace_root) not in first.text
    assert str(workspace_root) not in second.text

    _assert_runtime_clean(runtime, workspace_root)


@pytest.mark.runtime
@pytest.mark.anyio
async def test_streamable_http_unknown_tool_is_a_top_level_protocol_error(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    request_id = 501
    body = _request(
        "tools/call",
        request_id=request_id,
        params={"name": "does_not_exist", "arguments": {}},
    )
    headers = _headers("tools/call", name="does_not_exist")

    with _http_server(workspace_root, tmp_path) as runtime:
        async with httpx2.AsyncClient(trust_env=False) as http_client:
            response = await _post_json(http_client, runtime.url, body, headers)

    error = _assert_jsonrpc_error(
        response,
        status_code=400,
        request_id=request_id,
        error_code=-32602,
    )
    assert error["message"] == "Unknown tool: does_not_exist"
    assert error["data"] == {"name": "does_not_exist"}
    _assert_runtime_clean(runtime, workspace_root)


def test_diagnostic_client_preserves_programmer_errors(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    caller_cwd = tmp_path / "diagnostic-programmer-error-caller"
    caller_cwd.mkdir()
    probe = """
import sys
import scripts.diagnostic_client as diagnostic_client

async def fail(_args):
    raise ValueError("programmer-defect-canary")

diagnostic_client._run = fail
sys.argv = ["diagnostic_client.py"]
diagnostic_client.main()
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert TRACEBACK_MARKER in completed.stderr
    assert "ValueError: programmer-defect-canary" in completed.stderr


@pytest.mark.runtime
def test_diagnostic_client_runs_against_http(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    caller_cwd = tmp_path / "diagnostic-http-caller"
    caller_cwd.mkdir()
    script = repo_root / "scripts" / "diagnostic_client.py"

    environment = server_environment(workspace_root)
    environment["MCP_GITHUB_TOKEN"] = SECRET_CANARY
    environment["MCP_UNRELATED_SECRET"] = SECRET_CANARY

    with _http_server(workspace_root, tmp_path) as runtime:
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--transport",
                "http",
                "--url",
                runtime.url,
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
        "transport: http",
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

    _assert_runtime_clean(runtime, workspace_root)


@pytest.mark.runtime
def test_diagnostic_client_reports_http_connection_failure_cleanly(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    caller_cwd = tmp_path / "diagnostic-http-failure-caller"
    caller_cwd.mkdir()
    script = repo_root / "scripts" / "diagnostic_client.py"

    environment = server_environment(workspace_root)
    environment["MCP_GITHUB_TOKEN"] = SECRET_CANARY
    environment["MCP_UNRELATED_SECRET"] = SECRET_CANARY

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        port = int(unavailable.getsockname()[1])
        url = f"http://127.0.0.1:{port}/mcp"

        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--transport",
                "http",
                "--url",
                url,
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

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("diagnostic_error: ")
    assert completed.stderr.count("\n") == 1
    assert "ConnectError" in completed.stderr
    assert TRACEBACK_MARKER not in completed.stderr
    assert SECRET_CANARY not in completed.stderr
    assert str(workspace_root) not in completed.stderr
