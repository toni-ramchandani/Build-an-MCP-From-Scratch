from __future__ import annotations
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ENTRY = REPO_ROOT / "src" / "build_an_mcp_server" / "server.py"
PROTOCOL_VERSION = os.environ.get("MCP_PROTOCOL_VERSION", "2024-11-05")

try:
    import jsonschema
    from jsonschema import Draft202012Validator
except Exception:
    jsonschema = None
    Draft202012Validator = None


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
        self._outq: "queue.Queue[str]" = queue.Queue()
        self._pump()

    def _pump(self) -> None:
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
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float | None = 20.0) -> dict:
        raw = self._outq.get(timeout=timeout)
        return json.loads(raw)

    def close(self) -> None:
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
    rid = _new_id("init")
    host.send({
        "jsonrpc": "2.0",
        "id": rid,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "clientInfo": {"name": "ops-host", "version": "1.0"}
        }
    })
    return host.recv()


def send_initialized(host: MCPHost) -> None:
    host.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {"client": "ops-host"}})


def tools_list(host: MCPHost) -> dict:
    rid = _new_id("list")
    host.send({"jsonrpc": "2.0", "id": rid, "method": "tools/list", "params": {}})
    return host.recv()


def tools_call(host: MCPHost, name: str, arguments: dict) -> dict:
    rid = _new_id("call")
    host.send({
        "jsonrpc": "2.0",
        "id": rid,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments}
    })
    return host.recv(timeout=30.0)


def _find_tool_schema(list_reply: dict, tool_name: str) -> tuple[dict, dict]:
    tools = list_reply.get("result", {}).get("tools", [])
    for t in tools:
        if t.get("name") == tool_name:
            return t.get("inputSchema") or {}, t.get("outputSchema") or {}
    raise KeyError(f"tool not found: {tool_name}")


def _repair_smart_quotes(s: str) -> str:
    return s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")


def _load_args(ns_args: str | None, ns_args_file: str | None) -> dict:
    if ns_args_file:
        p = Path(ns_args_file)
        text = p.read_text(encoding="utf-8")
    else:
        text = ns_args or "{}"
    text = _repair_smart_quotes(text).strip()
    return json.loads(text)


def _validate_args(schema: dict, args_obj: dict) -> list[str]:
    if not jsonschema or not Draft202012Validator:
        return ["jsonschema is not installed. Run: pip install jsonschema"]
    try:
        validator = Draft202012Validator(schema or {"type": "object"})
    except Exception as e:
        return [f"schema error: {e}"]
    errors: list[str] = []
    for err in validator.iter_errors(args_obj):
        path = "/" + "/".join(str(p) for p in err.path)
        rule = err.validator
        msg = err.message
        errors.append(f"{path or '/'} violates {rule}: {msg}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True, help="Tool name (e.g., get_user_info)")
    ap.add_argument("--args", default=None, help="JSON string of tool args")
    ap.add_argument("--args-file", default=None, help="Path to a JSON file with tool args")
    ap.add_argument("--python", default=sys.executable, help="Python to run server")
    ns = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass

    # Run server as module
    host = MCPHost([ns.python, "-m", "build_an_mcp_server.server"], cwd=REPO_ROOT)
    try:
        _ = initialize(host)
        send_initialized(host)

        tl = tools_list(host)
        in_schema, out_schema = _find_tool_schema(tl, ns.tool)

        args_obj = _load_args(ns.args, ns.args_file)

        errs = _validate_args(in_schema, args_obj)
        if errs:
            print("Argument validation failed:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 3

        reply = tools_call(host, ns.tool, args_obj)
        print(json.dumps(reply, indent=2, ensure_ascii=False))
        return 0

    except json.JSONDecodeError as e:
        print(f"Invalid --args JSON: {e}", file=sys.stderr)
        return 2
    except queue.Empty:
        print("Timeout waiting for server reply.", file=sys.stderr)
        return 4
    finally:
        host.close()


if __name__ == "__main__":
    raise SystemExit(main())