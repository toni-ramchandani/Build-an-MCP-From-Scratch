# Chapter 7 live authentication lab

This lab selects Auth0 and a pre-registered Native application. The client in
`examples/ch07/live_auth.py` performs a browser authorization-code exchange with
S256 PKCE, checks callback state and issuer, and calls the same secured MCP
application over a real loopback connection. It keeps tokens in memory and
writes only a sanitized observation record. It does not implement refresh or
general-purpose OAuth discovery across arbitrary issuers.

The lab is implemented and has deterministic security checks. A successful
external run is established only when you execute it with your tenant and
complete the browser login. No successful external run is bundled or implied.

## Prepare the tenant

Use a development tenant dedicated to the exercise. Auth0's documented
configuration supports this chapter's deliberately narrow token contract.

1. Under **Applications > APIs**, create an API named **Chapter 7 workspace**.
   Set its Identifier to `https://mcp.example.com/mcp`, its signing algorithm to
   **RS256**, its access-token profile to **RFC 9068** and its maximum access
   token lifetime to **600 seconds**. The profile's Management API dialect is
   `rfc9068_profile`; use the API's profile setting rather than a tenant-wide
   change when available. The identifier is registered audience identity; this
   loopback lab does not require that example hostname to be deployed.
2. Add API permissions `workspace:read` and `workspace:probe`. The second is a
   harmless test permission with no MCP operation attached to it. Enable RBAC
   so a user receives only granted API permissions. Leave the optional
   permissions claim disabled; this application authorizes from `scope`.
3. Create a **Chapter 7 reader** role granting `workspace:read` on this API.
   Create a separate **Chapter 7 probe** role granting only `workspace:probe`.
   Assign these roles to two separate synthetic test users respectively.
   Enable a login connection for those users. Keep passwords in the issuer's
   login flow, not in repository files or command arguments. Disable public
   self-registration for this exercise's database connection.
4. Under **Applications > Applications**, create a **Native** application named
   **Chapter 7 local reader**. Enable the Authorization Code grant. Configure
   token-endpoint authentication as **None**. Register exactly
   `http://127.0.0.1:8765/callback` as its Allowed Callback URL, with no wildcard.
   Enable the test-users' connection for this application. If your API's access
   policy requires explicitly authorizing an application for user access,
   authorize this application. Keep client-credentials/password grants disabled.
5. Under **Settings > Advanced**, enable **Resource Parameter Compatibility
   Profile** and **Include Issuer in Authorization Responses**. The client sends
   `resource` in both authorization and token requests and requires exact `iss`
   equality before exchanging the code.
6. Copy the tenant issuer, including its trailing slash, and the Native
   application's public Client ID. For example, an issuer has the form
   `https://YOUR-TENANT.REGION.auth0.com/`. Do not copy a client secret. Use one
   issuer domain consistently rather than mixing its canonical and custom domains.

Do not request `openid`, `profile`, `email` or `offline_access` in this lab.
The requested scope is exactly `workspace:read` for the positive control.
OIDC user-info scopes can introduce an additional audience; the application
requires one exact audience string and does not accept a multi-audience token.
Do not relax the verifier to make an incompatible token pass.

## Install and verify the checkout

Use a committed checkout with no uncommitted source changes. The client refuses
a dirty checkout and checks that the source revision and lock digest remain
unchanged throughout the run. Evidence under `artifacts/` is ignored by Git.
From the repository root in Windows PowerShell:

```powershell
uv --version
uv sync --locked --extra dev
uv run --frozen --extra dev python -m pytest -q tests/security/test_live_auth_client.py
uv run --frozen --extra dev python scripts/verify.py
```

The first command must report `uv 0.11.33`. If another version is installed,
the project guard rejects it; select the pinned launcher, for example
`uvx --from uv==0.11.33 uv sync --locked --extra dev`, and use that same launcher
in place of `uv` for subsequent commands. The PowerShell server script invokes
`uv`, so run it where `uv --version` reports the project pin.

## Start the secured application

