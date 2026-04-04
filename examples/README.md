# MCP Server Examples

This directory contains practical examples demonstrating different ways to use and interact with the MCP server.

## 📋 Examples Overview

### 1. `stdio_host.py` - Complete MCP Client
**Purpose:** Demonstrates the full MCP protocol handshake and tool calling via stdio transport.

**What it does:**
- Shows proper initialization sequence: `initialize` → `initialized` → `tools/list` → `tools/call`
- Lists all available tools from the server
- Optionally calls a specific tool with arguments
- Handles environment variables and error cases

**Usage:**
```bash
# List all available tools
python examples/stdio_host.py

# Call a specific tool
python examples/stdio_host.py --call get_user_info --args '{"username":"octocat"}'
```

**Learn from this:**
- How to implement a proper MCP client
- Required JSON-RPC message format
- Correct handshake sequence
- Tool discovery and invocation

---

### 2. `http_adapter.py` - HTTP/SSE Bridge
**Purpose:** Wraps the stdio MCP server and exposes it via HTTP endpoints.

**What it does:**
- Runs the MCP server as a subprocess
- Exposes two HTTP endpoints:
  - `POST /mcp` - Standard JSON-RPC over HTTP
  - `POST /mcp/stream` - Server-Sent Events (SSE) streaming
- Handles request/response matching
- Enables concurrent HTTP clients

**Usage:**
```bash
# Install dependencies first
pip install -e ".[examples]"

# Run the HTTP adapter
python examples/http_adapter.py
# Server starts on http://127.0.0.1:8000
```

**Test with curl:**
```bash
# List tools
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Call a tool
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_directory","arguments":{"path":"."}}}'
```

**Learn from this:**
- How to bridge stdio to HTTP
- Server-Sent Events implementation
- Subprocess management
- Request multiplexing

---

### 3. `transport.py` - Abstract Transport Layer
**Purpose:** Demonstrates clean abstraction over different transport mechanisms.

**What it does:**
- Defines abstract `Transport` base class
- Implements `StdioTransport` for subprocess communication
- Implements `HttpTransport` for REST/HTTP communication
- Provides uniform `Message` interface

**Usage:**
```python
from transport import StdioTransport, HttpTransport, Message

# Use stdio transport
transport = StdioTransport(["python", "server.py"])
transport.send(Message({"jsonrpc": "2.0", "method": "initialize", ...}))
response = transport.recv()

# Or use HTTP transport
transport = HttpTransport("http://localhost:8000/mcp")
transport.send(Message({"jsonrpc": "2.0", "method": "tools/list", ...}))
response = transport.recv()
```

**Learn from this:**
- Design patterns for transport abstraction
- How to write swappable implementations
- Clean separation of concerns

---

### 4. `validate_and_call.py` - JSON Schema Validation
**Purpose:** Pre-validates tool arguments using JSON Schema before calling tools.

**What it does:**
- Fetches tool schemas from the server
- Validates arguments against `inputSchema` using `jsonschema` library
- Provides detailed validation error messages
- Repairs common JSON formatting issues (smart quotes)
- Only calls the tool if validation passes

**Usage:**
```bash
# Install dependencies first
pip install -e ".[examples]"

# Call tool with validated args
python examples/validate_and_call.py --tool get_user_info --args '{"username":"octocat"}'

# Call with args from file
python examples/validate_and_call.py --tool list_directory --args-file args.json

# Example args.json:
# {"path": "/home/user"}
```

**Learn from this:**
- JSON Schema validation in practice
- Type safety before execution
- Better error reporting
- Input sanitization

---

## 🚀 Getting Started

### Prerequisites
```bash
# Core server dependencies (required)
pip install -e .

# Example-specific dependencies (optional)
pip install -e ".[examples]"
```

### Quick Test
```bash
# 1. Make sure your .env file is configured
cp .env.example .env
# Edit .env with your GITHUB_TOKEN and TAVILY_API_KEY

# 2. Test the stdio client
python examples/stdio_host.py

# 3. Call a tool
python examples/stdio_host.py --call list_directory --args '{"path":"."}'
```

## 📦 Dependencies

### Core (always installed)
- `mcp` - MCP protocol implementation
- `pygithub` - GitHub API
- `python-dotenv` - Environment variables
- `playwright` - Browser automation
- `requests` - HTTP client

### Examples (install with `pip install -e ".[examples]"`)
- `fastapi` - Web framework (for http_adapter.py)
- `uvicorn` - ASGI server (for http_adapter.py)
- `jsonschema` - Schema validation (for validate_and_call.py)

## 🔍 Testing Examples

### Test stdio_host.py
```bash
python examples/stdio_host.py
# Should show: initialize response, tools list
```

### Test http_adapter.py
```bash
# Terminal 1: Start the HTTP server
python examples/http_adapter.py

# Terminal 2: Test with curl
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Test validate_and_call.py
```bash
# Valid call
python examples/validate_and_call.py --tool get_user_info --args '{"username":"octocat"}'

# Invalid args (will show validation errors)
python examples/validate_and_call.py --tool get_user_info --args '{"invalid":"field"}'
```

## 💡 Common Patterns

### 1. Initialize Handshake
All MCP clients must follow this sequence:
```python
# 1. Send initialize request
send({"jsonrpc":"2.0", "id":"init-1", "method":"initialize", "params":{...}})

# 2. Wait for initialize response
response = recv()

# 3. Send initialized notification
send({"jsonrpc":"2.0", "method":"notifications/initialized", "params":{...}})

# 4. Now you can use tools/resources/prompts
```

### 2. Calling Tools
```python
send({
    "jsonrpc": "2.0",
    "id": "call-123",
    "method": "tools/call",
    "params": {
        "name": "tool_name",
        "arguments": {"arg1": "value1"}
    }
})
response = recv()
```

### 3. Error Handling
```python
response = recv()
if "error" in response:
    print(f"Error: {response['error']}")
elif "result" in response:
    print(f"Success: {response['result']}")
```

## 🐛 Troubleshooting

### "GITHUB_TOKEN not set" warning
```bash
# Make sure .env file exists and has your token
cp .env.example .env
# Edit .env and add: GITHUB_TOKEN=your_token_here
```

### "Timeout waiting for server"
- Server may have crashed; check stderr output
- Server may still be starting; increase timeout
- Check if server.py path is correct

### "Module not found: fastapi"
```bash
# Install example dependencies
pip install -e ".[examples]"
```

### HTTP adapter port already in use
```bash
# Edit http_adapter.py and change the port:
uvicorn.run(app, host="127.0.0.1", port=8001)  # Changed from 8000
```

## 🎯 Next Steps

1. **Understand the handshake:** Run `stdio_host.py` and observe the JSON-RPC messages
2. **Try HTTP transport:** Run `http_adapter.py` and test with curl
3. **Add validation:** Use `validate_and_call.py` to see schema validation
4. **Build your own client:** Use these examples as templates

## 📚 Resources

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [JSON-RPC 2.0](https://www.jsonrpc.org/specification)
- [JSON Schema](https://json-schema.org/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
