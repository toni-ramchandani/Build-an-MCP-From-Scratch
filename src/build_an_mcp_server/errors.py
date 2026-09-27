from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError


class PublicToolError(ToolError):
    """An intentionally caller-safe tool failure."""


class ConfigurationBoundaryError(RuntimeError):
    """Raised before serving when a transport/policy combination is unsafe."""
