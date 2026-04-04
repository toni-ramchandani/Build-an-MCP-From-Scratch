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
SERVER_ENTRY = REPO_ROOT / "server.py"

PROTOCOL_VERSION = os.environ.get("MCP_PROTOCOL_VERSION", "2025-11-25")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class MCPHost:
    def __init__(
        self,
        server_cmd: list[str],
        cwd: Path | None = None,
        env: dict | None = None,
    ) -> None:
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

    def _pump(self) -> None:
        def _pump_stdout() -> None:
            if not self.proc.stdout:
                return
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                if line:
                    self._outq.put(line)

        def _pump_stderr() -> None:
            if not self.proc.stderr:
                return
            for line in self.proc.stderr:
                sys.stderr.write(f"[server] {line}")

        threading.Thread(target=_pump_stdout, daemon=True).start()
        threading.Thread(target=_pump_stderr, daemon=True).start()

    def send(self, obj: dict) -> None:
        if not self.proc.stdin:
            raise RuntimeError("server stdin is closed")

        msg = json.dumps(obj, separators=(",", ":"))
        self.proc.stdin.write(msg + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float | None = 15.0) -> dict:
        while True:
            try:
                raw = self._outq.get(timeout=timeout)
            except queue.Empty as e:
                raise TimeoutError("timed out waiting for server response") from e

            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                print(
                    f"[host] ignoring malformed stdout line: {raw!r} ({e})",
                    file=sys.stderr,
                )

    def close(self) -> None:
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception as e:
                print(f"[host] error closing server stdin: {e}", file=sys.stderr)

        try:
            self.proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            print("[host] server did not exit after EOF; killing process", file=sys.stderr)
            self.proc.kill()
        except Exception as e:
            print(f"[host] error waiting for server exit: {e}", file=sys.stderr)
            self.proc.kill()


def require_success(msg: dict, context: str) -> dict:
    if "error" in msg:
        err = msg["error"]
        raise RuntimeError(
            f"{context} failed with JSON-RPC error "
            f"{err.get('code')}: {err.get('message')} data={err.get('data')!r}"
        )
    return msg


def initialize(host: MCPHost) -> dict:
    rid = _new_id("init")
    host.send(
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ops-host", "version": "1.0"},
            },
        }
    )

    msg = require_success(host.recv(timeout=20.0), "initialize")
    server_version = msg["result"].get("protocolVersion")
    if server_version != PROTOCOL_VERSION:
        raise RuntimeError(
            f"unsupported protocol version: requested {PROTOCOL_VERSION}, "
            f"got {server_version}"
        )
    return msg


def send_initialized(host: MCPHost) -> None:
    host.send(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
    )


def tools_list(host: MCPHost) -> dict:
    rid = _new_id("list")
    host.send(
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/list",
            "params": {},
        }
    )
    return require_success(host.recv(timeout=20.0), "tools/list")


def tools_call(host: MCPHost, name: str, arguments: dict) -> dict:
    rid = _new_id("call")
    host.send(
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    return require_success(host.recv(timeout=30.0), "tools/call")


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--call", default=None, help="Tool name to call")
    parser.add_argument("--args", default=None, help="JSON string of tool args")
    parser.add_argument("--python", default=sys.executable, help="Python to run server")
    parser.add_argument("--server", default=str(SERVER_ENTRY), help="Path to server.py")
    args = parser.parse_args()

    env = os.environ.copy()
    if "GITHUB_TOKEN" not in env:
        sys.stderr.write(
            "[warn] GITHUB_TOKEN not set; GitHub-backed server tools may fail.\n"
        )

    host = MCPHost([args.python, args.server], cwd=REPO_ROOT, env=env)
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
                try:
                    tool_args = json.loads(args.args)
                except json.JSONDecodeError as e:
                    print(f"ERROR: --args must be valid JSON: {e}", file=sys.stderr)
                    sys.exit(2)

            print(f"\n>> tools/call {args.call} {tool_args}")
            call_reply = tools_call(host, args.call, tool_args)
            print(json.dumps(call_reply, indent=2, ensure_ascii=False))
        else:
            print("\n(no --call provided; done.)")

    except TimeoutError:
        print(
            "ERROR: timed out waiting for server response (see stderr logs above).",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        host.close()


if __name__ == "__main__":
    main()
