"""
Build an MCP Server from Scratch.

This package provides a Model Context Protocol (MCP) server with:
- Filesystem operations (read, write, list)
- GitHub API integration (repos, issues, PRs, users)
- Browser automation via Playwright
- Web search via Tavily API
- AI-ready prompts for common tasks
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

from build_an_mcp_server.server import mcp

__all__ = ["mcp"]
