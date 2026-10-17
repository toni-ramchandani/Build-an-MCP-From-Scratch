from pathlib import Path

import pytest

from build_an_mcp_server.errors import PublicToolError
from build_an_mcp_server.workspace import WorkspaceAdapter


def test_real_stale_digest_and_replace_failure_preserve_target_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = WorkspaceAdapter(
        (tmp_path,),
        max_file_read_bytes=64,
        max_write_bytes=64,
        max_digest_bytes=64,
        max_directory_entries=20,
    )
    adapter.write_text("root-1", "notes.txt", "first\n", expected_sha256="absent")
    first = adapter.read_text("root-1", "notes.txt", offset_bytes=0)
    assert first.sha256 is not None
    second = adapter.write_text("root-1", "notes.txt", "second\n", expected_sha256=first.sha256)
    with pytest.raises(PublicToolError, match="state changed"):
        adapter.write_text("root-1", "notes.txt", "stale\n", expected_sha256=first.sha256)
    assert (tmp_path / "notes.txt").read_text() == "second\n"

    def failed_replace(source: str, target: Path) -> None:
        assert Path(source).read_bytes() == b"third\n"
        raise OSError("synthetic-path-secret")

    monkeypatch.setattr("build_an_mcp_server.workspace.os.replace", failed_replace)
    with pytest.raises(PublicToolError, match="could not be written") as error:
        adapter.write_text("root-1", "notes.txt", "third\n", expected_sha256=second.sha256)
    assert "synthetic-path-secret" not in str(error.value)
    assert (tmp_path / "notes.txt").read_text() == "second\n"
    assert [p.name for p in tmp_path.iterdir()] == ["notes.txt"]
