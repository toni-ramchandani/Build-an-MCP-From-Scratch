from __future__ import annotations

from pathlib import Path

import pytest

from build_an_mcp_server.errors import PublicToolError
from build_an_mcp_server.workspace import WorkspaceAdapter


def _adapter(
    root: Path,
    *,
    read_bytes: int = 8,
    entries: int = 2,
    write_bytes: int = 16,
    digest_bytes: int | None = None,
) -> WorkspaceAdapter:
    return WorkspaceAdapter(
        (root,),
        max_file_read_bytes=read_bytes,
        max_directory_entries=entries,
        max_write_bytes=write_bytes,
        max_digest_bytes=digest_bytes if digest_bytes is not None else write_bytes,
    )


def test_manifest_exposes_opaque_root_not_absolute_path(workspace_root: Path) -> None:
    manifest = _adapter(workspace_root).manifest(read_only=True)

    assert manifest.roots[0].root_id == "root-1"
    assert manifest.roots[0].label == workspace_root.name
    assert str(workspace_root) not in manifest.model_dump_json()


def test_directory_listing_is_sorted_and_paginated(workspace_root: Path) -> None:
    (workspace_root / "z.txt").write_text("z", encoding="utf-8")
    listing = _adapter(workspace_root).list_directory("root-1", ".", offset=0)

    assert [entry.name for entry in listing.entries] == ["src", "README.md"]
    assert listing.truncated is True
    assert listing.next_offset == 2

    second = _adapter(workspace_root).list_directory("root-1", ".", offset=2)
    assert [entry.name for entry in second.entries] == ["z.txt"]
    assert second.truncated is False


def test_directory_scan_ceiling_rejects_oversized_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "oversized-directory"
    root.mkdir()

    for index in range(1_001):
        (root / f"file-{index:04}.txt").touch()

    adapter = _adapter(root, entries=2)

    with pytest.raises(PublicToolError, match="too large to list safely"):
        adapter.list_directory("root-1", ".", offset=0)


def test_read_is_utf8_safe_bounded_and_continuable(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "unicode.txt").write_text("abc€def", encoding="utf-8")
    adapter = _adapter(root, read_bytes=5)

    first = adapter.read_text("root-1", "unicode.txt", offset_bytes=0)

    assert first.content == "abc"
    assert first.bytes_read == 3
    assert first.truncated is True
    assert first.next_offset_bytes == 3

    second = adapter.read_text("root-1", "unicode.txt", offset_bytes=3)
    assert second.content.startswith("€")


def test_large_read_omits_unbounded_full_file_digest(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "large.txt").write_text("x" * 32, encoding="utf-8")

    result = _adapter(root, write_bytes=16).read_text("root-1", "large.txt", offset_bytes=0)

    assert result.sha256 is None
    assert result.truncated is True


def test_read_digest_uses_digest_budget_above_write_budget(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "mid.txt").write_text("x" * 32, encoding="utf-8")

    # File is above the write budget but below the digest budget: a digest is
    # still calculated because digest policy is decoupled from write policy.
    adapter = _adapter(root, read_bytes=64, write_bytes=16, digest_bytes=64)
    result = adapter.read_text("root-1", "mid.txt", offset_bytes=0)

    assert result.total_bytes == 32
    assert result.sha256 is not None


def test_read_above_digest_budget_omits_digest_regardless_of_write_budget(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "big.txt").write_text("x" * 32, encoding="utf-8")

    # Write budget is generous, but the smaller digest budget alone decides that
    # no full-file digest is computed for the read path.
    adapter = _adapter(root, read_bytes=64, write_bytes=64, digest_bytes=16)
    result = adapter.read_text("root-1", "big.txt", offset_bytes=0)

    assert result.total_bytes == 32
    assert result.sha256 is None


def test_write_budget_is_independent_of_digest_budget(workspace_root: Path) -> None:
    adapter = _adapter(workspace_root, write_bytes=16, digest_bytes=1024)

    with pytest.raises(PublicToolError, match="output budget"):
        adapter.write_text("root-1", "new.txt", "x" * 17, expected_sha256="absent")


@pytest.mark.parametrize("path", ["../secret.txt", "/tmp/secret.txt"])
def test_paths_cannot_escape_the_selected_root(workspace_root: Path, path: str) -> None:
    with pytest.raises(PublicToolError, match="relative|outside"):
        _adapter(workspace_root).read_text("root-1", path, offset_bytes=0)


def test_symlink_to_outside_cannot_be_read_or_written(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    link = root / "link.txt"

    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable on this platform")

    adapter = _adapter(root)

    with pytest.raises(PublicToolError, match="outside"):
        adapter.read_text("root-1", "link.txt", offset_bytes=0)

    with pytest.raises(PublicToolError, match="outside|symbolic"):
        adapter.write_text(
            "root-1",
            "link.txt",
            "changed",
            expected_sha256="absent",
        )


def test_write_requires_expected_state_and_is_atomic(workspace_root: Path) -> None:
    adapter = _adapter(workspace_root, write_bytes=64)

    created = adapter.write_text(
        "root-1",
        "notes.txt",
        "first\n",
        expected_sha256="absent",
    )
    assert created.created is True

    with pytest.raises(PublicToolError, match="state changed"):
        adapter.write_text(
            "root-1",
            "notes.txt",
            "wrong\n",
            expected_sha256="absent",
        )

    current = adapter.read_text("root-1", "notes.txt", offset_bytes=0)
    assert current.sha256 is not None

    replaced = adapter.write_text(
        "root-1",
        "notes.txt",
        "second\n",
        expected_sha256=current.sha256,
    )
    assert replaced.created is False
    assert (workspace_root / "notes.txt").read_text(encoding="utf-8") == "second\n"


def test_write_rejects_oversized_content_and_existing_file(workspace_root: Path) -> None:
    adapter = _adapter(workspace_root, write_bytes=16)
    large = workspace_root / "large.txt"
    large.write_text("x" * 32, encoding="utf-8")

    with pytest.raises(PublicToolError, match="output budget"):
        adapter.write_text(
            "root-1",
            "new.txt",
            "x" * 17,
            expected_sha256="absent",
        )

    with pytest.raises(PublicToolError, match="too large"):
        adapter.write_text(
            "root-1",
            "large.txt",
            "small",
            expected_sha256="0" * 64,
        )
