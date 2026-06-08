from __future__ import annotations

import json
from pathlib import Path

import pytest

from build_an_mcp_server.fs_utils import (
    list_directory_entries,
    read_file_text,
    resolve_and_validate,
)
from build_an_mcp_server.normalizers import (
    map_allowed_roots,
    map_directory_listing,
    map_text_file,
    resource_json,
)


def test_resolve_and_validate_accepts_absolute_file_inside_root(
    workspace_root: Path,
) -> None:
    target = workspace_root / "readme.md"

    resolved = resolve_and_validate(target, (workspace_root,))

    assert resolved == target.resolve()


def test_resolve_and_validate_rejects_path_outside_root(
    workspace_root: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the allowed"):
        resolve_and_validate(outside, (workspace_root,))


def test_resolve_and_validate_rejects_empty_roots(workspace_root: Path) -> None:
    with pytest.raises(ValueError, match="No filesystem roots"):
        resolve_and_validate(workspace_root / "readme.md", ())


def test_read_file_text_returns_resolved_path_and_text(workspace_root: Path) -> None:
    resolved, text = read_file_text(workspace_root / "readme.md", (workspace_root,))

    assert resolved == (workspace_root / "readme.md").resolve()
    assert text == "# Project\nA sample project.\n"


def test_list_directory_entries_returns_stable_directory_first_order(
    workspace_root: Path,
) -> None:
    directory, children = list_directory_entries(workspace_root, (workspace_root,))

    assert directory == workspace_root.resolve()
    assert [child.name for child in children] == ["src", "readme.md"]


def test_map_text_file_returns_server_owned_shape(workspace_root: Path) -> None:
    path = workspace_root / "readme.md"
    payload = map_text_file(path, path.read_text(encoding="utf-8"))

    dumped = payload.model_dump()
    assert dumped["path"] == str(path)
    assert dumped["content"] == "# Project\nA sample project.\n"
    assert dumped["bytesRead"] == len(dumped["content"].encode("utf-8"))
    assert dumped["mimeType"] in {"text/markdown", "text/plain"}


def test_resource_json_serializes_allowed_roots_manifest(workspace_root: Path) -> None:
    manifest = map_allowed_roots((workspace_root,), read_only=True)

    payload = json.loads(resource_json(manifest))

    assert payload == {
        "allowedRoots": [str(workspace_root)],
        "readOnly": True,
    }


def test_map_directory_listing_returns_stable_entries(workspace_root: Path) -> None:
    directory, children = list_directory_entries(workspace_root, (workspace_root,))

    payload = map_directory_listing(directory, children).model_dump()

    assert payload["path"] == str(workspace_root)
    assert payload["count"] == 2
    assert [entry["name"] for entry in payload["entries"]] == ["src", "readme.md"]
