from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager

import anyio
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class Busy(Exception):
    pass


class WorkSlots:
    """Event-loop-owned counters: no waiting queue and no idle principal entries."""

    def __init__(self, global_limit: int, principal_limit: int) -> None:
        self.global_limit = global_limit
        self.principal_limit = principal_limit
        self.active = 0
        self.by_principal: dict[tuple[str, str], int] = {}

    @contextmanager
    def reserve(self, principal: tuple[str, str]) -> Generator[None]:
        count = self.by_principal.get(principal, 0)
        if self.active >= self.global_limit or count >= self.principal_limit:
            raise Busy()
        self.active += 1
        self.by_principal[principal] = count + 1
        try:
            yield
        finally:
            self.active -= 1
            remaining = self.by_principal[principal] - 1
            if remaining:
                self.by_principal[principal] = remaining
            else:
                del self.by_principal[principal]


class IngressLimit:
    """Bound concurrent HTTP work before authentication; edge owns socket limits."""

    def __init__(self, app: ASGIApp, *, limit: int, deadline: float) -> None:
        self.app, self.limit, self.deadline = app, limit, deadline
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        if sum(len(k) + len(v) for k, v in headers) > 24_576:
            await JSONResponse({"error": "headers_too_large"}, status_code=431)(
                scope, receive, send
            )
            return
        if len([1 for k, _ in headers if k.lower() == b"authorization"]) > 1:
            await JSONResponse({"error": "ambiguous_authorization"}, status_code=400)(
                scope, receive, send
            )
            return
        if self.active >= self.limit:
            await JSONResponse({"error": "server_busy"}, status_code=503)(scope, receive, send)
            return
        self.active += 1
        started = False
        expires = time.monotonic() + self.deadline

        async def send_before_deadline(message: Message) -> None:
            nonlocal started
            # Synchronous work may defer cancellation. Do not send a late success.
            if time.monotonic() >= expires:
                raise TimeoutError()
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            with anyio.fail_after(self.deadline):
                await self.app(scope, receive, send_before_deadline)
        except TimeoutError:
            if not started:
                await JSONResponse({"error": "request_deadline"}, status_code=504)(
                    scope, receive, send
                )
            else:
                # A response already started cannot acquire a new HTTP status.
                # Let the server close this failed exchange; no success is synthesized.
                raise
        finally:
            self.active -= 1


class AuthenticatedAdmission:
    """Use verified issuer and subject for reader quotas, independent of client ID."""

    def __init__(self, app: ASGIApp, *, slots: WorkSlots) -> None:
        self.app, self.slots = app, slots

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        user = scope.get("user")
        if not isinstance(user, AuthenticatedUser):
            await self.app(scope, receive, send)
            return
        token = user.access_token
        issuer = (token.claims or {}).get("iss")
        if not isinstance(issuer, str) or not issuer or not token.subject:
            await JSONResponse({"error": "invalid_principal"}, status_code=401)(
                scope, receive, send
            )
            return
        try:
            with self.slots.reserve((issuer, token.subject)):
                await self.app(scope, receive, send)
        except Busy:
            await JSONResponse({"error": "server_busy"}, status_code=503)(scope, receive, send)
