from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from mcp.client.stdio import get_default_environment
from mcp_types import CallToolResult, TextContent
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from build_an_mcp_server.config import ServerSettings


class _ExplicitTestSettings(ServerSettings):
    """Retain production validation with constructor-only test inputs."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def make_settings(**values: object) -> ServerSettings:
    """Construct settings without consulting a developer's process or `.env` file."""

    settings_type = cast(Any, _ExplicitTestSettings)
    return cast(ServerSettings, settings_type(_env_file=None, **values))


def tool_text(result: CallToolResult) -> str:
    return "\n".join(item.text for item in result.content if isinstance(item, TextContent))


def server_environment(root: Path, *, port: int | None = None) -> dict[str, str]:
    """Build the explicit environment used by deterministic runtime tests."""

    values = get_default_environment() | {
        "MCP_ENABLE_WORKSPACE": "true",
        "MCP_WORKSPACE_ROOTS": str(root),
        "MCP_ENABLE_GITHUB": "false",
        "MCP_ENABLE_MUTATION": "false",
        "MCP_ENABLE_BROWSER": "false",
    }
    if port is not None:
        values["MCP_HTTP_PORT"] = str(port)
    return values
