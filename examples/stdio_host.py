# examples/stdio_host.py
# STDIO host for your Ops-MCP server (server.py), with correct MCP handshake.
# Usage:
#   python examples/stdio_host.py
#   python examples/stdio_host.py --call get_user_info --args '{"username":"octocat"}'

from __future__ import annotations
import argparse, json, os, queue, sys, threading, subprocess, uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ENTRY = REPO_ROOT / "src" / "build_an_mcp_server" / "server.py"

PROTOCOL_VERSION = os.environ.get("MCP_PROTOCOL_VERSION", "2024-11-05")  # spec tag

def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

class MCPHost:
    def __init__(self, server_cmd: list[str], cwd: Path | None = None, env: dict | None = None):
        self.proc = subprocess.Popen(
            server_cmd,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env or os.environ.copy(),
        )
        self._outq: queue.Queue[str] = queue.Queue()
        self._pump()

    def _pump(self):
        def _pump_stdout():
            if not self.proc.stdout:
                return
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                if line:
                    self._outq.put(line)

        def _pump_stderr():
            if not self.proc.stderr:
                return
            for line in self.proc.stderr:
                sys.stderr.write(f"[server] {line}")

        threading.Thread(target=_pump_stdout, daemon=True).start()
        threading.Thread(target=_pump_stderr, daemon=True).start()

    def send(self, obj: dict) -> None:
        if not self.proc.stdin:
            raise RuntimeError("server stdin is closed")
        msg = json.dumps(obj, separators=(",", ":"))  # one JSON per line
        self.proc.stdin.write(msg + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float | None = 15.0) -> dict:
        raw = self._outq.get(timeout=timeout)
        return json.loads(raw)

    def close(self):
        try:
            self.send({"jsonrpc": "2.0", "id": _new_id("bye"), "method": "shutdown"})
        except Exception:
            pass
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=3.0)
        except Exception:
            self.proc.kill()

def initialize(host: MCPHost) -> dict:
    req_id = _new_id("init")
    host.send({
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {  # declare what the CLIENT supports; empty {} is fine
                "tools": {},
                "resources": {},
                "prompts": {}
            },
            "clientInfo": {"name": "ops-host", "version": "1.0"}
        }
    })
    return host.recv(timeout=20.0)

def send_initialized(host: MCPHost) -> None:
    # Required AFTER successful initialize, BEFORE using tools/resources/prompts
    host.send({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {"client": "ops-host"}
    })

def tools_list(host: MCPHost) -> dict:
    req_id = _new_id("list")
    host.send({"jsonrpc":"2.0","id":req_id,"method":"tools/list","params":{}})
    return host.recv(timeout=20.0)

def tools_call(host: MCPHost, name: str, arguments: dict) -> dict:
    req_id = _new_id("call")
    host.send({
        "jsonrpc":"2.0",
        "id":req_id,
        "method":"tools/call",
        "params":{"name":name,"arguments":arguments}
    })
    return host.recv(timeout=30.0)

def main():
    import argparse, json
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--call", default=None, help="Tool name to call")
    parser.add_argument("--args", default=None, help="JSON string of tool args")
    parser.add_argument("--python", default=sys.executable, help="Python to run server")
    args = parser.parse_args()

    env = os.environ.copy()
    if "GITHUB_TOKEN" not in env:
        sys.stderr.write("[warn] GITHUB_TOKEN not set; GitHub API calls may fail.\n")

    # Run server as module
    host = MCPHost([args.python, "-m", "build_an_mcp_server.server"], cwd=REPO_ROOT, env=env)
    try:
        print(">> initialize")
        init_reply = initialize(host)
        print(json.dumps(init_reply, indent=2, ensure_ascii=False))

        print("\n>> notifications/initialized")
        send_initialized(host)

        print("\n>> tools/list")
        list_reply = tools_list(host)
        print(json.dumps(list_reply, indent=2, ensure_ascii=False))

        if args.call:
            tool_args = {}
            if args.args:
                tool_args = json.loads(args.args)
            print(f"\n>> tools/call {args.call} {tool_args}")
            call_reply = tools_call(host, args.call, tool_args)
            print(json.dumps(call_reply, indent=2, ensure_ascii=False))
        else:
            print("\n(no --call provided; done.)")

    except queue.Empty:
        print("ERROR: timeout waiting for server response (see [server] logs above).", file=sys.stderr)
        sys.exit(1)
    finally:
        host.close()

if __name__ == "__main__":
    main()
