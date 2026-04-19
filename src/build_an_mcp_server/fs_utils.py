from pathlib import Path
import os

MAX_INLINE_READ_BYTES = 100_000  # 100 KB


def _parse_allowed_dirs() -> list[Path]:
    """Return the absolute directories the server is allowed to access.

    Directories are provided via the FS_ALLOWED_DIRS environment variable.
    Multiple paths can be separated by os.pathsep (colon on Unix-like systems,
    semicolon on Windows). The variable must be set, and each configured path
    must already exist.
    """
    raw = os.getenv("FS_ALLOWED_DIRS")
    if raw is None or not raw.strip():
        raise RuntimeError(
            "FS_ALLOWED_DIRS must be set to one or more absolute directories."
        )

    dirs: list[str] = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    if not dirs:
        raise RuntimeError(
            "FS_ALLOWED_DIRS did not contain any usable directory paths."
        )

    resolved: list[Path] = []
    for d in dirs:
        candidate = Path(d).expanduser()
        if not candidate.is_absolute():
            raise RuntimeError(
                f"FS_ALLOWED_DIRS entries must be absolute paths: {d}"
            )

        p = candidate.resolve()
        if not p.exists() or not p.is_dir():
            raise RuntimeError(
                f"Allowed directory does not exist or is not a directory: {p}"
            )

        resolved.append(p)

    return resolved


ALLOWED_DIRS: list[Path] = _parse_allowed_dirs()


def _is_subpath(path: Path, parent: Path) -> bool:
    """Return True if *path* is inside *parent* or is the same path."""
    return path.is_relative_to(parent)


def resolve_and_validate(path: str) -> Path:
    """Resolve *path* and ensure it stays within ALLOWED_DIRS.

    Raises ValueError if the path falls outside the configured allow-list.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    resolved = candidate.resolve()

    for allowed in ALLOWED_DIRS:
        if _is_subpath(resolved, allowed):
            return resolved

    raise ValueError(
        f"Access to '{resolved}' is not permitted; it lies outside ALLOWED_DIRS."
    )


def read_file_text(path: str, max_bytes: int | None = None) -> str:
    """Return UTF-8 text content of *path* up to *max_bytes* bytes."""
    p = resolve_and_validate(path)
    if not p.is_file():
        raise ValueError(f"'{p}' is not a file")

    limit = MAX_INLINE_READ_BYTES if max_bytes is None else max_bytes
    with p.open("rb") as f:
        data = f.read(limit + 1)

    text = data[:limit].decode("utf-8", errors="replace")
    if len(data) > limit:
        text += "\n...[truncated]..."
    return text


def list_directory(path: str) -> list[dict[str, str]]:
    """Return structured metadata for entries in *path*."""
    p = resolve_and_validate(path)
    if not p.is_dir():
        raise ValueError(f"'{p}' is not a directory")

    entries: list[dict[str, str]] = []
    for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "type": "dir" if child.is_dir() else "file",
            }
        )
    return entries
