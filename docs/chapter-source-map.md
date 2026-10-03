# Chapter source map: Chapters 1–6

This map connects the manuscript to the complete reference checkout. Each
chapter develops or inspects part of the same application. The checkout already
contains the implementation, test harness, and supporting code used throughout
these chapters.

Source baseline for this map: `7ac87284656691c83d6b99d334132a3f661863d5`.
The paths and listing numbers below correspond to the reviewed Chapters 1–6.
When the manuscript or source changes, reconcile this map with both.

## How to work through the book

1. Complete Appendix A and open the repository root in your editor. Install the
   locked development environment with `uv sync --locked --extra dev`.
2. Run `uv run --frozen python scripts/verify.py` once before editing. Keep the
   result as your baseline; a pre-existing environment failure should not be
   mistaken for a problem introduced by a chapter exercise.
3. Work on a local branch. Open the file named in a listing caption before
   changing code. Reconstruct the named definition in its existing location.
4. Use the caption to determine the replacement boundary. A complete file
   replaces that file; a complete function or method replaces that definition;
   a selected excerpt replaces only the matching statements. Preserve the
   surrounding imports, decorators, helpers, and definitions.
5. Run the focused checks below after a coherent change. Inspect the returned
   schemas, data, or error behavior described by the chapter, as well as the
   test result. Compare your change with `git diff`.
6. Run the full verifier at the runtime-and-package checkpoint.

The chapter listings are not files to concatenate. Workspace methods belong
inside `WorkspaceAdapter`; nested tool, resource, and prompt definitions belong
inside their registration function. Preserve their indentation and ownership.

A passing test on the untouched reference checkout establishes a working
baseline. It does not establish that you have completed the construction
exercise. To follow the build, reconstruct the selected definition, explain its
boundary, and verify the resulting behavior.

The focused commands run from the repository root after the locked development
environment has been installed. They use repository-owned fixtures. Manual
client and host exercises use the dedicated workspace and configuration
described in Appendix A and the manuscript.

## Chapter 1 — Responsibilities and boundaries

**Work in this chapter:** Trace an allowed workspace read and a refused request.
Identify what the host, client, server, and filesystem each control.

**Supplied by the checkout:** The Python package, dependency lock, application,
and verification scripts. This conceptual chapter does not require replacing
a server definition.

**Completion evidence:** Explain where workspace policy is enforced and why a
refused request must not return file content. Successful environment setup is
separate evidence from understanding those responsibilities.

For the component map, see [repository architecture](repository-architecture.md).

## Chapter 2 — The workspace interface

| Listings | Source location | Work developed |
| --- | --- | --- |
| 2.1 | `examples/ch02/minimal_add_server.py` | One complete typed-tool example |
| 2.2 | `src/build_an_mcp_server/models.py` | Public workspace result models |
| 2.3–2.7 | `src/build_an_mcp_server/workspace.py` | Root map, adapter construction, path resolution, bounded reads, UTF-8 handling, and directory pagination |
| 2.8–2.10 | `src/build_an_mcp_server/workspace_capabilities.py` | Read-only tools, manifest resource, and review prompt within `register_read_only_workspace` |

**Supplied surrounding code:** Imports, adjacent private helpers, settings,
server factory, entry points, and test fixtures. Preserve optional write
definitions already present in the module; they are not required for this
read-only construction exercise.

**Focused checks:**

```text
uv run --frozen python -m pytest -q tests/contract/test_examples.py -k chapter_2
uv run --frozen python -m pytest -q tests/unit/test_workspace.py
uv run --frozen python -m pytest -q tests/contract/test_surface.py
uv run --frozen python -m pytest -q tests/unit/test_review_regressions.py -k "utf8 or metadata"
```

**Completion evidence:** The minimal tool returns the structured result
`{"result": 42}` for 20 and 22. The workspace surface advertises the intended
tools, resource, and prompt; reads and directory pages remain bounded.
Invalid UTF-8 at EOF and filesystem metadata failures produce controlled
failures. The prompt instructs the host how to treat retrieved content; it
does not enforce host behavior.

## Chapter 3 — Transport behavior

| Listings | Source location | Work developed or inspected |
| --- | --- | --- |
| 3.1 | `examples/ch03/raw_stdio_trace.py` | One raw stdio request and response |
| 3.2–3.3 | `scripts/diagnostic_client.py` | SDK client setup for stdio and Streamable HTTP |
| 3.4 | `scripts/diagnostic_client.py`, `_run()` | Discovery and the optional bounded read through either transport |

**Supplied surrounding code:** The assembled server, argument parser,
environment helpers, HTTP entry point, and protocol guard. Preserve those
definitions when reconstructing the selected client code.

**Focused checks:**

```text
uv run --frozen python -m pytest -q tests/contract/test_examples.py -k chapter_3
uv run --frozen python -m pytest -q tests/runtime/test_request_errors.py
```

**Completion evidence:** The raw trace contains the expected request and tool
discovery response. In the manuscript's manual comparison, the stdio client
owns a child process while the HTTP client connects to a separately running
service. Both inspect the same application surface. The automated checks
above cover the raw example and request-error behavior; they do not replace
performing and interpreting that two-transport comparison.

