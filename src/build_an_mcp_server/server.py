from __future__ import annotations

from .config import load_settings
from .factory import create_server


def main() -> None:
    """Run the local stdio entry point without writing diagnostics to stdout."""

    server = create_server(load_settings(), boundary="stdio")
    server.run()


if __name__ == "__main__":
    main()
