# Narrow teaching examples

The active implementation lives in `src/build_an_mcp_server/`. These files are
small mechanism microscopes, not chapter-sized copies of that server.

| Chapter | Example | Question it isolates |
|---|---|---|
| 2 | `ch02/minimal_add_server.py` | What is the smallest useful MCP tool registration? |
| 3 | `ch03/raw_stdio_trace.py` | What does one MCP 2026-07-28 request and response look like over newline-framed stdio? |

Check the minimal example through the SDK client on the book's explicit
2026-07-28 protocol path:

```text
uv run --frozen --extra dev python -m pytest -q tests/contract/test_examples.py -k chapter_2
```

The test discovers the typed `add` operation, checks its schemas, invokes it
with 20 and 22, and checks the structured result. For an interactive view of
the complete workspace server, use the explicit-modern Inspector template
described in the root README.

Trace one raw request against an explicit workspace root:

```bash
uv run python -m examples.ch03.raw_stdio_trace --root /absolute/path/to/workspace
```

Do not use this directory as a second source of truth for the complete server;
the active implementation under `src/build_an_mcp_server/` is authoritative.