## Chapter 4 — Configuration, composition, and resource ownership

| Listings | Source location | Work developed |
| --- | --- | --- |
| 4.1–4.2 | `src/build_an_mcp_server/config.py` | Selected `ServerSettings` fields and policy validation |
| 4.3 | `src/build_an_mcp_server/factory.py` | Selected server-construction and registration statements |
| 4.4 | `src/build_an_mcp_server/server.py`, `main()` | Thin stdio entry point |
| 4.5 | `src/build_an_mcp_server/github_capabilities.py` | Provider interface and tool registration |
| 4.6 | `src/build_an_mcp_server/github_adapter.py` | Provider request and normalization boundary |
| 4.7–4.8 | `src/build_an_mcp_server/runtime_state.py` | Lifespan construction and registered cleanup |

**Supplied surrounding code:** Existing workspace registrations, remaining
settings and factory statements, provider construction, and the optional
browser and mutation implementations. The complete factory includes policy
for these optional surfaces even when the read-only workspace exercise leaves
them disabled.

**Focused checks:**

```text
uv run --frozen python -m pytest -q tests/unit/test_config.py tests/unit/test_github_adapter.py tests/unit/test_runtime_state.py
uv run --frozen python -m pytest -q tests/contract/test_policy_surface.py tests/contract/test_discovery_order.py
uv run --frozen python -m pytest -q tests/unit/test_review_regressions.py -k cleanup
```

**Completion evidence:** Invalid settings are rejected, enabled policy shapes
discovery, provider behavior is tested through controlled substitutes, and
registered cleanup runs if later resource acquisition fails. These checks do
not establish live GitHub connectivity.

## Chapter 5 — In-process contracts

| Listings | Source location | Work developed |
| --- | --- | --- |
| 5.1 | `tests/helpers.py` | Constructor-only test settings |
| 5.2 | `tests/conftest.py` | Reusable in-process fixtures |
| 5.3–5.4 | `tests/contract/test_surface.py` | Discovery and structured-result assertions |
| 5.5 | `tests/contract/test_policy_surface.py` | Policy-shaped discovery |
| 5.6 | `tests/contract/test_optional_surfaces.py` | Caller-safe provider failure and non-disclosure |
| 5.7 | `.github/workflows/ci.yml` | Deterministic verification in CI |

**Supplied surrounding code:** The application, remaining fixture definitions,
complete test parametrization, and verifier orchestration. Selected assertion
excerpts belong inside the named existing tests.

**Focused checks:**

```text
uv run --frozen python -m pytest -q tests/unit/test_test_settings.py
uv run --frozen python -m pytest -q tests/contract
```

**Completion evidence:** Tests control settings and workspace data, freeze the
advertised surface, validate structured results against schemas, and check
policy-dependent discovery and controlled failures. The contract directory
also contains example and host-template checks; it is broader than the
selected Chapter 5 listings. In-process assertions alone do not prove that
an installed server starts or works through a real transport.

## Chapter 6 — Runtime, clients, and installed packages

| Listings or exercise | Source location | Work developed or inspected |
| --- | --- | --- |
| 6.1–6.3 | `tests/runtime/test_stdio.py` | SDK process crossing, stdout checking, and normal EOF |
| 6.4–6.6 | `tests/runtime/test_http.py` | Independent HTTP process and routing-metadata failures |
| 6.7 | `scripts/inspector-stdio.mcp.json.example` | Complete modern-era Inspector template |
| Diagnostic comparison | `scripts/diagnostic_client.py` | Discovery and read through both transports; controlled diagnostics |
| Host acceptance | `scripts/claude-desktop.mcp.json.example` | Host configuration template |
| Package checkpoint | `scripts/verify.py`, `scripts/verify_installed.py` | Full verification and installed-command proof |

**Supplied surrounding code:** The assembled application, existing contract
tests, runtime helpers, and `tests/fixtures/polluted_stdio_entry.py`.
A host configuration template requires resolved local paths before use.

**Focused checks:**

```text
uv run --frozen python -m pytest -q tests/runtime
uv run --frozen python -m pytest -q tests/unit/test_diagnostic_redaction.py tests/contract/test_claude_host_example.py
uv run --frozen python scripts/verify.py
```

The full verifier includes installed-package verification; a second invocation
of `scripts/verify_installed.py` is unnecessary when that full run succeeds.

**Completion evidence:** The real processes complete discovery and bounded
reads; stdio remains protocol-clean; invalid HTTP inputs receive the expected
rejections; a wheel built from the source distribution works outside the
checkout through both installed console commands.

Record the Inspector and desktop-host observations separately, including the
source revision, client version, protocol mode, discovered surface, and
bounded-read result. Passing template tests does not prove that a desktop host
actually launched and used the server.

## Scope of these checks

The deterministic verification route excludes the credentialed live
integration tests. Dependency installation and package building may require
network access or a prepared cache. Local HTTP proof does not establish remote
production deployment, and optional capability code in the checkout does not
mean those capabilities have been enabled or operationally accepted.

See [verification](verification.md) for the full verification boundary and
[the README](../README.md) for configuration and known limitations.

