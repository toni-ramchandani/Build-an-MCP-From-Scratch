from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.shared.inbound import decode_header_value
from starlette.types import ASGIApp, Receive, Scope, Send

OperationKey = tuple[str, str | None]


class HttpScopePolicy:
    """Apply application-owned scope policy before an MCP HTTP request is decoded."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        base_scopes: Sequence[str],
        operation_scopes: Mapping[OperationKey, Sequence[str]],
        resource_metadata_url: str,
    ) -> None:
        self.app = app
        self.base_scopes = tuple(base_scopes)
        self.operation_scopes = {
            operation: tuple(scopes) for operation, scopes in operation_scopes.items()
        }
        self.resource_metadata_url = resource_metadata_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {name.lower(): value for name, value in scope.get("headers", [])}
        method = _decode_header(headers.get(b"mcp-method")) or ""
        name = _decode_header(headers.get(b"mcp-name"))
        operation_key: OperationKey = (method, name)
        required_list: list[str] = []
        for required_scope in self.base_scopes + self.operation_scopes.get(operation_key, ()):
            if required_scope not in required_list:
                required_list.append(required_scope)
        required = tuple(required_list)

        user = scope.get("user")
        if not isinstance(user, AuthenticatedUser):
            await self._send_error(
                send,
                status_code=401,
                error="invalid_token",
                description="Authentication required",
                required_scopes=required,
            )
            return

        if any(required_scope not in user.scopes for required_scope in required):
            await self._send_error(
                send,
                status_code=403,
                error="insufficient_scope",
                description="The access token does not grant this operation",
                required_scopes=required,
            )
            return

        await self.app(scope, receive, send)

    async def _send_error(
        self,
        send: Send,
        *,
        status_code: int,
        error: str,
        description: str,
        required_scopes: Sequence[str],
    ) -> None:
        challenge = [f"error={json.dumps(error)}", f"error_description={json.dumps(description)}"]
        if required_scopes:
            challenge.append(f"scope={json.dumps(' '.join(required_scopes))}")
        challenge.append(f"resource_metadata={json.dumps(self.resource_metadata_url)}")

        body = json.dumps({"error": error, "error_description": description}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", f"Bearer {', '.join(challenge)}".encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _decode_header(value: bytes | None) -> str | None:
    if value is None:
        return None
    try:
        rendered = value.decode("ascii")
    except UnicodeDecodeError:
        return None
    return decode_header_value(rendered)
