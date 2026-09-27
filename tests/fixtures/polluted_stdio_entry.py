from __future__ import annotations

from build_an_mcp_server.server import main

# Intentional test-only startup pollution before the SDK claims the stdio wire.
print("polluted-stdout-fixture", flush=True)
main()
