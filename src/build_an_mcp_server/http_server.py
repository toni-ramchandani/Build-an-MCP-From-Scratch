from __future__ import annotations

import uvicorn
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Route

from .config import ServerSettings, load_settings
from .factory import create_server
from .http_policy import HttpScopePolicy, OperationKey


def create_http_app(
    settings: ServerSettings,
    *,
    token_verifier: TokenVerifier | None = None,
    json_response: bool = False,
    transport_security: TransportSecuritySettings | None = None,
) -> Starlette:
    """Build the Streamable HTTP app and its application-owned authorization gate."""

    server = create_server(settings, boundary="http", token_verifier=token_verifier)
    app = server.streamable_http_app(
        host=settings.http_host,
        json_response=json_response,
        max_request_body_size=settings.max_http_request_bytes,
        transport_security=transport_security,
    )

    if settings.http_require_auth:
        assert settings.auth_resource_url is not None
        operation_scopes: dict[OperationKey, tuple[str, ...]] = {}
        if settings.enable_mutation:
            operation_scopes[("tools/call", "write_workspace_text")] = ("workspace:write",)
        metadata_url = str(build_resource_metadata_url(settings.auth_resource_url))
        for route in app.routes:
            if isinstance(route, Route) and route.path == "/mcp":
                route.app = HttpScopePolicy(
                    route.app,
                    base_scopes=settings.auth_required_scopes,
                    operation_scopes=operation_scopes,
                    resource_metadata_url=metadata_url,
                )
                break
        else:  # pragma: no cover - pinned SDK construction invariant
            raise RuntimeError("The SDK did not create the expected /mcp route")

    return app


def main() -> None:
    """Run the repository-owned loopback HTTP development entry point."""

    settings = load_settings()
    app = create_http_app(settings)
    uvicorn.run(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
