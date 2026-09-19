"""Send one MCP 2026-07-28 request as newline-delimited JSON over stdio."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from mcp.client.stdio import get_default_environment

PROTOCOL_VERSION = "2026-07-28"


def _request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "chapter-3-raw-trace",
                    "version": "0.2.0",
                },
            }
        },
    }


def _server_environment(root: Path) -> dict[str, str]:
    return get_default_environment() | {
        "MCP_ENABLE_WORKSPACE": "true",
        "MCP_WORKSPACE_ROOTS": str(root),
        "MCP_ENABLE_GITHUB": "false",
        "MCP_ENABLE_MUTATION": "false",
        "MCP_ENABLE_BROWSER": "false",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trace one modern tools/list exchange over MCP stdio framing."
    )
    parser.add_argument("--root", type=Path, required=True, help="Explicit workspace root.")
    args = parser.parse_args()
    root = args.root.expanduser().resolve(strict=True)
    if not root.is_dir():
        parser.error("--root must name an existing directory")

    request = _request()
    with TemporaryDirectory(prefix="mcp-raw-trace-") as runtime_cwd:
        completed = subprocess.run(
            [sys.executable, "-m", "build_an_mcp_server.server"],
            env=_server_environment(root),
            cwd=runtime_cwd,
            input=json.dumps(request, separators=(",", ":")) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"server exited with status {completed.returncode}")
    lines = [line for line in completed.stdout.splitlines() if line]
    if len(lines) != 1:
        raise RuntimeError("expected exactly one JSON-RPC response line")
    response = json.loads(lines[0])

    print("sent:")
    print(json.dumps(request, indent=2))
    print("received:")
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
