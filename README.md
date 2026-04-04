# Build an MCP Server

An Model Context Protocol (MCP) server implementation that provides powerful capabilities for AI assistants including filesystem operations, GitHub integration, browser automation, and web search.

## Features

### 🗂️ Filesystem Operations
- **Read files**: Safe file reading with configurable allowed directories
- **Write files**: Create and modify files with overwrite protection
- **List directories**: Browse directory contents
- **Path validation**: Prevent directory traversal attacks

### 🐙 GitHub Integration
- **Repository info**: Get detailed repository metadata
- **Issues management**: List, search, and analyze issues
- **Pull requests**: Access PR information and status
- **User profiles**: Retrieve GitHub user data
- **Repository search**: Find repositories with advanced filters

### 🌐 Browser Automation
- **Page navigation**: Open and interact with web pages
- **Element interaction**: Click, fill forms, extract text
- **Screenshots**: Capture page screenshots (full or viewport)
- **Health monitoring**: Built-in health checks
- **Session management**: Multiple concurrent browser sessions

### 🔍 Web Search
- **Tavily integration**: Advanced web search capabilities
- **Customizable results**: Control depth, domains, and result count
- **Structured output**: JSON-formatted search results

### 🤖 AI-Ready Prompts
Pre-built prompts for common tasks:
- Repository analysis
- Issue debugging
- Code review checklists
- Topic research
- File analysis
- Web automation planning

## Installation

### Prerequisites
- Python 3.10 or higher
- pip

### Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/toni-ramchandani/Build-an-MCP-From-Scratch.git
   cd Build-an-MCP-From-Scratch
   ```

2. **Install dependencies**
   
   ```bash
   pip install -e .
   ```

3. **Install Playwright browsers**
   ```bash
   playwright install chromium
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

5. **Run the server**
   ```bash
   python -m build_an_mcp_server.server
   ```

## Configuration

Create a `.env` file in the project root with the following variables:

```env
# Required for GitHub features
GITHUB_TOKEN=your_github_token_here

# Required for web search
TAVILY_API_KEY=your_tavily_api_key_here

# Optional: Filesystem access control
# Windows (semicolon-separated)
FS_ALLOWED_DIRS=C:\allowed\path1;C:\allowed\path2

# Linux/Mac (colon-separated)
FS_ALLOWED_DIRS=/home/user/allowed:/home/user/projects

# Optional: Logging
LOG_LEVEL=INFO
```

### Getting API Keys

- **GitHub Token**: [https://github.com/settings/tokens](https://github.com/settings/tokens)
  - Required scopes: `repo`, `read:user`
  
- **Tavily API Key**: [https://tavily.com](https://tavily.com)
  - Sign up and get your API key from the dashboard

## Usage Examples

### Filesystem Operations

```python
# Read a file
read_file(path="/path/to/file.txt")

# Write a file
write_file(
    path="/path/to/output.txt",
    content="Hello, MCP!",
    overwrite=True
)

# List directory
list_directory(path="/path/to/directory")
```

### GitHub Operations

```python
# Get repository info
get_repository_info(owner="microsoft", repo="vscode")

# List issues
list_repository_issues(
    owner="microsoft",
    repo="vscode",
    state="open",
    labels="bug"
)

# Search repositories
search_repositories(
    query="MCP server language:Python",
    sort="stars",
    order="desc"
)
```

### Browser Automation

```python
# Open a page
browser_open_page(
    url="https://example.com",
    wait_until="domcontentloaded"
)

# Fill a form
browser_fill(
    page_id="page_1",
    selector="#email",
    text="user@example.com"
)

# Take screenshot
browser_screenshot(page_id="page_1", full_page=True)

# Close page
browser_close_page(page_id="page_1")
```

### Web Search

```python
# Search the web
web_search(
    query="MCP protocol documentation",
    max_results=10,
    search_depth="advanced"
)
```

## Project Structure

```
Build-an-MCP-From-Scratch/
├── pyproject.toml          # Project configuration and dependencies
├── README.md               # This file
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore rules
├── src/
│   └── build_an_mcp_server/
│       ├── __init__.py         # Package initialization
│       ├── server.py           # Main MCP server implementation
│       ├── fs_utils.py         # Filesystem utilities
│       ├── github_utils.py     # GitHub API helpers
│       └── browser_utils.py    # Browser automation helpers
└── examples/               # Usage examples
    ├── README.md           # Examples overview
    └── http_transport/     # HTTP/SSE transport example
        ├── README.md
        └── server_http.py
```

## Security Considerations

### Filesystem Access
- **Sandboxing**: Only directories listed in `FS_ALLOWED_DIRS` are accessible
- **Path validation**: Prevents directory traversal attacks
- **Size limits**: File reads are capped at 100KB by default

### API Keys
- **Environment variables**: Store sensitive credentials in `.env`
- **Never commit**: Add `.env` to `.gitignore`
- **Minimal permissions**: Use tokens with least required privileges

### Browser Automation
- **Headless mode**: Runs in headless Chromium by default
- **Timeouts**: Prevents hanging operations
- **Resource cleanup**: Automatic cleanup of browser resources

## Troubleshooting

### Playwright Installation Issues
```bash
# Reinstall Playwright browsers
playwright install --force chromium
```

### Import Errors
```bash
# Ensure package is installed in editable mode
pip install -e .
```

### API Rate Limits
- GitHub: 5000 requests/hour (authenticated)
- Tavily: Check your plan limits

## Testing with MCP Inspector

Use the official MCP Inspector to test your server:

**With stdio transport (default):**
```bash
npx @modelcontextprotocol/inspector python -m build_an_mcp_server.server
```

**With HTTP transport (see examples):**
```bash
# Run the HTTP server first
python examples/http_transport/server_http.py

# Then connect inspector
npx @modelcontextprotocol/inspector http://localhost:3000/sse
```

This will open a web interface where you can:
- Browse and test all available tools
- View resources and prompts
- Debug server responses

## Examples

Check the [examples/](examples/) directory for practical demonstrations:
- **HTTP Transport**: Run the server as a web service with SSE transport
- More examples coming soon!

Each example includes its own README with detailed instructions.

## Acknowledgments

- Built with [Official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
- Uses [PyGithub](https://github.com/PyGithub/PyGithub) for GitHub API
- Uses [Playwright](https://playwright.dev/python/) for browser automation
- Uses [Tavily](https://tavily.com) for web search

## Support

- 🐛 [Issue Tracker](https://github.com/toni-ramchandani/Build-an-MCP-From-Scratch/issues)
- 💬 [Discussions](https://github.com/toni-ramchandani/Build-an-MCP-From-Scratch/discussions)
