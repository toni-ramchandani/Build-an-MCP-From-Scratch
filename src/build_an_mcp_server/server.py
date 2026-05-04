from __future__ import annotations

from .config import load_settings
from .factory import create_server


def main() -> None:
    """Run the local stdio entry point."""

    settings = load_settings()
    mcp = create_server(settings)
    mcp.run()


if __name__ == "__main__":
    main()
