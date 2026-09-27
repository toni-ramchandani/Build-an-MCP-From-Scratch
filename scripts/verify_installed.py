"""Verify the built wheel's two console commands outside the checkout.

Run after scripts/verify.py with the locked development environment. Dependencies
are exported from uv.lock; the application is installed from the wheel only.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx2
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client

PROTOCOL_VERSION = "2026-07-28"
CANARY = "installed-wheel-canary\n"


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, timeout=180)


async def _probe(command: str, url: str, workspace: Path) -> None:
    import build_an_mcp_server

    package_file = build_an_mcp_server.__file__
    assert package_file is not None
    assert Path(package_file).resolve().is_relative_to(Path(sys.prefix).resolve())
    environment = get_default_environment() | {
        "MCP_ENABLE_WORKSPACE": "true",
        "MCP_WORKSPACE_ROOTS": str(workspace),
        "MCP_ENABLE_GITHUB": "false",
        "MCP_ENABLE_MUTATION": "false",
        "MCP_ENABLE_BROWSER": "false",
    }
    async with httpx2.AsyncClient(trust_env=False) as http:
        transport = (
            streamable_http_client(url, http_client=http)
            if url
            else stdio_client(
                StdioServerParameters(command=command, env=environment, cwd=Path.cwd())
            )
        )
        async with Client(transport, mode=PROTOCOL_VERSION, cache=None) as client:
            assert client.protocol_version == PROTOCOL_VERSION
            assert {tool.name for tool in (await client.list_tools()).tools} == {
                "list_workspace_directory",
                "read_workspace_text",
            }
            assert {str(item.uri) for item in (await client.list_resources()).resources} == {
                "workspace://manifest"
            }
            assert {item.name for item in (await client.list_prompts()).prompts} == {
                "review_workspace_file"
            }
            result = await client.call_tool(
                "read_workspace_text",
                {"root_id": "root-1", "relative_path": "canary.txt"},
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["content"] == CANARY
    print(f"installed {'http' if url else 'stdio'}: discovery and canary read passed")


def _wait(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("installed HTTP command exited before readiness")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError("installed HTTP command did not listen within 10 seconds")


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="mcp-installed-proof-") as temporary:
        root = Path(temporary)
        output, environment, outside = root / "dist", root / "venv", root / "outside"
        outside.mkdir()
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "canary.txt").write_bytes(CANARY.encode("utf-8"))
        requirements = root / "requirements.txt"
        _run(
            ["uv", "build", "--no-build-isolation", "--no-sources", "--out-dir", str(output)],
            cwd=repo,
        )
        wheels = list(output.glob("*.whl"))
        assert len(wheels) == 1 and len(list(output.glob("*.tar.gz"))) == 1
        for artifact in sorted(output.iterdir()):
            if artifact.suffix in {".whl", ".gz"}:
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                print(f"sha256 {artifact.name}: {digest}", flush=True)
        _run(
            [
                "uv",
                "export",
                "--quiet",
                "--frozen",
                "--no-dev",
                "--no-editable",
                "--no-emit-project",
                "--output-file",
                str(requirements),
            ],
            cwd=repo,
        )
        _run(["uv", "venv", "--python", sys.executable, str(environment)], cwd=outside)
        binary = environment / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        _run(["uv", "pip", "sync", "--python", str(python), str(requirements)], cwd=outside)
        _run(
            ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheels[0])],
            cwd=outside,
        )
        extension = ".exe" if os.name == "nt" else ""
        stdio = binary / f"build-an-mcp-server{extension}"
        http_command = binary / f"build-an-mcp-server-http{extension}"
        assert stdio.is_file() and http_command.is_file()
        probe = [str(python), "-I", str(Path(__file__).resolve()), "--probe", str(stdio)]
        _run([*probe, "", str(workspace)], cwd=outside)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = int(listener.getsockname()[1])
        child_environment = get_default_environment() | {
            "MCP_ENABLE_WORKSPACE": "true",
            "MCP_WORKSPACE_ROOTS": str(workspace),
            "MCP_ENABLE_GITHUB": "false",
            "MCP_ENABLE_MUTATION": "false",
            "MCP_ENABLE_BROWSER": "false",
            "MCP_HTTP_HOST": "127.0.0.1",
            "MCP_HTTP_PORT": str(port),
        }
        with (
            (root / "http.stdout").open("wb") as stdout,
            (root / "http.stderr").open("wb") as stderr,
        ):
            process = subprocess.Popen(
                [str(http_command)],
                cwd=outside,
                env=child_environment,
                stdout=stdout,
                stderr=stderr,
            )
            try:
                _wait(process, port)
                _run([*probe, f"http://127.0.0.1:{port}/mcp", str(workspace)], cwd=outside)
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError("installed HTTP command required forced kill") from None
        print("installed package proof passed (wheel built from sdist; locked dependencies)")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--probe":
        asyncio.run(_probe(sys.argv[2], sys.argv[3], Path(sys.argv[4])))
    else:
        main()
