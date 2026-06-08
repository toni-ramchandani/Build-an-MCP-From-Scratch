from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.mcp_test_utils import make_project_tree, tool_names


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, proc: subprocess.Popen[str], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise AssertionError(f"HTTP server exited early: {stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"HTTP server did not accept connections on port {port}")


@contextmanager
def _http_server(workspace_root: Path) -> Iterator[str]:
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env.update(
        {
            "ENABLE_FILESYSTEM": "true",
            "FS_ALLOWED_DIRS": str(workspace_root),
            "READ_ONLY": "true",
            "ENABLE_GITHUB": "false",
            "ENABLE_BROWSER": "false",
            "CHAPTER5_HTTP_PORT": str(port),
        }
    )
    code = (
        "import os, uvicorn; "
        "from build_an_mcp_server.http_server import create_http_app; "
        "uvicorn.run(create_http_app(), host='127.0.0.1', "
        "port=int(os.environ['CHAPTER5_HTTP_PORT']), log_level='error')"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=str(_repo_root()),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(port, proc)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _post_raw(url: str, body: bytes, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


@pytest.mark.anyio
async def test_streamable_http_initialize_and_tools_list(tmp_path: Path) -> None:
    workspace_root = make_project_tree(tmp_path / "project")

    with _http_server(workspace_root) as url:
        async with streamable_http_client(url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()

    names = tool_names(listed)
    assert {"list_files", "read_file"}.issubset(names)
    assert "write_file" not in names


def test_streamable_http_rejects_non_local_origin(tmp_path: Path) -> None:
    workspace_root = make_project_tree(tmp_path / "project")

    with _http_server(workspace_root) as url:
        status, _headers, body = _post_raw(
            url,
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8"),
            headers={"Origin": "https://attacker.example"},
        )

    assert status == 403
    assert b"Forbidden Origin" in body


def test_streamable_http_malformed_json_is_http_error(tmp_path: Path) -> None:
    workspace_root = make_project_tree(tmp_path / "project")

    with _http_server(workspace_root) as url:
        status, _headers, _body = _post_raw(url, b"not-json")

    assert status >= 400
