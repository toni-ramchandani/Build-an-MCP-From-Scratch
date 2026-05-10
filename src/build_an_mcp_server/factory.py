from __future__ import annotations

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base
from mcp.types import CallToolResult, TextContent

from .config import ServerSettings
from .fs_utils import (
    list_directory_entries,
    read_file_text,
    write_file_text,
)
from .normalizers import (
    map_allowed_roots,
    map_directory_listing,
    map_text_file,
    map_write_receipt,
    resource_json,
)
from .runtime_state import make_app_lifespan


def create_server(settings: ServerSettings) -> FastMCP:
    """Assemble one FastMCP server from validated settings."""

    mcp = FastMCP(
        settings.server_name,
        lifespan=make_app_lifespan(settings),
    )

    if settings.enable_filesystem:
        _register_filesystem_capabilities(mcp, settings)

    _register_prompt_capabilities(mcp)

    if settings.enable_github:
        _register_github_capabilities(mcp, settings)

    if settings.enable_browser:
        _register_browser_capabilities(mcp, settings)

    return mcp


def _register_filesystem_capabilities(
    mcp: FastMCP,
    settings: ServerSettings,
) -> None:
    allowed_roots = settings.fs_allowed_dirs

    @mcp.resource("filesystem://roots", mime_type="application/json")
    def filesystem_roots() -> str:
        manifest = map_allowed_roots(
            allowed_roots,
            read_only=settings.read_only,
        )
        return resource_json(manifest)

    @mcp.tool()
    def list_files(path: str) -> CallToolResult:
        try:
            directory, children = list_directory_entries(
                path,
                allowed_roots,
            )
            listing = map_directory_listing(directory, children)
        except (ValueError, OSError) as exc:
            return _tool_error(str(exc))

        names = [entry.name for entry in listing.entries]
        fallback = "\n".join(names) if names else "(empty directory)"
        return _tool_success(listing, fallback)

    @mcp.tool()
    def read_file(path: str) -> CallToolResult:
        try:
            resolved, content = read_file_text(path, allowed_roots)
            result = map_text_file(resolved, content)
        except (ValueError, OSError, UnicodeError) as exc:
            return _tool_error(str(exc))

        return _tool_success(result, result.content)

    if not settings.read_only:

        @mcp.tool()
        def write_file(
            path: str,
            content: str,
            overwrite: bool = True,
        ) -> CallToolResult:
            try:
                resolved = write_file_text(
                    path,
                    content,
                    allowed_roots,
                    overwrite=overwrite,
                )
                receipt = map_write_receipt(resolved, content, overwrite)
            except (ValueError, OSError, UnicodeError) as exc:
                return _tool_error(str(exc))

            fallback = f"Wrote {receipt.bytesWritten} bytes to {receipt.path}"
            return _tool_success(receipt, fallback)


def _register_prompt_capabilities(mcp: FastMCP) -> None:
    @mcp.prompt(title="Review a file")
    def review_file(path: str) -> list[base.Message]:
        return [
            base.UserMessage(f"Review the file at {path}."),
            base.UserMessage(
                "First call read_file to inspect its contents. "
                "Then summarize purpose, risks, and suggested improvements."
            ),
        ]

    @mcp.prompt(title="Inspect a directory")
    def inspect_directory(path: str) -> list[base.Message]:
        return [
            base.UserMessage(f"Inspect the directory at {path}."),
            base.UserMessage(
                "Start with list_files. Identify important entries, "
                "then read only the files that matter for the task."
            ),
        ]


def _register_github_capabilities(
    mcp: FastMCP,
    settings: ServerSettings,
) -> None:
    try:
        from .github_utils import register_github_capabilities
    except ImportError as exc:
        raise RuntimeError(
            "ENABLE_GITHUB is true, but github_utils.py does not expose "
            "register_github_capabilities()."
        ) from exc

    register_github_capabilities(mcp, settings)


def _register_browser_capabilities(
    mcp: FastMCP,
    settings: ServerSettings,
) -> None:
    try:
        from .browser_utils import register_browser_capabilities
    except ImportError as exc:
        raise RuntimeError(
            "ENABLE_BROWSER is true, but browser_utils.py does not expose "
            "register_browser_capabilities()."
        ) from exc

    register_browser_capabilities(mcp, settings)


def _tool_success(model: BaseModel, fallback_text: str) -> CallToolResult:
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=fallback_text,
            )
        ],
        structuredContent=model.model_dump(mode="json"),
    )


def _tool_error(message: str) -> CallToolResult:
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=message,
            )
        ],
        isError=True,
    )
