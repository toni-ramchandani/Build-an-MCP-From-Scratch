# Build an MCP from Scratch

This repository accompanies the book *Build an MCP from Scratch (Model Context Protocol)*. It keeps the early teaching examples runnable while also providing the Chapter 4 production-shaped runtime package used by the later chapters.

The code intentionally has two layers:

- `src/build_an_mcp_server/` is the active MCP server package after the Chapter 4 refactor.
- `examples/` and chapter snapshots preserve smaller teaching programs from earlier chapters.

The active package uses the official MCP Python SDK package, imported through `mcp.*`, including `FastMCP`, stdio execution, Streamable HTTP, prompt helpers, tool result types, and the SDK in-memory test transport.

## Capabilities in the active package

The Chapter 4 package can expose these capability groups through settings:

- Filesystem tools and resources inside configured allowed roots.
- GitHub repository tools and resources using PyGithub and `GITHUB_TOKEN`.
- Tavily web search using `TAVILY_API_KEY`.
- Browser automation through Playwright and Chromium.
- Prompt templates for recurring file and directory review workflows.

These capabilities remain MCP tools, resources, and prompts. Streamable HTTP exposes one MCP endpoint; it does not create one REST route per tool.

## Repository layout

```text
.
├── pyproject.toml
├── .env.example
├── README.md
├── src/
│   └── build_an_mcp_server/
│       ├── __init__.py
│       ├── config.py
│       ├── factory.py
│       ├── fs_utils.py
│       ├── github_utils.py
│       ├── web_search_utils.py
│       ├── browser_utils.py
│       ├── normalizers.py
│       ├── runtime_state.py
│       ├── server.py
│       └── http_server.py
├── examples/
│   ├── ch02/
│   │   ├── __init__.py
│   │   ├── minimal_add_server.py
│   │   ├── server_ch2.py
│   │   ├── fs_utils_ch2.py
│   │   ├── github_utils_ch2.py
│   │   └── browser_utils_ch2.py
│   └── ch03/
│       ├── stdio_host.py
│       ├── http_adapter.py
│       ├── transport.py
│       └── validate_and_call.py
├── scripts/
│   └── smoke_all_capabilities.py
└── tests/
    ├── test_ch02_snapshot.py
    ├── test_ch04_runtime.py
    └── test_owner_smoke_integration.py
```

## Chapter snapshots versus the active package

Chapter 2 originally builds a larger single-file `server.py`. That teaching version is preserved as `examples/ch02/server_ch2.py` with its own helper copies. It is not part of the active `src/` package.

Chapter 4 refactors the active package into smaller files:

- `config.py` loads and validates runtime settings.
- `factory.py` assembles the `FastMCP` server and registers enabled capability groups.
- `server.py` is the thin stdio entry point.
- `http_server.py` is the native Streamable HTTP entry point.
- `fs_utils.py`, `github_utils.py`, `web_search_utils.py`, and `browser_utils.py` keep adapter logic out of entry points.
- `normalizers.py` defines stable filesystem result shapes.
- `runtime_state.py` owns application runtime state and cleanup callbacks.

## Install

Using `uv`:

```bash
uv venv
uv pip install -e ".[dev,examples]"
```

Using `pip`:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,examples]"
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,examples]"
```

Install browser binaries only when you want browser capability tests:

```bash
playwright install chromium
```

## Configure

Copy the template:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
copy .env.example .env
```

Minimal local configuration:

```env
ENABLE_FILESYSTEM=true

# Use an absolute path.
# macOS/Linux example:
# FS_ALLOWED_DIRS=/Users/you/projects/Build-an-MCP-From-Scratch
# Windows example:
# FS_ALLOWED_DIRS=C:\Users\you\projects\Build-an-MCP-From-Scratch
FS_ALLOWED_DIRS=/absolute/path/to/your/project

READ_ONLY=false
ENABLE_GITHUB=false
ENABLE_WEB_SEARCH=false
ENABLE_BROWSER=false
```

Full owner-level configuration:

