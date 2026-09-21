"""Connect to either transport and inspect the same MCP server surface."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from tempfile import TemporaryDirectory
from typing import Protocol, cast

import httpx2
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

PROTOCOL_VERSION = "2026-07-28"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_BASE_STDIO_MCP_SETTINGS = frozenset(
    {
        "MCP_SERVER_NAME",
        "MCP_ENABLE_WORKSPACE",
        "MCP_WORKSPACE_ROOTS",
        "MCP_ENABLE_GITHUB",
        "MCP_ENABLE_MUTATION",
        "MCP_ENABLE_BROWSER",
        "MCP_MAX_FILE_READ_BYTES",
        "MCP_MAX_WRITE_BYTES",
        "MCP_MAX_DIGEST_BYTES",
        "MCP_MAX_DIRECTORY_ENTRIES",
        "MCP_LOG_LEVEL",
    }
)
_GITHUB_STDIO_MCP_SETTINGS = frozenset(
    {
        "MCP_GITHUB_TOKEN",
        "MCP_GITHUB_REPOSITORIES",
        "MCP_GITHUB_TIMEOUT_SECONDS",
        "MCP_MAX_GITHUB_BODY_CHARS",
    }
)
_BROWSER_STDIO_MCP_SETTINGS = frozenset(
    {
        "MCP_BROWSER_ALLOWED_ORIGINS",
        "MCP_BROWSER_MAX_HANDLES",
        "MCP_BROWSER_HANDLE_TTL_SECONDS",
        "MCP_BROWSER_NAVIGATION_TIMEOUT_MS",
        "MCP_MAX_BROWSER_TEXT_CHARS",
    }
)
_SENSITIVE_MCP_NAME_PARTS = ("TOKEN", "SECRET", "PASSWORD")


class _ExceptionGroupLike(Protocol):
    exceptions: tuple[BaseException, ...]


def _feature_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def _mcp_environment() -> dict[str, str]:
    """Forward only stdio-relevant settings, with optional settings feature-scoped."""

    allowed = set(_BASE_STDIO_MCP_SETTINGS)
    if _feature_enabled("MCP_ENABLE_GITHUB"):
        allowed.update(_GITHUB_STDIO_MCP_SETTINGS)
    if _feature_enabled("MCP_ENABLE_BROWSER"):
        allowed.update(_BROWSER_STDIO_MCP_SETTINGS)

    return {key: os.environ[key] for key in allowed if key in os.environ}


def _exception_leaves(exc: BaseException) -> list[BaseException]:
    if not hasattr(exc, "exceptions"):
        return [exc]

    children = cast(_ExceptionGroupLike, exc).exceptions
    leaves: list[BaseException] = []
    for child in children:
        leaves.extend(_exception_leaves(child))
    return leaves


def _expected_runtime_failure(exc: BaseException) -> BaseException | None:
    expected: list[BaseException] = []
    unexpected: list[BaseException] = []

    for leaf in _exception_leaves(exc):
        if isinstance(leaf, httpx2.HTTPError | MCPError):
            expected.append(leaf)
        elif isinstance(leaf, asyncio.CancelledError | GeneratorExit):
            continue
        else:
            unexpected.append(leaf)

    if unexpected or not expected:
        return None
    return expected[0]


def _sanitized_error_message(exc: BaseException) -> str:
    message = " ".join(str(exc).split()) or "runtime connection failed"

    for key, value in os.environ.items():
        if not value:
            continue
        upper = key.upper()
        sensitive = key == "MCP_WORKSPACE_ROOTS" or any(
            marker in upper for marker in _SENSITIVE_MCP_NAME_PARTS
        )
        if sensitive:
            message = message.replace(value, "<redacted>")

    return message[:240]


def _report_runtime_failure(exc: BaseException) -> None:
    print(
        f"diagnostic_error: {type(exc).__name__}: {_sanitized_error_message(exc)}",
        file=sys.stderr,
    )


@asynccontextmanager
async def _open_client(args: argparse.Namespace) -> AsyncGenerator[Client]:
    if args.transport == "stdio":
        # Keep the server child away from a caller- or repository-owned `.env` file.
        with TemporaryDirectory(prefix="mcp-diagnostic-") as server_cwd:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "build_an_mcp_server.server"],
                env=_mcp_environment(),
                cwd=server_cwd,
            )
            async with Client(
                stdio_client(parameters),
                mode=PROTOCOL_VERSION,
                cache=None,
            ) as client:
                yield client
        return

    async with httpx2.AsyncClient(trust_env=False) as http_client:
        transport = streamable_http_client(args.url, http_client=http_client)
        async with Client(transport, mode=PROTOCOL_VERSION, cache=None) as client:
            yield client


async def _run(args: argparse.Namespace) -> int:
    async with _open_client(args) as client:
        try:
            tools = await client.list_tools()
            resources = await client.list_resources()
            prompts = await client.list_prompts()
        except MCPError as exc:
            _report_runtime_failure(exc)
            return 2

        print(f"transport: {args.transport}")
        print(f"protocol: {client.protocol_version}")
        print(f"tools: {', '.join(sorted(item.name for item in tools.tools))}")
        print(f"resources: {', '.join(sorted(str(item.uri) for item in resources.resources))}")
        print(f"prompts: {', '.join(sorted(item.name for item in prompts.prompts))}")

        if args.read is None:
            return 0

        try:
            result = await client.call_tool(
                "read_workspace_text",
                {
                    "root_id": args.root_id,
                    "relative_path": args.read,
                },
            )
        except MCPError as exc:
            _report_runtime_failure(exc)
            return 2

        print(f"read.is_error: {result.is_error}")
        if isinstance(result.structured_content, dict):
            structured = cast(
                dict[str, object],
                result.structured_content,  # pyright: ignore[reportUnknownMemberType]
            )
            print(f"read.relative_path: {structured.get('relative_path')}")
            print(f"read.bytes_read: {structured.get('bytes_read')}")
            print(f"read.truncated: {structured.get('truncated')}")
        return 1 if result.is_error else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect the repository's MCP v2 server.")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--root-id", default="root-1")
    parser.add_argument("--read", help="Optional relative workspace path to read.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except Exception as exc:
        failure = _expected_runtime_failure(exc)
        if failure is None:
            raise
        _report_runtime_failure(failure)
        raise SystemExit(2) from None

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
