from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from transport import StdioTransport

try:
    from jsonschema import Draft202012Validator
except Exception:
    Draft202012Validator = None


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ENTRY = REPO_ROOT / "src" / "build_an_mcp_server" / "server.py"
PROTOCOL_VERSION = os.environ.get("MCP_PROTOCOL_VERSION", "2025-11-25")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class MCPHost:
    def __init__(self, server_cmd: list[str]):
        self.transport = StdioTransport(server_cmd)

    def send(self, msg: dict) -> None:
        self.transport.send(msg)

    def recv(self, timeout: float | None = None) -> dict:
        return self.transport.recv(timeout=timeout)

    def close(self) -> None:
        self.transport.close()


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


def _find_tool_schema(list_reply: dict, tool_name: str) -> tuple[dict, dict]:
    tools = list_reply.get("result", {}).get("tools", [])
    for tool in tools:
        if tool.get("name") == tool_name:
            return tool.get("inputSchema") or {}, tool.get("outputSchema") or {}
    raise KeyError(f"tool not found: {tool_name}")


def _repair_smart_quotes(s: str) -> str:
    return (
        s.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


def _load_args(ns_args: str | None, ns_args_file: str | None) -> dict:
    if ns_args_file:
        text = Path(ns_args_file).read_text(encoding="utf-8")
    else:
        text = ns_args or "{}"

    text = _repair_smart_quotes(text).strip()
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("tool arguments must decode to a JSON object")
    return obj


def _validate_args(schema: dict, args_obj: dict) -> list[str]:
    if not Draft202012Validator:
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tool",
        required=True,
        help="Tool name (for example, get_user_info)",
    )
    parser.add_argument(
        "--args",
        default=None,
        help="JSON string of tool arguments",
    )
    parser.add_argument(
        "--args-file",
        default=None,
        help="Path to a JSON file with tool arguments",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter to run the server",
    )
    parser.add_argument(
        "--server",
        default=str(SERVER_ENTRY),
        help="Path to server.py",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass

    # Run server as module to avoid import issues
    host = MCPHost([args.python, "-m", "build_an_mcp_server.server"])
    try:
        initialize(host)
        send_initialized(host)

        list_reply = tools_list(host)
        input_schema, _ = _find_tool_schema(list_reply, args.tool)

        args_obj = _load_args(args.args, args.args_file)

        errors = _validate_args(input_schema, args_obj)
        if errors:
            print("Argument validation failed:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 3

        reply = tools_call(host, args.tool, args_obj)
        print(json.dumps(reply, indent=2, ensure_ascii=False))
        return 0

    except json.JSONDecodeError as e:
        print(f"Invalid --args JSON: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except TimeoutError:
        print("Timeout waiting for server reply.", file=sys.stderr)
        return 4
    finally:
        host.close()


if __name__ == "__main__":
    raise SystemExit(main())