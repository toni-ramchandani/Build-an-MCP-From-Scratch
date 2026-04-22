"""Simplified HTTP-to-stdio bridge used in Chapter 3.

This example exists to make Streamable HTTP request forwarding and
response-scoped SSE visible without rewriting the underlying MCP server.
It is not a full Streamable HTTP implementation: it omits GET-opened
SSE streams, stateful sessions, MCP-Protocol-Version enforcement, and
HTTP authorization.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

REPO_ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="MCP HTTP Adapter")


class StdioBridge:
    """Forward JSON-RPC messages between HTTP and a stdio MCP server."""

    def __init__(self, cmd: list[str]) -> None:
        self.proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=os.environ.copy(),
        )
        self._q: queue.Queue[str] = queue.Queue()
        self._pending: dict[Any, list[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._pump()

    def _pump(self) -> None:
        def _stdout() -> None:
            if not self.proc.stdout:
                return
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                if line:
                    self._q.put(line)

        def _stderr() -> None:
            if not self.proc.stderr:
                return
            for line in self.proc.stderr:
                sys.stderr.write(f"[server] {line}")

        threading.Thread(target=_stdout, daemon=True).start()
        threading.Thread(target=_stderr, daemon=True).start()

    def send(self, obj: dict[str, Any]) -> None:
        if not self.proc.stdin:
            raise RuntimeError("server stdin is closed")

        msg = json.dumps(obj, separators=(",", ":"))
        self.proc.stdin.write(msg + "\n")
        self.proc.stdin.flush()

    def recv_matching(self, target_id: Any, timeout: float = 30.0) -> dict[str, Any]:
        with self._pending_lock:
            bucket = self._pending.get(target_id)
            if bucket:
                return bucket.pop(0)

        while True:
            try:
                raw = self._q.get(timeout=timeout)
            except queue.Empty as e:
                raise TimeoutError("timed out waiting for server response") from e

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as e:
                print(
                    f"[adapter] ignoring malformed stdout line: {raw!r} ({e})",
                    file=sys.stderr,
                )
                continue

            msg_id = msg.get("id")
            if msg_id == target_id:
                return msg

            with self._pending_lock:
                self._pending.setdefault(msg_id, []).append(msg)

    def close(self) -> None:
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception as e:
                print(f"[adapter] error closing server stdin: {e}", file=sys.stderr)

        try:
            self.proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            print("[adapter] server did not exit cleanly; killing process", file=sys.stderr)
            self.proc.kill()
        except Exception as e:
            print(f"[adapter] error waiting for server exit: {e}", file=sys.stderr)
            self.proc.kill()


bridge = StdioBridge([sys.executable, "-m", "build_an_mcp_server.server"])


@app.on_event("shutdown")
def _shutdown_bridge() -> None:
    bridge.close()


def _accept_values(request: Request) -> set[str]:
    accept = request.headers.get("accept", "")
    return {
        part.split(";", 1)[0].strip().lower()
        for part in accept.split(",")
        if part.strip()
    }


def _require_standard_accept(request: Request) -> None:
    accepted = _accept_values(request)
    required = {"application/json", "text/event-stream"}
    if not required.issubset(accepted):
        raise HTTPException(
            status_code=406,
            detail="Accept must include application/json and text/event-stream",
        )


def _prefer_stream(request: Request) -> bool:
    """Adapter-specific switch used only by this teaching bridge."""
    return request.headers.get("x-prefer-stream", "").lower() == "true"


def _sse_json(obj: dict[str, Any]) -> str:
    return "data: " + json.dumps(obj, separators=(",", ":")) + "\n\n"


@app.post("/mcp")
async def mcp(request: Request) -> Response:
    _require_standard_accept(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Body must be one JSON-RPC 2.0 object")

    if "id" not in body:
        bridge.send(body)
        return Response(status_code=202)

    req_id = body["id"]
    bridge.send(body)

    if not _prefer_stream(request):
        try:
            reply = bridge.recv_matching(req_id, timeout=60.0)
        except TimeoutError:
            raise HTTPException(status_code=504, detail="Upstream MCP server timed out")
        return JSONResponse(reply)

    def gen():
        try:
            reply = bridge.recv_matching(req_id, timeout=300.0)
            yield _sse_json(reply)
        except TimeoutError:
            yield _sse_json(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": "deadline_exceeded",
                    },
                }
            )

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
