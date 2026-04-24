# Examples

This directory contains the example programs used in the early chapters of the book.

They are intentionally small and concrete. They are not a client SDK and they are not the production server implementation used later in the book. Their job is to make MCP transport mechanics, message flow, and schema-driven validation easy to inspect.

## Directory layout

- `ch02/minimal_add_server.py` is the smallest possible FastMCP example from Chapter 2.
- `ch03/stdio_host.py` is a host-side stdio harness.
- `ch03/http_adapter.py` is a teaching HTTP-to-stdio bridge.
- `ch03/transport.py` defines the small transport abstraction used by the Chapter 3 examples.
- `ch03/validate_and_call.py` validates tool arguments locally before calling a tool.

## Install the example dependencies

Install the project first:

```bash
pip install -e .
```

Then install the extra dependencies used by the Chapter 3 examples:

```bash
pip install -e ".[examples]"
```

If you use a local `.env` file for tokens or configuration, create it in the repository root before running the examples.

## `ch02/minimal_add_server.py`

This is the smallest FastMCP server in the repo. It exists to support the first server examples in Chapter 2.

Run it with:

```bash
python examples/ch02/minimal_add_server.py
```

## `ch03/stdio_host.py`

`stdio_host.py` is a host-side harness for local subprocess communication.

It launches the MCP server as a child process, sends JSON-RPC messages over stdio, and prints the replies so you can inspect the lifecycle and tool flow directly.

What it demonstrates:

- `initialize`
- `notifications/initialized`
- `tools/list`
- optional `tools/call`
- strict separation between protocol traffic on `stdout` and diagnostics on `stderr`

Example usage:

```bash
python examples/ch03/stdio_host.py
python examples/ch03/stdio_host.py --call list_directory --args '{"path":"."}'
```

## `ch03/http_adapter.py`

`http_adapter.py` is a small HTTP-to-stdio bridge.

It keeps the existing MCP server running over stdio, but exposes a single HTTP endpoint so the same JSON-RPC messages can be sent from environments that cannot spawn a local subprocess directly.

Important scope note:

- this file is a teaching bridge
- it is not a full native Streamable HTTP server
- it implements one `POST /mcp` endpoint
- it can return either a normal JSON response or a response-scoped SSE stream
- the SSE branch is selected with the adapter-specific request header `X-Prefer-Stream: true`

Start the adapter:

```bash
python examples/ch03/http_adapter.py
```

JSON response example:

```bash
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Response-scoped SSE example:

```bash
curl -N -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Prefer-Stream: true" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

## `ch03/transport.py`

`transport.py` defines a very small transport abstraction used by the Chapter 3 examples.

It contains:

- a `Transport` interface
- `StdioTransport` for subprocess communication
- `HttpTransport` for the JSON-response branch of the HTTP example

This file is not a transport framework. It exists so later host-side examples can switch between stdio and HTTP without rewriting the surrounding logic.

One limitation is explicit in the code: `HttpTransport` handles only the JSON-response branch. If the server returns `text/event-stream`, the example raises `NotImplementedError` rather than pretending SSE is supported.

## `ch03/validate_and_call.py`

`validate_and_call.py` is a host-side validator built on top of `StdioTransport`.

It initializes a session, calls `tools/list`, finds the selected tool definition, validates input arguments locally against `inputSchema`, calls the tool only when validation succeeds, and optionally validates returned `structuredContent` against `outputSchema`.

Example usage:

```bash
python examples/ch03/validate_and_call.py --tool list_directory --args-file args.json
```

On Windows PowerShell, use `--args-file` rather than inline JSON when possible.

## Smoke tests

### stdio harness

```bash
python examples/ch03/stdio_host.py
```

A successful run should initialize the session and print the result of `tools/list`.

### HTTP bridge

In one terminal:

```bash
python examples/ch03/http_adapter.py
```

In another terminal:

```bash
curl -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Schema validator

```bash
python examples/ch03/validate_and_call.py --tool list_directory --args-file args.json
```

The validator should fail locally when the supplied JSON object does not match the tool schema.
