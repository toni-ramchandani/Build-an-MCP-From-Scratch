# Repository verification

This guide explains how to reproduce the repository's deterministic checks and
what those checks do and do not prove.

## Environment

- Python 3.10–3.14 (declared in the project metadata)
- `uv==0.11.33` — verify with `uv --version`

The project pins `uv==0.11.33`; a different `uv` is rejected by the project
guard.

## Install

```bash
uv sync --locked --extra dev
```

This creates the environment from `uv.lock` with the development extras.

## Run the deterministic checks

```bash
uv run --frozen python scripts/verify.py
```

`scripts/verify.py` runs, in order:

1. Ruff format check
2. Ruff lint
3. Pyright strict type check
4. `pytest -m "not integration"` — unit, contract, runtime, and security tests
5. `scripts/verify_installed.py` — package construction and installed-command proof

You can run the test suite on its own:

```bash
uv run --frozen python -m pytest -m "not integration" -ra
```

## Package and transport verification

```bash
uv run --frozen python scripts/verify_installed.py
```

This builds the source distribution, builds the wheel from that source
distribution, installs the wheel into a separate environment using locked
dependencies, and then exercises the installed application from outside the
checkout. `build-an-mcp-server` and `build-an-mcp-server-http` perform discovery
and a bounded file read over stdio and Streamable HTTP. The secured console
command, `build-an-mcp-server-secure`, must reject incomplete configuration.
The positive secured-application read and refusal probes use ASGI transport
and controlled trusted-key delivery through `scripts/secure_package_probe.py`.
They establish installed construction and token enforcement, not a successful
external login or a positive secure-console network journey.

The separate [Chapter 7 live-authentication lab](ch07-live-auth.md) requires an
external issuer, pre-registered public client and browser login. Its results
are recorded independently; the deterministic verifier does not run that flow.

## Live integration tests

GitHub and browser tests are marked `integration` and are excluded from the
deterministic run. They execute only when `RUN_LIVE_INTEGRATIONS=1` is set
together with their feature-specific configuration (credentials, repository
allowlist, or a Chromium binary and allowed origins).

## Known limitations

- On platforms without symbolic-link support (for example, some Windows
  configurations), the symlink workspace test is skipped rather than failed.
- Continuous integration runs Python 3.10, 3.12, and 3.14 on Linux; results on
  other interpreter or OS combinations are only established when that
  environment actually runs the checks.

## What is and is not proven

Proven by the deterministic checks:

- formatting, lint, and strict static types;
- the public MCP surface, schemas, metadata, output budgets, and negative
  security paths in-process;
- real stdio and Streamable HTTP process boundaries;
- unknown-tool protocol conformance (top-level JSON-RPC `-32602`) over stdio and
  Streamable HTTP;
- package build and installed-command behavior from a clean environment.

Not proven by these checks:

- live GitHub, live browser, or a real Chromium lifecycle;
- browser network isolation beyond exact-origin filtering (no SSRF/egress
  sandbox);
- resistance to hostile external filesystem writers or cross-process write
  races;
- a complete OAuth authorization-server deployment, token issuance, or consent;
- remote (non-loopback) Streamable HTTP deployment, TLS, or proxy trust;
- deployed service-wide rate limits, durable audit logging, or bounded log-export/retention behavior.
