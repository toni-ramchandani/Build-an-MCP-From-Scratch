from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Chapter 2 Minimal Tool Demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def main() -> None:
    # Explicit stdio keeps the Chapter 2 example aligned with the official quickstart.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
