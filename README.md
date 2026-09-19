# Build an MCP from Scratch

The executable companion repository for the book *Build an MCP from Scratch*.
It contains one evolving Model Context Protocol (MCP) server — not a collection
of unrelated demo servers. The active implementation lives under
`src/build_an_mcp_server/`; `examples/` holds only narrow programs that each
expose a single mechanism clearly.

The main protocol path is the [MCP specification revision
2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28), and
`uv.lock` pins the official Python SDK to
[`mcp==2.0.0`](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0).

## What the server exposes

The default surface is deliberately small:

- `list_workspace_directory` — bounded directory inspection inside an opaque,
  explicitly configured root
- `read_workspace_text` — bounded UTF-8 reads with continuation metadata
- `workspace://manifest` — the public root identifiers and result budgets
- `review_workspace_file` — one prompt that depends on the workspace tools

By default there is no write tool, GitHub access, browser, web search, or
implicit home/repository access. Optional surfaces are registered only when
their policy is explicitly enabled (see [Optional capabilities](#optional-capabilities)).

The public protocol surface uses opaque identifiers (`root-1`, `root-2`, …)
and never exposes absolute filesystem paths. For protocol conformance, an
unknown `tools/call` name returns a top-level JSON-RPC `-32602`
invalid-parameters error over both stdio and Streamable HTTP.

## Quick start

```bash
uv sync --locked --extra dev
MCP_WORKSPACE_ROOTS="$PWD" uv run build-an-mcp-server
```

On Windows PowerShell:

```powershell
uv sync --locked --extra dev
$env:MCP_WORKSPACE_ROOTS = (Get-Location).Path
uv run build-an-mcp-server
```

## Requirements

- Python 3.10–3.14 (declared in the project metadata)
- `uv==0.11.33` — verify with `uv --version`
- Node.js 22.19 or later — only for the optional MCP Inspector
- Chromium via Playwright — only for the optional browser capability

Install the locked development environment:

```bash
uv sync --locked --extra dev
```

A pip environment can install the project, but pip does not consume `uv.lock`,
so it is a fallback rather than the reproducible path:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Configure an explicit workspace

Copy `.env.example` to `.env`, then set `MCP_WORKSPACE_ROOTS` to one or more
existing absolute directories. Multiple roots use the platform path separator
(`:` on POSIX, `;` on Windows). The public surface exposes `root-1`, `root-2`,
and so on — not those absolute paths.

## Run stdio

For one shell invocation on macOS or Linux:

```bash
MCP_WORKSPACE_ROOTS="$PWD" uv run build-an-mcp-server
```

On Windows PowerShell:

```powershell
$env:MCP_WORKSPACE_ROOTS = (Get-Location).Path
uv run build-an-mcp-server
```

The stdio entry point writes protocol messages only to stdout. Diagnostics
belong on stderr.

## Run Streamable HTTP

```bash
MCP_WORKSPACE_ROOTS="$PWD" uv run build-an-mcp-server-http
```

The local endpoint is `http://127.0.0.1:8000/mcp`. This command is a
loopback-only development path. Non-loopback settings fail closed even when
authentication is configured: remote hosting needs an explicit Origin/Host,
proxy, TLS, and authorization policy that this repository does not provide.
Authenticated HTTP additionally requires an application-supplied SDK
`TokenVerifier`; this repository does not ship an authorization server or a
static production token scheme.

## Run Inspector

Use the pinned Inspector (Node.js 22.19 or later) against the narrow minimal
example:

```bash
npx --yes @modelcontextprotocol/inspector@2.2.0 \
  uv run python examples/ch02/minimal_add_server.py
```

Alternatively, adapt `scripts/inspector-stdio.mcp.json.example` with an explicit
root. Avoid the SDK's `mcp dev` wrapper in a shared command: SDK v2.0.0 invokes
an unversioned Inspector package.

You can also drive the first-class SDK v2 client directly:

```bash
MCP_WORKSPACE_ROOTS="$PWD" uv run python scripts/diagnostic_client.py \
  --transport stdio --read README.md
```

Start the HTTP server in another terminal, then select `--transport http`. The
raw stdio trace sends one `tools/list` request directly over stdio:

```bash
uv run python -m examples.ch03.raw_stdio_trace --root "$PWD"
```

## Verify the repository

The deterministic local and CI check is:

```bash
uv run python scripts/verify.py
```

It checks formatting, lint, strict static types, unit and domain behavior,
in-process MCP contracts, real stdio and HTTP boundaries, security-negative
cases, package construction, and both installed console commands from a separate
environment outside the checkout. See [`docs/verification.md`](docs/verification.md)
for details and for what is and is not proven.

Live GitHub and browser tests are marked `integration`; both require
`RUN_LIVE_INTEGRATIONS=1` plus their feature-specific configuration. They do not
run merely because a token or browser happens to exist on a developer machine.

## Optional capabilities

Optional provider packages are separate from the core:

```bash
uv sync --locked --extra dev --extra github
uv sync --locked --extra dev --extra browser
uv run playwright install chromium
```

Each optional surface is disabled by default and appears in discovery only when
its policy is enabled:

- **GitHub** — a two-tool, read-only module. Enabling it requires a token and an
  explicit repository allowlist.
- **Workspace write** — one bounded write with expected-digest checking, atomic
  replacement, and serialization within a single `WorkspaceAdapter`.
- **Browser** — isolated browser-page handles with bounded text and
  application-owned cleanup. Enabling it requires an exact-origin allowlist.

Over HTTP, GitHub, mutation, and browser surfaces require authenticated HTTP;
a read-only provider tool is still sensitive when it can spend or disclose data
through a server-held credential. When authenticated HTTP exposes the write
tool, that operation requires the `workspace:write` scope; an under-scoped
request receives `403 Forbidden` with an `insufficient_scope` challenge.

## Security boundaries

This repository does not claim complete production security. Known boundaries:

- The workspace checks are application policy, not an operating-system sandbox.
  They assume other processes cannot maliciously replace checked paths or parent
  directories between validation and I/O. A local writer with that access can
  race the path checks. Digest checking and replacement are serialized only
  within one `WorkspaceAdapter`; external editors and other server processes do
  not share its lock. Use a trusted workspace.
- The browser origin filter is not an SSRF or network-egress sandbox. Redirects,
  DNS resolution, WebSockets, subresources, and reachable destinations need a
  separately designed network policy. URL, title, and text are each bounded by
  the configured browser-text budget with explicit truncation flags. Handle
  expiry is checked during subsequent operations, not by a background timer.
  Cleanup is cooperative and best effort; a failed browser shutdown can require
  process termination.
- HTTP is loopback-only and fails closed on non-loopback binds. Rate limiting,
  audit logging, consent, and remote-deployment authorization are out of scope.

## Repository layout

```text
.
├── .github/workflows/ci.yml
├── .env.example
├── docs/
│   ├── repository-architecture.md
│   └── verification.md
├── examples/
│   ├── ch02/minimal_add_server.py
│   └── ch03/raw_stdio_trace.py
├── scripts/
│   ├── diagnostic_client.py
│   ├── inspector-stdio.mcp.json.example
│   ├── verify.py
│   └── verify_installed.py
├── src/build_an_mcp_server/
│   ├── config.py
│   ├── factory.py
│   ├── http_policy.py
│   ├── workspace_capabilities.py
│   ├── workspace.py
│   ├── github_capabilities.py
│   ├── github_adapter.py
│   ├── browser_capabilities.py
│   ├── browser_runtime.py
│   ├── models.py
│   ├── runtime_state.py
│   ├── server.py
│   └── http_server.py
└── tests/
    ├── unit/
    ├── contract/
    ├── runtime/
    ├── security/
    └── integration/
```
