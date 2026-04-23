from __future__ import annotations

"""Educational host-side schema validator used in Chapter 3.

This example launches the MCP server over stdio, discovers tool schemas via
`tools/list`, validates input arguments locally before `tools/call`, and can
optionally validate returned structured content against `outputSchema`.
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from transport import StdioTransport

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover - optional dependency for the example
    Draft202012Validator = None

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = os.environ.get("MCP_PROTOCOL_VERSION", "2025-11-25")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class MCPHost:
    def __init__(
        self,
        server_cmd: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.transport = StdioTransport(server_cmd, cwd=cwd, env=env)

    def send(self, msg: dict[str, Any]) -> None:
        self.transport.send(msg)

    def recv(self, timeout: float | None = None) -> dict[str, Any]:
        return self.transport.recv(timeout=timeout)

    def close(self) -> None:
        self.transport.close()


def require_success(msg: dict[str, Any], context: str) -> dict[str, Any]:
    if "error" in msg:
        err = msg["error"]
        raise RuntimeError(
            f"{context} failed with JSON-RPC error "
            f"{err.get('code')}: {err.get('message')} data={err.get('data')!r}"
        )
    return msg


def initialize(host: MCPHost) -> dict[str, Any]:
    rid = _new_id("init")
    host.send(
        {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "schema-validator", "version": "1.0"},
            },
        }
    )

    msg = require_success(host.recv(timeout=20.0), "initialize")
    server_version = msg.get("result", {}).get("protocolVersion")
    if server_version != PROTOCOL_VERSION:
        raise RuntimeError(
            f"unsupported protocol version: requested {PROTOCOL_VERSION}, got {server_version}"
        )
    return msg


def send_initialized(host: MCPHost) -> None:
    host.send(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
    )


def tools_list(host: MCPHost) -> dict[str, Any]:
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


def tools_call(host: MCPHost, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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


def _find_tool_definition(list_reply: dict[str, Any], tool_name: str) -> dict[str, Any]:
    tools = list_reply.get("result", {}).get("tools", [])
    for tool in tools:
        if tool.get("name") == tool_name:
            return tool
    raise KeyError(f"tool not found: {tool_name}")


def _repair_smart_quotes(s: str) -> str:
    return (
        s.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


def _load_args(args_json: str | None, args_file: str | None) -> dict[str, Any]:
    if args_file:
        text = Path(args_file).read_text(encoding="utf-8")
    else:
        text = args_json or "{}"

    obj = json.loads(_repair_smart_quotes(text).strip())
    if not isinstance(obj, dict):
        raise ValueError("tool arguments must decode to a JSON object")
    return obj


def _validator(schema: dict[str, Any] | None):
    if not Draft202012Validator:
        raise RuntimeError("jsonschema is not installed. Run: pip install jsonschema")
    return Draft202012Validator(schema or {"type": "object"})


def _validate_args(schema: dict[str, Any] | None, args_obj: dict[str, Any]) -> list[str]:
    validator = _validator(schema)
    errors: list[str] = []
    for err in validator.iter_errors(args_obj):
        path = "/" + "/".join(str(p) for p in err.path)
        errors.append(f"{path or '/'} violates {err.validator}: {err.message}")
    return errors


def _validate_output(
    tool_name: str,
    output_schema: dict[str, Any] | None,
    reply: dict[str, Any],
) -> list[str]:
    if not output_schema:
        return []

    result = reply.get("result", {})
    if result.get("isError"):
        return []

    structured = result.get("structuredContent")
    if structured is None:
        return [
            f"tool '{tool_name}' declared outputSchema but returned no structuredContent"
        ]

    validator = _validator(output_schema)
    errors: list[str] = []
    for err in validator.iter_errors(structured):
        path = "/" + "/".join(str(p) for p in err.path)
        errors.append(f"{path or '/'} violates {err.validator}: {err.message}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True, help="Tool name to call")
    parser.add_argument("--args", default=None, help="JSON string of tool arguments")
    parser.add_argument("--args-file", default=None, help="Path to a JSON file with tool arguments")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter to run the server")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass

    env = os.environ.copy()
    host = MCPHost(
        [args.python, "-m", "build_an_mcp_server.server"],
        cwd=str(REPO_ROOT),
        env=env,
    )
    try:
        initialize(host)
        send_initialized(host)

        list_reply = tools_list(host)
        tool_def = _find_tool_definition(list_reply, args.tool)
        input_schema = tool_def.get("inputSchema") or {}
        output_schema = tool_def.get("outputSchema") or None

        args_obj = _load_args(args.args, args.args_file)
        input_errors = _validate_args(input_schema, args_obj)
        if input_errors:
            print("Argument validation failed:", file=sys.stderr)
            for error in input_errors:
                print(f"  - {error}", file=sys.stderr)
            return 3

        reply = tools_call(host, args.tool, args_obj)

        output_errors = _validate_output(args.tool, output_schema, reply)
        if output_errors:
            print("Output validation failed:", file=sys.stderr)
            for error in output_errors:
                print(f"  - {error}", file=sys.stderr)
            return 5

        print(json.dumps(reply, indent=2, ensure_ascii=False))
        return 0

    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 4
    except TimeoutError:
        print("Timeout waiting for server reply.", file=sys.stderr)
        return 4
    finally:
        host.close()


if __name__ == "__main__":
    raise SystemExit(main())
