from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent


def _tool_text(result: CallToolResult) -> str:
    return "\n".join(
        item.text
        for item in result.content
        if isinstance(item, TextContent)
    )


@asynccontextmanager
async def _stdio_session() -> AsyncIterator[ClientSession]:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "build_an_mcp_server.server"],
        env=os.environ.copy(),
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def _http_session(url: str) -> AsyncIterator[ClientSession]:
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def _open_session(args: argparse.Namespace) -> AsyncIterator[ClientSession]:
    if args.transport == "stdio":
        async with _stdio_session() as session:
            yield session
    else:
        async with _http_session(args.url) as session:
            yield session


async def _run(args: argparse.Namespace) -> int:
    async with _open_session(args) as session:
        tools = await session.list_tools()
        tool_names = sorted(tool.name for tool in tools.tools)

        print(f"connected: {args.transport}")
        print(f"tools: {', '.join(tool_names)}")

        if not args.read_file:
            return 0

        if "read_file" not in tool_names:
            print("read_file: not available")
            return 2

        result = await session.call_tool(
            "read_file",
            {"path": args.read_file},
        )

        print(f"read_file.isError: {bool(result.isError)}")

        structured = result.structuredContent
        if isinstance(structured, dict):
            print(f"read_file.path: {structured.get('path')}")
            print(f"read_file.mimeType: {structured.get('mimeType')}")
            print(f"read_file.bytesRead: {structured.get('bytesRead')}")

        text = _tool_text(result).strip().replace("\n", "\\n")
        if text:
            print(f"read_file.text: {text[:200]}")

        return 1 if result.isError else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal MCP diagnostic client for the packaged server runtime.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/mcp",
    )
    parser.add_argument(
        "--read-file",
        help="Optional path to pass to the read_file tool. Use an absolute path inside FS_ALLOWED_DIRS.",
    )
    return parser.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
