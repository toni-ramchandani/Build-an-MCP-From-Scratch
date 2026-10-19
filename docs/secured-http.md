# Secured HTTP configuration

`build-an-mcp-server-secure` constructs the existing MCP application with a
real JWT verifier, a validated corpus, and bounded admission. It binds to
loopback and does not load an ambient `.env` file. The default `read-only`
profile disables mutation, GitHub, and browser capabilities.

The locked construction uses MCP 2.0.0, protocol revision 2026-07-28,
PyJWT 2.13.0, and httpx2 2.10.0. Run the locked verification environment before
changing these dependencies.

| Required environment input | Meaning |
| --- | --- |
| `MCP_HTTP_REQUIRE_AUTH` | Set `true`; override the earlier development value |
| `MCP_SECURITY_PROFILE` | Set `read-only` |
| `MCP_ENABLE_MUTATION`, `MCP_ENABLE_GITHUB`, `MCP_ENABLE_BROWSER` | Set all three to `false` |
| `MCP_AUTH_REQUIRED_SCOPES` | Set `workspace:read` |
| `MCP_WORKSPACE_ROOTS` | One operator-controlled corpus directory |
| `MCP_CORPUS_APPROVAL_FILE` | Absolute approval JSON path outside the corpus |
| `MCP_AUTH_ISSUER_URL` | Trusted issuer identity after settings parsing |
| `MCP_AUTH_RESOURCE_URL` | Intended resource; distinct from backend address |
| `MCP_JWKS_URL` | Trusted issuer key endpoint |
| `MCP_ALLOWED_CLIENT_IDS` | Comma-separated approved client identifiers |

Security URLs require HTTPS without credentials, query, or fragment. The base
scope is `workspace:read`. Tokens require RS256, `typ=at+jwt`, a known key
identifier, exact issuer/single audience, integer issue/expiry times, subject,
approved `client_id`, and a space-separated scope string. Maximum lifetime
defaults to 900 seconds, with zero clock tolerance. This acceptance contract
requires actual issuer/client compatibility verification. The
[selected Auth0 lab](ch07-live-auth.md) supplies the pre-registration, PKCE,
callback and observation procedure; its external run remains separate evidence.

Key delivery permits no redirects, a 64 KiB uncompressed document, and at most
eight supported RSA public keys. Network timeout is two seconds; retrieval has
a three-second overall cooperative deadline. Default key freshness is 60
seconds and refresh spacing is five seconds. No stale-key extension or
individual-token revocation is implemented. Fresh cached keys remain usable
until their deadline.

Default work limits are 16 active HTTP requests, four authenticated requests
per process, and one per verified `(issuer, subject)`. There is no waiting
queue. A five-second request deadline does not forcibly terminate synchronous
workers; accounting stays occupied until they finish. These are application
starting points, not measured throughput or distributed quotas.

Approval JSON contains exactly `generation`, `files`, and `excluded`.
`files` maps approved relative names to SHA-256 digests. Missing/extra files,
invalid UTF-8, symlinks, unexpected directories, and exceeded bounds reject the
complete candidate. Approval is an operator decision, not secret classification.
The operator prevents changes during validation and serving.

Prepare synthetic data with `uv run --frozen python examples/ch07/prepare_corpus.py`.
The output identifies a new directory, corpus root, approval file, and generation.
It does not approve an existing directory. Remove the generated directory when
no process uses it. After supplying all inputs, launch with:

```text
uv run --frozen build-an-mcp-server-secure
```

The diagnostic client accepts `MCP_DIAGNOSTIC_ACCESS_TOKEN` for HTTP only. It
does not implement OAuth login or refresh. Obtain a short-lived token through
the approved client/issuer flow; never put it in arguments or repository files.
In a second terminal, with that variable supplied through the approved secret
input mechanism, run the controlled loopback read:

```text
uv run --frozen python scripts/diagnostic_client.py --transport http --url http://127.0.0.1:8000/mcp --read canary.txt
```

Use the final HTTPS endpoint instead when the selected integration requires it.
The diagnostic refuses credentialed redirects and uses a 30-second
connect/write/pool timeout and a 300-second read-inactivity timeout.
These timeouts are not one end-to-end operation deadline.

The separate `mutation-lab` profile requires `MCP_ENABLE_MUTATION=true`,
`MCP_MUTATION_LAB_CONFIRMED=true`, a disposable root, and write scope. It skips
immutable corpus approval for this exercise. Return to `read-only` before
deployment; a successful lab does not approve production mutation.

`scripts/verify.py` covers deterministic controls and installed-package probes.
The positive secure-package probe uses controlled key delivery and ASGI
transport. Live issuer/client interaction, an authenticated console-process
journey, actual service isolation, external HTTPS, egress, supervisor behavior,
and operating measurements remain distinct acceptance work.
