from __future__ import annotations

import os
from pathlib import Path

MAX_INLINE_READ_BYTES = 100_000

def _parse_allowed_dirs() -> list[Path]:
    raw = os.getenv("FS_ALLOWED_DIRS")
    if raw is None or not raw.strip():
        raise RuntimeError(
            "FS_ALLOWED_DIRS must be set to one or more absolute directories."
        )

    dirs = [part.strip() for part in raw.split(os.pathsep) if part.strip()]
    if not dirs:
        raise RuntimeError(
            "FS_ALLOWED_DIRS did not contain any usable directory paths."
        )

    resolved: list[Path] = []
    for directory in dirs:
        candidate = Path(directory).expanduser()
        if not candidate.is_absolute():
            raise RuntimeError(
                f"FS_ALLOWED_DIRS entries must be absolute paths: {directory}"
            )

        path = candidate.resolve()
        if not path.exists() or not path.is_dir():
            raise RuntimeError(
                f"Allowed directory does not exist or is not a directory: {path}"
            )
        resolved.append(path)

    return resolved


ALLOWED_DIRS: list[Path] = _parse_allowed_dirs()


def _is_subpath(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_and_validate(path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    resolved = candidate.resolve()

    for allowed in ALLOWED_DIRS:
        if _is_subpath(resolved, allowed):
            return resolved

    raise ValueError(
        f"Access to '{resolved}' is not permitted; it lies outside FS_ALLOWED_DIRS."
    )


def read_file_text(path: str, max_bytes: int | None = None) -> str:
    file_path = resolve_and_validate(path)
    if not file_path.is_file():
        raise ValueError(f"'{file_path}' is not a file")

    limit = MAX_INLINE_READ_BYTES if max_bytes is None else max_bytes
    with file_path.open("rb") as handle:
        data = handle.read(limit + 1)

    text = data[:limit].decode("utf-8", errors="replace")
    if len(data) > limit:
        text += "\n...[truncated]..."
    return text


def list_directory(path: str) -> list[dict[str, str]]:
    directory = resolve_and_validate(path)
    if not directory.is_dir():
        raise ValueError(f"'{directory}' is not a directory")

    entries: list[dict[str, str]] = []
    for child in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "type": "dir" if child.is_dir() else "file",
            }
        )
    return entries
