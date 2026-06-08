from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from mcp import types

from tests.mcp_test_utils import make_project_tree


class JsonLineReader:
    def __init__(self, stream) -> None:
        self._queue: queue.Queue[str | BaseException | None] = queue.Queue()
        self._thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self._thread.start()

    def _read(self, stream) -> None:
        try:
            for line in iter(stream.readline, ""):
                self._queue.put(line)
        except BaseException as exc:  # pragma: no cover - diagnostic only
            self._queue.put(exc)
        finally:
            self._queue.put(None)

    def read_message(self, *, timeout: float) -> dict[str, Any]:
        item = self._queue.get(timeout=timeout)
        if item is None:
            raise AssertionError("server stdout closed before expected response")
        if isinstance(item, BaseException):
            raise AssertionError("stdout reader failed") from item

        line = item.rstrip("\n")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"stdout contained non-protocol output: {line!r}") from exc


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _server_env(workspace_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    src = str(_repo_root() / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    env.update(
        {
            "ENABLE_FILESYSTEM": "true",
            "FS_ALLOWED_DIRS": str(workspace_root),
            "READ_ONLY": "true",
            "ENABLE_GITHUB": "false",
            "ENABLE_BROWSER": "false",
        }
    )
    return env


def _start_server(workspace_root: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "build_an_mcp_server.server"],
        cwd=str(_repo_root()),
        env=_server_env(workspace_root),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _send(proc: subprocess.Popen[str], message: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def _read_response(
    reader: JsonLineReader,
    *,
    response_id: int,
    timeout: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    seen: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        message = reader.read_message(timeout=remaining)
        if message.get("id") == response_id:
            return message
        seen.append(message)

    raise AssertionError(f"timed out waiting for response id {response_id}; saw {seen!r}")


def _shutdown(proc: subprocess.Popen[str]) -> None:
    try:
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_stdio_initialize_initialized_and_tools_list(tmp_path: Path) -> None:
    workspace_root = make_project_tree(tmp_path / "project")
    proc = _start_server(workspace_root)
    assert proc.stdout is not None
    reader = JsonLineReader(proc.stdout)

    try:
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": types.LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "chapter5-stdio-smoke",
                        "version": "0.1.0",
                    },
                },
            },
        )
        initialize = _read_response(reader, response_id=1)
        assert "result" in initialize
        assert "capabilities" in initialize["result"]

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        listed = _read_response(reader, response_id=2)

        tools = listed["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert {"list_files", "read_file"}.issubset(names)
        assert "write_file" not in names
    finally:
        _shutdown(proc)


def test_stdio_read_file_with_absolute_allowed_path(tmp_path: Path) -> None:
    workspace_root = make_project_tree(tmp_path / "project")
    target = workspace_root / "readme.md"
    proc = _start_server(workspace_root)
    assert proc.stdout is not None
    reader = JsonLineReader(proc.stdout)

    try:
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": types.LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "chapter5-stdio-smoke",
                        "version": "0.1.0",
                    },
                },
            },
        )
        _read_response(reader, response_id=1)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "read_file",
                    "arguments": {"path": str(target)},
                },
            },
        )
        response = _read_response(reader, response_id=2)

        result = response["result"]
        assert result.get("isError") is not True
        assert result["structuredContent"]["path"] == str(target)
        assert result["structuredContent"]["content"] == "# Project\nA sample project.\n"
    finally:
        _shutdown(proc)
