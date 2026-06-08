from __future__ import annotations

import importlib
from pathlib import Path

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.http_server import create_http_app


def test_stdio_entry_point_module_exposes_main() -> None:
    module = importlib.import_module("build_an_mcp_server.server")

    assert hasattr(module, "main")


def test_streamable_http_app_can_be_constructed(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "readme.md").write_text("# Project\n", encoding="utf-8")

    settings = ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(root,),
        read_only=True,
        enable_github=False,
        enable_browser=False,
    )

    app = create_http_app(settings)

    assert app is not None
    assert callable(app)
