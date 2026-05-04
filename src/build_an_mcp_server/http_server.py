from __future__ import annotations

import contextlib
from urllib.parse import urlparse

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import ServerSettings, load_settings
from .factory import create_server


_LOCAL_HTTP_HOSTS = {"127.0.0.1", "localhost"}


def _origin_is_allowed(origin: str | None) -> bool:
    if origin is None:
        return True

    parsed = urlparse(origin)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in _LOCAL_HTTP_HOSTS
    )


class LocalOriginGuard:
    """Reject explicit non-local Origin headers for the local HTTP runtime."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] == "http":
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            origin = headers.get("origin")

            if not _origin_is_allowed(origin):
                response = JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32000,
                            "message": "Forbidden Origin",
                        },
                    },
                    status_code=403,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def create_http_app(
    settings: ServerSettings | None = None,
) -> Starlette:
    """Create the native Streamable HTTP ASGI app."""

    settings = settings or load_settings()
    mcp = create_server(settings)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Mount("/", app=mcp.streamable_http_app()),
        ],
        middleware=[
            Middleware(LocalOriginGuard),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    """Run the native Streamable HTTP entry point for local development."""

    uvicorn.run(create_http_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
