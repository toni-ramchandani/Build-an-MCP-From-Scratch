from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any, cast

import anyio
import httpx2
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from mcp.server.auth.provider import AccessToken

from .security_config import SecuritySettings

logger = logging.getLogger(__name__)


class KeyServiceUnavailable(Exception):
    """No usable key set is available within the configured freshness policy."""


class JwtVerifier:
    """One issuer, RS256, at+jwt, exact resource and approved client identities.

    The caller owns the HTTP client. No token or verified-result cache is kept.
    """

    def __init__(
        self,
        settings: SecuritySettings,
        client: httpx2.AsyncClient,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.client = client
        self.clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fresh_until = 0.0
        self._refresh_after = 0.0
        self._lock = anyio.Lock()

    async def _key(self, kid: str) -> jwt.PyJWK | None:
        async with self._lock:
            now = self.clock()
            if now < self._fresh_until and kid in self._keys:
                return self._keys[kid]
            if now < self._refresh_after:
                if now >= self._fresh_until:
                    raise KeyServiceUnavailable()
                return None
            self._refresh_after = now + self.settings.jwks_refresh_seconds
            try:
                with anyio.fail_after(3):
                    async with self.client.stream("GET", str(self.settings.jwks_url)) as response:
                        response.raise_for_status()
                        if response.headers.get("content-encoding", "identity") != "identity":
                            raise ValueError("compressed key response")
                        if response.status_code != 200:
                            raise ValueError("unexpected key response")
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(data) + len(chunk) > 65_536:
                                raise ValueError("key response too large")
                            data.extend(chunk)
                    keys = self._parse_keys(json.loads(data))
            except (httpx2.HTTPError, TimeoutError, ValueError, jwt.PyJWTError) as exc:
                logger.warning("verification_dependency_unavailable")
                raise KeyServiceUnavailable() from exc
            self._keys = keys
            self._fresh_until = self.clock() + self.settings.jwks_cache_seconds
            return keys.get(kid)

    @staticmethod
    def _parse_keys(document: Any) -> dict[str, jwt.PyJWK]:
        if not isinstance(document, dict):
            raise ValueError("invalid key document")
        document = cast(dict[str, Any], document)
        value = document.get("keys")
        if not isinstance(value, list):
            raise ValueError("invalid key document")
        raw_keys = cast(list[Any], value)
        if not 1 <= len(raw_keys) <= 8:
            raise ValueError("invalid key count")
        keys: dict[str, jwt.PyJWK] = {}
        for item in raw_keys:
            if not isinstance(item, dict):
                raise ValueError("invalid key")
            item = cast(dict[str, Any], item)
            kid = item.get("kid")
            if not isinstance(kid, str) or not 1 <= len(kid) <= 64 or kid in keys:
                raise ValueError("invalid key identity")
            if (
                item.get("kty") != "RSA"
                or item.get("use", "sig") != "sig"
                or item.get("alg", "RS256") != "RS256"
                or item.get("key_ops", ["verify"]) != ["verify"]
                or any(name in item for name in ("d", "p", "q", "dp", "dq", "qi", "oth"))
            ):
                raise ValueError("unsupported signing key")
            key = jwt.PyJWK(item, algorithm="RS256")
            if not isinstance(key.key, RSAPublicKey) or not 2048 <= key.key.key_size <= 4096:
                raise ValueError("unsupported RSA size")
            keys[kid] = key
        return keys

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            if not token.isascii() or len(token) > 16_384:
                return None
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or header.get("typ") != "at+jwt"
                or not isinstance(kid, str)
                or not 1 <= len(kid) <= 64
                or any(name in header for name in ("jku", "jwk", "x5u", "crit"))
            ):
                return None
            key = await self._key(kid)
            if key is None:
                return None
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=str(self.settings.auth_issuer_url),
                audience=str(self.settings.auth_resource_url),
                options={
                    "require": ["iss", "sub", "aud", "exp", "iat", "client_id", "scope"],
                    "strict_aud": True,
                },
                leeway=0,
            )
            if any(type(claims[name]) is not int for name in ("iat", "exp")):
                return None
            if "nbf" in claims and type(claims["nbf"]) is not int:
                return None
            lifetime = claims["exp"] - claims["iat"]
            if not 0 < lifetime <= self.settings.max_token_lifetime_seconds:
                return None
            subject, client_id, scope = claims["sub"], claims["client_id"], claims["scope"]
            if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
                return None
            if not isinstance(client_id, str) or client_id not in self.settings.allowed_client_ids:
                return None
            if not isinstance(scope, str) or len(scope) > 1024:
                return None
            scopes = scope.split(" ")
            if not scopes or any(
                not s
                or not s.isascii()
                or any(ord(c) < 33 or ord(c) > 126 or c in '\\"' for c in s)
                for s in scopes
            ):
                return None
            return AccessToken(
                token=token,
                client_id=client_id,
                subject=subject,
                scopes=scopes,
                expires_at=claims["exp"],
                resource=str(self.settings.auth_resource_url),
                claims={"iss": claims["iss"]},
            )
        except KeyServiceUnavailable:
            return None
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError):
            return None
