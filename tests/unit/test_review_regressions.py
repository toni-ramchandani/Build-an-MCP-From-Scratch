from pathlib import Path
from typing import NoReturn

import pytest
from mcp.client import Client

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.factory import create_server
from build_an_mcp_server.runtime_state import make_app_lifespan
from tests.helpers import make_settings


@pytest.mark.anyio
@pytest.mark.parametrize("tail", [b"\xc2", b"\xe2\x82", b"\xf0\x9f\x92"])
@pytest.mark.parametrize("prefix_length", [3, 1023])
async def test_incomplete_utf8_eof_is_a_tool_error(
    tmp_path: Path, tail: bytes, prefix_length: int
) -> None:
    (tmp_path / "bad.txt").write_bytes(b"a" * prefix_length + tail)
    settings = make_settings(workspace_roots=(tmp_path,), max_file_read_bytes=1024)
    async with Client(create_server(settings), cache=None) as client:
        offset = 0
        for _ in range(3):
            result = await client.call_tool(
                "read_workspace_text",
                {"root_id": "root-1", "relative_path": "bad.txt", "offset_bytes": offset},
            )
            if result.is_error:
                return
            assert result.structured_content is not None
            next_offset = result.structured_content["next_offset_bytes"]
            assert isinstance(next_offset, int) and next_offset > offset
            offset = next_offset
    pytest.fail("Invalid UTF-8 at EOF must be rejected")


@pytest.mark.anyio
async def test_registered_cleanup_runs_if_later_acquisition_fails(tmp_path: Path) -> None:
    calls: list[str] = []
    settings = make_settings(
        workspace_roots=(tmp_path,),
        enable_browser=True,
        browser_allowed_origins=("https://example.com",),
    )

    def broken_factory(_settings: ServerSettings) -> NoReturn:
        raise RuntimeError("synthetic acquisition failure")

    lifespan = make_app_lifespan(
        settings,
        browser_factory=broken_factory,
        additional_cleanups=(lambda: calls.append("provider_closed"),),
    )
    with pytest.raises(RuntimeError, match="synthetic acquisition failure"):
        async with lifespan(None):  # type: ignore[arg-type]
            pytest.fail("Startup must not reach the yield")
    assert calls == ["provider_closed"]


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["read_workspace_text", "list_workspace_directory"])
async def test_filesystem_metadata_failure_is_caller_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    target = tmp_path / "private-metadata-canary"
    if operation == "read_workspace_text":
        target.write_text("canary", encoding="utf-8")
    else:
        target.mkdir()
    settings = make_settings(workspace_roots=(tmp_path,))
    original = Path.exists

    def denied(path: Path) -> bool:
        if path == target:
            raise PermissionError(13, "Permission denied", str(path))
        return original(path)

    monkeypatch.setattr(Path, "exists", denied)
    async with Client(create_server(settings), mode="2026-07-28", cache=None) as client:
        result = await client.call_tool(
            operation,
            {"root_id": "root-1", "relative_path": target.name},
        )
    assert result.is_error is True
    assert str(tmp_path) not in result.model_dump_json()
