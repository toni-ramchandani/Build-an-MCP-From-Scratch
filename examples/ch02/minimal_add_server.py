"""The smallest Chapter 2 mechanism example: one server and one tool."""

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("chapter-2-minimal")


@server.tool(
    title="Add two integers",
    description="Return the sum of two integers.",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
)
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    server.run()
