from pathlib import Path
import os

# Maximum bytes to read when returning file content inline to avoid memory issues
MAX_INLINE_READ_BYTES = 100_000  # 100 KB


def _parse_allowed_dirs() -> list[Path]:
    """Return a list of absolute Paths that the server is allowed to access.

    Directories are provided via the FS_ALLOWED_DIRS environment variable. Multiple
    paths can be separated by os.pathsep (colon on *nix, semicolon on Windows).
    If the variable is empty or undefined, the current working directory becomes
    the sole allowed directory. This safeguards against unrestricted access.
    """
    raw = os.getenv("FS_ALLOWED_DIRS", "").strip()
    if not raw:
        return [Path.cwd().resolve()]

    dirs: list[str] = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    resolved: list[Path] = []
    for d in dirs:
        p = Path(d).expanduser().resolve()
        if not p.exists():
            # Create if missing to avoid validation failures later on.
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                # If we cannot create, skip silently – validation will handle.
                pass
        resolved.append(p)
    return resolved


ALLOWED_DIRS: list[Path] = _parse_allowed_dirs()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_subpath(path: Path, parent: Path) -> bool:
    """Return True if *path* is a sub-path (or same path) of *parent*."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_and_validate(path: str) -> Path:
    """Resolve *path* to an absolute Path and ensure it lies within ALLOWED_DIRS.

    Raises ValueError if the path is outside allowed directories or attempts
    path traversal.
    """
    p = Path(path).expanduser()
    if not p.is_absolute():
        # Interpret relative paths relative to current working directory.
        p = (Path.cwd() / p).resolve()
    else:
        p = p.resolve()

    for allowed in ALLOWED_DIRS:
        if _is_subpath(p, allowed):
            return p
    raise ValueError(f"Access to '{p}' is not permitted – outside allowed directories.")


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def read_file_text(path: str, max_bytes: int | None = None) -> str:
    """Return UTF-8 text content of *path* up to *max_bytes* (default MAX_INLINE_READ_BYTES)."""
    p = resolve_and_validate(path)
    if not p.is_file():
        raise ValueError(f"'{p}' is not a file")

    limit = MAX_INLINE_READ_BYTES if max_bytes is None else max_bytes
    with p.open("rb") as f:
        data = f.read(limit + 1)

    text = data.decode("utf-8", errors="replace")
    if len(data) > limit:
        text += "\n...[truncated]..."
    return text


def list_directory(path: str) -> list[dict[str, str]]:
    """Return a list of dictionaries with name and type for entries in *path*."""
    p = resolve_and_validate(path)
    if not p.is_dir():
        raise ValueError(f"'{p}' is not a directory")

    entries: list[dict[str, str]] = []
    for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
        entries.append({
            "name": child.name,
            "path": str(child),
            "type": "dir" if child.is_dir() else "file"
        })
    return entries 
