from __future__ import annotations

from pathlib import Path

import pytest

from build_an_mcp_server.config import ServerSettings
from build_an_mcp_server.runtime_state import RuntimeState


def _settings(root: Path) -> ServerSettings:
    return ServerSettings(
        enable_filesystem=True,
        fs_allowed_dirs=(root,),
        read_only=True,
        enable_github=False,
        enable_browser=False,
    )


def test_runtime_state_starts_empty(tmp_path: Path) -> None:
    state = RuntimeState(settings=_settings(tmp_path))

    assert state.closed is False
    assert state.browser_handles == {}
    assert state.get_browser_handle("page") is None


def test_runtime_state_remembers_and_forgets_browser_handles(tmp_path: Path) -> None:
    state = RuntimeState(settings=_settings(tmp_path))
    handle = object()

    state.remember_browser_handle("page", handle)

    assert state.get_browser_handle("page") is handle
    assert state.forget_browser_handle("page") is handle
    assert state.get_browser_handle("page") is None


@pytest.mark.anyio
async def test_runtime_state_cleanup_callbacks_are_called_once(tmp_path: Path) -> None:
    calls: list[str] = []
    state = RuntimeState(settings=_settings(tmp_path))

    def sync_cleanup() -> None:
        calls.append("sync")

    async def async_cleanup() -> None:
        calls.append("async")

    state.add_cleanup(sync_cleanup)
    state.add_cleanup(async_cleanup)

    await state.aclose()
    await state.aclose()

    assert state.closed is True
    assert sorted(calls) == ["async", "sync"]


def test_runtime_state_rejects_new_handles_after_close(tmp_path: Path) -> None:
    state = RuntimeState(settings=_settings(tmp_path))

    async def close() -> None:
        await state.aclose()

    import anyio

    anyio.run(close)

    with pytest.raises(RuntimeError, match="closed"):
        state.remember_browser_handle("page", object())

    with pytest.raises(RuntimeError, match="closed"):
        state.add_cleanup(lambda: None)