Stop any earlier process listening on port 8000. In Terminal 1, replace the two
public placeholders and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\examples\ch07\start_secure.ps1 -Issuer "https://YOUR-TENANT.REGION.auth0.com/" -ClientId "YOUR-NATIVE-CLIENT-ID"
```

This bypass applies only to the child PowerShell process. The script creates
the synthetic corpus with its approval record outside the root, sets the
explicit read-only security settings, and starts `build-an-mcp-server-secure`.
It selects the Auth0 tenant's `/.well-known/jwks.json` endpoint. Authentication
is enabled explicitly, overriding Appendix A's development value. GitHub,
browser and mutation remain disabled. Leave this terminal running.

## Perform a real login and read

In Terminal 2 at the same repository root:

```powershell
uv run --frozen python examples/ch07/live_auth.py --issuer "https://YOUR-TENANT.REGION.auth0.com/" --client-id "YOUR-NATIVE-CLIENT-ID" --evidence artifacts/ch07/live-read.json
```

Sign in as the synthetic reader user and approve access if the issuer asks.
The callback listener binds only to `127.0.0.1:8765`; the browser returns there.
The client does not print the authorization code or access token. It requests
only `workspace:read`, obtains a token for the registered resource and verifies
the read-only MCP tool surface plus the exact prepared canary bytes and digest.
It also checks that a malformed token receives HTTP 401. On success, the client
prints `live_auth_passed: sanitized evidence saved` and exits 0.

The evidence file records the time, issuer/client/resource, source revision,
lock digest, SDK/protocol, PKCE and callback checks, and observed read metadata.
It contains no bearer token, authorization code, code verifier, password,
private key, subject identifier or document body. Existing evidence files are
not overwritten; use a new filename for another attempt.

The public resource identity differs from the loopback transport address.
For this explicit lab mapping, the client first verifies the challenge's exact
public metadata URL, fetches that path from the configured backend, and checks
the resource and issuer against the operator's inputs. It does not follow an
arbitrary metadata host. It then obtains issuer metadata over verified HTTPS
and pins authorization, token and key endpoints to that issuer origin. This
selected setup does not establish public endpoint discovery or edge security.

## Record representative refusals

Run the missing-read-scope case and log in as the separate probe user:

```powershell
uv run --frozen python examples/ch07/live_auth.py --issuer "https://YOUR-TENANT.REGION.auth0.com/" --client-id "YOUR-NATIVE-CLIENT-ID" --scope workspace:probe --expect-status 403 --evidence artifacts/ch07/live-scope-refusal.json
```

For wrong-resource rejection, first register a second synthetic API whose
Identifier is `https://mcp.example.com/other`. Give it the same RFC 9068/RS256/
600-second settings and a `workspace:read` permission granted to the reader
role. Authorize the same Native application for this API if its access policy
requires it. Keep the MCP server's resource setting unchanged. Then run:

```powershell
uv run --frozen python examples/ch07/live_auth.py --issuer "https://YOUR-TENANT.REGION.auth0.com/" --client-id "YOUR-NATIVE-CLIENT-ID" --token-resource https://mcp.example.com/other --expect-status 401 --evidence artifacts/ch07/live-resource-refusal.json
```

Sign in as the reader user. The issuer issues for the second API; the original
MCP application must refuse that token with HTTP 401. A 401 caused by an
unconfigured issuer/API is not a successful wrong-resource test: the helper
must complete the token exchange before probing the MCP application.

These network probes assert the HTTP refusal and absence of canary content or
credential echo. They do not instrument adapter entry. Keep the deterministic
no-adapter-entry assertions as separate evidence. Expiry, key rotation,
dependency failures and worker accounting retain their existing controlled
tests; additional live cases must be recorded when run.

## Finish and accept the candidate

Check all three new JSON records and the deterministic verifier result against
the same committed source, lock and read-only candidate. Restore the read-only
configuration after any separate mutation lab. Stop Terminal 1 with Ctrl+C;
the server script removes only its generated corpus directory and restores the
settings it changed in that child process. Do not delete the retained evidence.

The live-authentication checkpoint closes when the real challenge/metadata,
issuer login, code/PKCE/resource
exchange, authenticated MCP read and representative refusals have been observed
and the reader procedure reproduces them. An unrun helper or passing mocked
client test does not close that gate. Actual service-account confinement,
public HTTPS/proxy policy, egress, workload and recovery remain Chapter 8 work.

## Troubleshooting

| Outcome | Check |
| --- | --- |
| `callback_issuer` or callback rejected in browser | Enable Include Issuer in Authorization Responses; use the exact issuer with its trailing slash. |
| Token exchange fails | Native app, Authorization Code enabled, token-endpoint auth None, exact callback, correct resource API and resource compatibility toggle. |
| Positive read receives 401 | RFC 9068 profile, RS256, 600-second lifetime, one audience, correct client ID, issuer/JWKS identity and locally correct clock. |
| Positive read receives 403 | Reader role, requested `workspace:read`, RBAC permissions and API application-access policy. |
| Scope case succeeds unexpectedly | Use the separate probe user with no read permission; inspect granted scope locally without sharing the raw token. |
| Port 8765 unavailable | Stop the previous callback process; do not broaden the redirect wildcard or change ports without updating registration. |
| `evidence_exists` | Preserve that record and choose another output filename. |

The Python client and server controls can be checked on Linux. The PowerShell
launch procedure needs its own execution on your Windows machine; no Windows
run is implied by the deterministic Linux checks.

## Primary references

- [MCP 2026-07-28 authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [Auth0 access-token profiles](https://auth0.com/docs/secure/tokens/access-tokens/access-token-profiles)
- [Configure the API token profile](https://auth0.com/docs/get-started/apis/configure-access-token-profile)
- [Auth0 resource and response-issuer toggles](https://auth0.com/ai/docs/mcp/guides/resource-param-compatibility-profile)
- [Auth0 PKCE flow and Native client registration](https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-pkce/add-login-using-the-authorization-code-flow-with-pkce)
- [Auth0 access-token lifetime](https://auth0.com/docs/secure/tokens/access-tokens/update-access-token-lifetime)
