# examples/http_adapter.py #3.3
from __future__ import annotations
import json, os, queue, subprocess, sys, threading, uuid               #A
from pathlib import Path                                               #A
from typing import Any, Dict                                           #A
from fastapi import FastAPI, Request, Response, HTTPException          #A
from fastapi.responses import JSONResponse, StreamingResponse          #A

REPO_ROOT = Path(__file__).resolve().parents[1]                        #B
SERVER_ENTRY = REPO_ROOT / "src" / "build_an_mcp_server" / "server.py"                                 #B

app = FastAPI(title="MCP HTTP Adapter")                                #C

def _new_id(prefix: str) -> str:                                       #D
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

class StdioBridge:                                                     #E
    def __init__(self, cmd: list[str]):
        self.proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        self._q: "queue.Queue[str]" = queue.Queue()
        self._pump()

    def _pump(self) -> None:                                           #F
        def _stdout():
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                if line:
                    self._q.put(line)
        def _stderr():
            if not self.proc.stderr:
                return
            for line in self.proc.stderr:
                sys.stderr.write(f"[server] {line}")
        threading.Thread(target=_stdout, daemon=True).start()
        threading.Thread(target=_stderr, daemon=True).start()

    def send(self, obj: Dict[str, Any]) -> None:                        #G
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def recv_matching(self, target_id: Any, timeout: float = 30.0) -> Dict[str, Any]:  #H
        while True:
            raw = self._q.get(timeout=timeout)
            msg = json.loads(raw)
            # Match on jsonrpc id; ignore unrelated notifications
            if msg.get("id") == target_id:
                return msg

    def close(self) -> None:                                            #I
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=3.0)
        except Exception:
            self.proc.kill()

bridge = StdioBridge([sys.executable, "-m", "build_an_mcp_server.server"])              #J

def _sse_event(event: str, data: Dict[str, Any]) -> str:               #K
    return f"event: {event}\n" + "data: " + json.dumps(data) + "\n\n"

@app.post("/mcp")                                                      #L
async def mcp(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(400, "Body must be a JSON-RPC 2.0 object")

    req_id = body.get("id", _new_id("http"))
    body["id"] = req_id
    bridge.send(body)                                                  #M
    try:
        reply = bridge.recv_matching(req_id, timeout=60.0)             #N
    except queue.Empty:
        raise HTTPException(504, "Upstream MCP server timed out")
    return JSONResponse(reply)                                         #O

@app.post("/mcp/stream")                                               #P
async def mcp_stream(request: Request) -> StreamingResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise HTTPException(400, "Body must be a JSON-RPC 2.0 object")

    req_id = body.get("id", _new_id("sse"))
    body["id"] = req_id

    def gen():
        # Optional "start" signal
        yield _sse_event("start", {"id": req_id})                      #Q
        bridge.send(body)
        try:
            # Minimal stream: emit only the terminal message as 'result' or 'error'
            reply = bridge.recv_matching(req_id, timeout=300.0)
            if "result" in reply:
                yield _sse_event("result", reply["result"])
            else:
                yield _sse_event("error", reply.get("error", {}))
        except queue.Empty:
            yield _sse_event("error", {"code": "deadline_exceeded"})
    return StreamingResponse(gen(), media_type="text/event-stream")    #R

# Optional: run with `python examples/http_adapter.py`
if __name__ == "__main__":                                             #S
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
