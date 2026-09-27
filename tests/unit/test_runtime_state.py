from __future__ import annotations

from pathlib import Path

import pytest

from build_an_mcp_server.runtime_state import RuntimeState, make_app_lifespan
from tests.helpers import make_settings


@pytest.mark.anyio
async def test_cleanup_is_idempotent_and_best_effort(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    state = RuntimeState()

    def failing_cleanup() -> None:
        calls.append("failure")
        raise RuntimeError("sensitive detail")

    async def successful_cleanup() -> None:
        calls.append("success")

    state.add_cleanup(successful_cleanup)
    state.add_cleanup(failing_cleanup)

    await state.aclose()
    await state.aclose()

    assert calls == ["failure", "success"]
    assert state.closed is True
    assert state.cleanup_failures == ["RuntimeError"]
    assert "sensitive detail" not in repr(state.cleanup_failures)
    assert "sensitive detail" not in caplog.text


@pytest.mark.anyio
async def test_browser_runtime_belongs_to_application_lifespan(tmp_path: Path) -> None:
    settings = make_settings(
        workspace_roots=(tmp_path,),
        enable_browser=True,
        browser_allowed_origins=("https://example.com",),
    )

    class FakeBrowser:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    browser = FakeBrowser()
    lifespan = make_app_lifespan(settings, browser_factory=lambda _: browser)  # type: ignore[arg-type]

    async with lifespan(None):  # type: ignore[arg-type]
        assert browser.closed is False

    assert browser.closed is True
