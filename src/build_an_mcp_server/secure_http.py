from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2
import uvicorn
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.routing import Route

from .admission import AuthenticatedAdmission, IngressLimit, WorkSlots
from .auth_verifier import JwtVerifier
from .corpus_policy import CorpusRejected, validate_corpus
from .http_policy import HttpScopePolicy
from .http_server import create_http_app
from .security_config import SecuritySettings


def create_secure_app(
    settings: SecuritySettings, *, transport: httpx2.AsyncBaseTransport | None = None
) -> Starlette:
    """Build the existing application with an owned verifier and bounded admission."""
    if settings.security_profile == "read-only":
        assert settings.corpus_approval_file is not None
        validate_corpus(settings.workspace_roots[0], settings.corpus_approval_file)
    client = httpx2.AsyncClient(
        transport=transport,
        trust_env=False,
        headers={"Accept-Encoding": "identity"},
        follow_redirects=False,
        timeout=httpx2.Timeout(2),
        limits=httpx2.Limits(max_connections=2, max_keepalive_connections=2),
    )
    verifier = JwtVerifier(settings, client)
    # AsyncClient has made no requests at construction. Lifespan owns all network use.
    app = create_http_app(settings, token_verifier=verifier, json_response=True)
    slots = WorkSlots(settings.global_slots, settings.principal_slots)
    for route in app.routes:
        if isinstance(route, Route) and route.path == "/mcp":
            assert isinstance(route.app, HttpScopePolicy)
            route.app.app = AuthenticatedAdmission(route.app.app, slots=slots)
            break
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(selected: Starlette) -> AsyncGenerator[None]:
        async with client, original_lifespan(selected):
            yield

    app.router.lifespan_context = lifespan
    app.add_middleware(
        IngressLimit, limit=settings.ingress_slots, deadline=settings.request_deadline_seconds
    )
    app.state.work_slots = slots
    return app


def main() -> None:
    try:
        settings = SecuritySettings()  # pyright: ignore[reportCallIssue]
        app = create_secure_app(settings)
    except (ValidationError, CorpusRejected):
        # Never serialize inputs, validation context or exception chains here.
        logging.getLogger(__name__).error("security_configuration_rejected")
        raise SystemExit(2) from None
    uvicorn.run(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_level=settings.log_level.lower(),
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
