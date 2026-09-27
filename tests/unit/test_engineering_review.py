from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import anyio
import pytest
from mcp.client import Client
from mcp.client.stdio import get_default_environment

from build_an_mcp_server.browser_capabilities import _owner  # pyright: ignore[reportPrivateUsage]
from build_an_mcp_server.errors import PublicToolError
from build_an_mcp_server.factory import create_server
from build_an_mcp_server.github_adapter import GitHubAdapter
from build_an_mcp_server.runtime_state import RuntimeState
from build_an_mcp_server.workspace import WorkspaceAdapter
from tests.helpers import make_settings
from tests.unit.test_browser_runtime import FakeBrowser, FakeContext, FakePage, make_runtime


def test_settings_failure_does_not_print_token(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "build_an_mcp_server.server"],
        cwd=tmp_path,
        env=get_default_environment() | {"MCP_GITHUB_TOKEN": "AUDIT_FAKE_TOKEN"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "AUDIT_FAKE_TOKEN" not in result.stdout + result.stderr
    assert "no explicit workspace_roots" in result.stderr


@pytest.mark.parametrize("existing", [False, True])
def test_competing_writes_only_one_expected_state_commits(tmp_path: Path, existing: bool) -> None:
    target = tmp_path / "file.txt"
    if existing:
        target.write_text("old")
    expected = hashlib.sha256(b"old").hexdigest() if existing else "absent"
    adapter = WorkspaceAdapter(
        (tmp_path,),
        max_file_read_bytes=1024,
        max_directory_entries=10,
        max_write_bytes=1024,
        max_digest_bytes=1024,
    )
    first_at_replace = threading.Event()
    second_at_replace = threading.Event()
    real_replace = __import__("os").replace
    counter_lock = threading.Lock()
    replace_calls = 0

    def delayed_replace(src: str, dst: Path) -> None:
        nonlocal replace_calls
        with counter_lock:
            replace_calls += 1
            first = replace_calls == 1
        if first:
            first_at_replace.set()
            second_at_replace.wait(timeout=0.2)
        else:
            second_at_replace.set()
        real_replace(src, dst)

    def write(content: str) -> str:
        try:
            adapter.write_text("root-1", "file.txt", content, expected_sha256=expected)
        except PublicToolError as exc:
            assert "state changed" in str(exc)
            return "conflict"
        return "success"

    with (
        patch("build_an_mcp_server.workspace.os.replace", delayed_replace),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        first = executor.submit(write, "first")
        assert first_at_replace.wait(timeout=2)
        second = executor.submit(write, "second")
        results = [first.result(timeout=3), second.result(timeout=3)]
    assert sorted(results) == ["conflict", "success"]
    assert replace_calls == 1
    assert target.read_text() == "first"


@pytest.mark.anyio
async def test_write_preflight_os_error_is_safe_at_mcp_boundary(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("old")
    settings = make_settings(workspace_roots=(tmp_path,), enable_mutation=True)
    async with Client(create_server(settings), cache=None) as client:
        with patch.object(
            WorkspaceAdapter,
            "_sha256",
            side_effect=PermissionError(13, "Denied", "PRIVATE_PATH_CANARY"),
        ):
            result = await client.call_tool(
                "write_workspace_text",
                {
                    "root_id": "root-1",
                    "relative_path": "file.txt",
                    "content": "new",
                    "expected_sha256": "0" * 64,
                },
            )
    assert result.is_error
    assert "PRIVATE_PATH_CANARY" not in result.model_dump_json()
    assert "The file could not be written" in result.model_dump_json()


def test_casefold_ties_have_a_total_order(tmp_path: Path) -> None:
    adapter = WorkspaceAdapter(
        (tmp_path,),
        max_file_read_bytes=1024,
        max_directory_entries=1,
        max_write_bytes=1024,
        max_digest_bytes=1024,
    )

    def is_directory(*, follow_symlinks: bool) -> bool:
        return False

    def is_file(*, follow_symlinks: bool) -> bool:
        return True

    def entry(name: str) -> SimpleNamespace:
        return SimpleNamespace(
            name=name, is_symlink=lambda: False, is_dir=is_directory, is_file=is_file
        )

    from contextlib import nullcontext

    for order in (["a.txt", "A.txt"], ["A.txt", "a.txt"]):
        with patch(
            "build_an_mcp_server.workspace.os.scandir",
            side_effect=[nullcontext(iter(map(entry, order))) for _ in range(2)],
        ):
            first = adapter.list_directory("root-1", ".", offset=0)
            second = adapter.list_directory("root-1", ".", offset=1)
        assert first.entries[0].name == "A.txt"
        assert second.entries[0].name == "a.txt"


def test_browser_identity_encoding_is_unambiguous() -> None:
    owners: list[str] = []
    for client_id, subject in (("a:b", "c"), ("a", "b:c"), ("a", None), ("a", "")):
        with patch(
            "mcp.server.auth.middleware.auth_context.get_access_token",
            return_value=SimpleNamespace(client_id=client_id, subject=subject),
        ):
            owners.append(_owner(True))
        assert json.loads(owners[-1]) == [client_id, subject]
    assert len(set(owners)) == len(owners)


@pytest.mark.anyio
async def test_summary_failure_does_not_consume_handle_quota() -> None:
    class BadPage(FakePage):
        async def title(self) -> str:
            raise RuntimeError("provider detail")

    failed = FakeContext(BadPage("short"))
    good = FakeContext(FakePage("short"))
    runtime = make_runtime(FakeBrowser([failed, good]), max_handles=1)
    with pytest.raises(PublicToolError):
        await runtime.open_page("https://example.com", owner="a")
    assert failed.closed
    opened = await runtime.open_page("https://example.com", owner="a")
    assert opened.handle
    await runtime.aclose()


@pytest.mark.anyio
async def test_cancelled_open_closes_unpublished_context() -> None:
    reached = asyncio.Event()

    class WaitingPage(FakePage):
        async def goto(self, url: str, *, wait_until: str, timeout: int) -> object:
            reached.set()
            await asyncio.Event().wait()
            return None

    context = FakeContext(WaitingPage("short"))
    runtime = make_runtime(FakeBrowser([context]))
    task = asyncio.create_task(runtime.open_page("https://example.com", owner="a"))
    await asyncio.wait_for(reached.wait(), 2)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert context.closed
    await runtime.aclose()


@pytest.mark.anyio
async def test_hung_summary_has_a_deadline_and_releases_runtime() -> None:
    class WaitingTitle(FakePage):
        async def title(self) -> str:
            await asyncio.Event().wait()
            return "unused"

    context = FakeContext(WaitingTitle("short"))
    runtime = make_runtime(FakeBrowser([context]))
    with anyio.fail_after(3):
        with pytest.raises(PublicToolError):
            await runtime.open_page("https://example.com", owner="a")
        await runtime.aclose()
    assert context.closed


@pytest.mark.anyio
async def test_read_revalidates_page_origin() -> None:
    page = FakePage("short")
    runtime = make_runtime(FakeBrowser([FakeContext(page)]))
    opened = await runtime.open_page("https://example.com", owner="a")
    page.url = "https://forbidden.example"
    with pytest.raises(PublicToolError, match="origin"):
        await runtime.read_page(opened.handle, owner="a")
    await runtime.aclose()


@pytest.mark.anyio
async def test_browser_unicode_slice_preserves_truncation_contract() -> None:
    class UnicodePage(FakePage):
        async def evaluate(self, expression: str) -> object:
            # Simulate the actual JavaScript UTF-16 .slice, not Python slicing.
            count = int(expression.rsplit(",", 1)[1].rstrip(")"))
            return (
                ("😀" * 20)
                .encode("utf-16-le")[: count * 2]
                .decode("utf-16-le", errors="surrogatepass")
            )

    runtime = make_runtime(FakeBrowser([FakeContext(UnicodePage("unused"))]))
    opened = await runtime.open_page("https://example.com", owner="a")
    assert opened.text == "😀" * 10
    assert opened.text_truncated
    opened.model_dump_json()
    await runtime.aclose()


@pytest.mark.anyio
async def test_shutdown_shields_enclosing_anyio_cancellation() -> None:
    calls: list[str] = []
    state = RuntimeState()

    async def cleanup() -> None:
        await anyio.sleep(0)
        calls.append("closed")

    state.add_cleanup(cleanup)
    with anyio.CancelScope() as scope:
        scope.cancel()
        await state.aclose()
    assert calls == ["closed"]


@pytest.mark.anyio
async def test_direct_task_cancel_does_not_skip_remaining_cleanups() -> None:
    calls: list[str] = []
    reached = asyncio.Event()
    state = RuntimeState()

    async def waiting_cleanup() -> None:
        reached.set()
        await asyncio.Event().wait()

    state.add_cleanup(lambda: calls.append("remaining"))
    state.add_cleanup(waiting_cleanup)
    task = asyncio.create_task(state.aclose())
    await asyncio.wait_for(reached.wait(), 2)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await state.aclose()
    assert calls == ["remaining"]


def test_provider_status_is_numeric_only(caplog: pytest.LogCaptureFixture) -> None:
    class Error(RuntimeError):
        status = "STATUS_SECRET_CANARY"

    caplog.set_level(logging.WARNING)
    GitHubAdapter._record_failure(  # pyright: ignore[reportPrivateUsage]
        "repository_summary", Error("private")
    )
    assert "STATUS_SECRET_CANARY" not in caplog.text
    assert "status=None" in caplog.text


@pytest.mark.anyio
async def test_owned_github_client_is_closed_but_injected_client_is_not(tmp_path: Path) -> None:
    class Provider:
        closed = 0

        def get_repo(self, full_name_or_id: str) -> Any:
            raise AssertionError("discovery must not perform provider I/O")

        def close(self) -> None:
            self.closed += 1

    owned = Provider()

    def token_auth(token: str) -> str:
        return token

    def github_client(**kwargs: object) -> Provider:
        return owned

    fake_module = SimpleNamespace(Auth=SimpleNamespace(Token=token_auth), Github=github_client)
    settings = make_settings(
        workspace_roots=(tmp_path,),
        enable_github=True,
        github_token="FAKE",
        github_repositories=("owner/repo",),
    )
    with patch("importlib.import_module", return_value=fake_module):
        server = create_server(settings)
    async with Client(server, cache=None) as client:
        await client.list_tools()
    assert owned.closed == 1
    injected = Provider()
    adapter = GitHubAdapter("FAKE", ("owner/repo",), max_body_chars=1000, client=injected)
    adapter.close()
    assert injected.closed == 0