```env
ENABLE_FILESYSTEM=true
FS_ALLOWED_DIRS=/absolute/path/to/your/project
READ_ONLY=false

ENABLE_GITHUB=true
GITHUB_TOKEN=your_github_token

ENABLE_WEB_SEARCH=true
TAVILY_API_KEY=your_tavily_key

ENABLE_BROWSER=true
BROWSER_HEADLESS=true
BROWSER_TIMEOUT_MS=15000
```

## Run the Chapter 2 examples

Chapter 2 has two runnable examples:

- `examples/ch02/minimal_add_server.py` is the smallest tool demo used for the first `add` example.
- `examples/ch02/server_ch2.py` is the full Chapter 2 snapshot with filesystem, GitHub, browser, web-search, resource, and prompt examples.

### Minimal tool demo

The smallest Chapter 2 example registers one `add` tool and runs the server over stdio:

```bash
python -m examples.ch02.minimal_add_server
```

Use MCP Inspector for interactive testing:

```bash
npx @modelcontextprotocol/inspector python -m examples.ch02.minimal_add_server
```

### Full Chapter 2 snapshot

The full Chapter 2 snapshot uses `FS_ALLOWED_DIRS`, so set it to an absolute directory before running the server.

macOS/Linux:

```bash
FS_ALLOWED_DIRS="$(pwd)" python -m examples.ch02.server_ch2
```

Windows PowerShell:

```powershell
$env:FS_ALLOWED_DIRS = (Get-Location).Path
python -m examples.ch02.server_ch2
```

Use MCP Inspector for interactive testing.

macOS/Linux:

```bash
FS_ALLOWED_DIRS="$(pwd)" npx @modelcontextprotocol/inspector python -m examples.ch02.server_ch2
```

Windows PowerShell:

```powershell
$env:FS_ALLOWED_DIRS = (Get-Location).Path
npx @modelcontextprotocol/inspector python -m examples.ch02.server_ch2
```

Raw file execution is also supported:

```bash
FS_ALLOWED_DIRS="$(pwd)" python examples/ch02/server_ch2.py
```

## Run the Chapter 4 stdio server

```bash
python -m build_an_mcp_server.server
```

or through the console script:

```bash
build-an-mcp-server
```

Do not run `python src/build_an_mcp_server/server.py`; this is a `src/` package with relative imports.

## Run the Chapter 4 Streamable HTTP server

```bash
python -m build_an_mcp_server.http_server
```

or through the console script:

```bash
build-an-mcp-server-http
```

The MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

Use Inspector with transport `Streamable HTTP` and URL `http://127.0.0.1:8000/mcp`.

## Test levels

### 1. Fast local tests

These require no external credentials and do not open a browser:

```bash
pytest tests/test_ch02_snapshot.py tests/test_ch04_runtime.py
```

Expected result: Chapter 2 snapshot helpers import and work; Chapter 4 can list tools, read and write files, return structured content, remove write tools in read-only mode, and construct the HTTP app.

### 2. Owner-level capability smoke test script

This runs through an actual MCP client session and calls enabled capabilities:

```bash
python scripts/smoke_all_capabilities.py
```

With the minimal `.env`, it tests filesystem and prompts. With full `.env`, it also tests GitHub, Tavily web search, and Playwright browser automation.

### 3. Owner-level pytest integration test

Set your `.env` for full capabilities, install Chromium, then run:

```bash
RUN_INTEGRATION=1 pytest tests/test_owner_smoke_integration.py -s
```

This test skips external capability checks unless both the feature flag and the needed credential/runtime are available.

## Common failures

- `ModuleNotFoundError: mcp`: install with `pip install -e ".[dev,examples]"`.
- `GITHUB_TOKEN is required`: set `ENABLE_GITHUB=false` or provide `GITHUB_TOKEN`.
- `TAVILY_API_KEY is required`: set `ENABLE_WEB_SEARCH=false` or provide `TAVILY_API_KEY`.
- Browser launch fails: run `playwright install chromium`.
- `write_file` missing from `tools/list`: check `READ_ONLY`; this is expected when `READ_ONLY=true`.

## Security notes

This repo is a teaching project, not a hardened deployment. The Chapter 4 runtime adds local binding, Origin validation, explicit filesystem roots, read-only mode, and cleanup hooks. Authentication, authorization, observability, rate limiting, multi-tenant controls, and deployment hardening belong to later chapters.
