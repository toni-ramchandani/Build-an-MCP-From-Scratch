# Build an MCP from Scratch

This repository accompanies the book *Build an MCP from Scratch* and contains the Python code used across the early chapters.

The project has two distinct roles:

- `src/build_an_mcp_server/` contains the real MCP server used as the book’s running example.
- `examples/` contains small teaching utilities that make protocol flow, transport behavior, and schema validation easier to inspect.

The server is intentionally broader than a “hello world” example. It exposes tools, resources, and prompts around four domains:

- local filesystem access within an explicit allow-list
- GitHub repository and issue workflows
- browser automation with Playwright
- live web search with Tavily

The examples are intentionally narrower. They are not a general-purpose client SDK, and they are not meant to replace the official MCP Python SDK. Their purpose is to make the wire protocol and host-side behavior visible on the page.

## Repository layout

```text
Build-an-MCP-From-Scratch/
├── pyproject.toml
├── README.md
├── .env.example
├── src/
│   └── build_an_mcp_server/
│       ├── __init__.py
│       ├── server.py
│       ├── fs_utils.py
│       ├── github_utils.py
│       └── browser_utils.py
└── examples/
    ├── README.md
    ├── ch02/
    │   └── minimal_add_server.py
    └── ch03/
        ├── stdio_host.py
        ├── http_adapter.py
        ├── transport.py
        └── validate_and_call.py
```

## Prerequisites

- Python 3.10 or later
- `pip` or `uv`
- Playwright browser binaries for the browser tools

## Installation

Install the project in editable mode:

```bash
pip install -e .
```

Install the optional packages used by the Chapter 3 examples:

```bash
pip install -e ".[examples]"
```

Install the browser runtime used by the browser tools:

```bash
playwright install chromium
```

## Configuration

Copy the environment template and edit it for your machine:

```bash
cp .env.example .env
```

The main settings are:

- `FS_ALLOWED_DIRS`: one or more absolute directories the filesystem tools are allowed to access
- `GITHUB_TOKEN`: required for GitHub-backed tools and resources
- `TAVILY_API_KEY`: required for the `web_search` tool

`FS_ALLOWED_DIRS` is not optional for the filesystem helpers in this server. The helper module fails closed if the variable is missing or empty.

Examples:

```env
# Windows
FS_ALLOWED_DIRS=C:\work\repo;C:\work\scratch

# macOS / Linux
FS_ALLOWED_DIRS=/home/user/work/repo:/home/user/scratch

GITHUB_TOKEN=your_token_here
TAVILY_API_KEY=your_api_key_here
LOG_LEVEL=INFO
```

## Running the server

Run the real server package directly:

```bash
python -m build_an_mcp_server.server
```

You can also use the console script installed from `pyproject.toml`:

```bash
build-an-mcp-server
```

The default runtime path is stdio, which is the simplest way to connect a local host to the server.

## Running the examples

The examples in `examples/ch03/` are chapter support programs.

List tools and inspect the stdio handshake:

```bash
python examples/ch03/stdio_host.py
```

Call one tool through the stdio harness:

```bash
python examples/ch03/stdio_host.py --call list_directory --args '{"path":"."}'
```

Start the teaching HTTP bridge:

```bash
python examples/ch03/http_adapter.py
```

Run the schema-aware validator:

```bash
python examples/ch03/validate_and_call.py --tool list_directory --args-file args.json
```

On Windows PowerShell, `--args-file` is usually more reliable than inline JSON arguments.

See `examples/README.md` for the example-specific notes and smoke-test commands.

## What the examples are and are not

The Chapter 3 examples are deliberately narrow:

- `stdio_host.py` is a sequential host-side harness for stdio.
- `http_adapter.py` is a teaching bridge that exposes the stdio server through a single `POST /mcp` endpoint.
- `transport.py` is a small transport abstraction for the examples.
- `validate_and_call.py` is a host-side validator that uses `tools/list` schemas before `tools/call`.

These files are useful for learning and inspection. They are not the production runtime surface of the book’s server.

## Security notes

This repository is intended for learning and experimentation, but the safeguards still matter.

- Filesystem access is constrained by `FS_ALLOWED_DIRS`.
- Browser automation should be treated as a privileged capability.
- GitHub and Tavily credentials should be supplied through environment variables, not hardcoded.
- The HTTP bridge in `examples/ch03/http_adapter.py` is a teaching subset, not a hardened production deployment.

## Current status

As of the revised Chapter 3 material, the repo is aligned around the current MCP protocol version `2025-11-25`, the standard transports `stdio` and `Streamable HTTP`, and the distinction between protocol-level errors and tool-result failures.

The next development step in the book is to productionize the real server and add a proper `tests/` tree, rather than expanding the Chapter 3 teaching helpers.
