from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


PathLike = str | Path
AllowedRoots = tuple[Path, ...]


def normalize_roots(allowed_roots: Iterable[PathLike]) -> AllowedRoots:
    """Resolve configured filesystem roots into comparable Path objects."""

    return tuple(
        Path(root).expanduser().resolve()
        for root in allowed_roots
    )


def resolve_and_validate(
    path: PathLike,
    allowed_roots: Iterable[PathLike],
) -> Path:
    """Resolve a path and ensure it is inside one configured root."""

    roots = normalize_roots(allowed_roots)
    if not roots:
        raise ValueError("No filesystem roots are configured.")

    candidate = Path(path).expanduser().resolve()

    if any(_is_within(candidate, root) for root in roots):
        return candidate

    allowed = ", ".join(str(root) for root in roots)
    raise ValueError(
        f"Path '{candidate}' is outside the allowed filesystem roots: {allowed}"
    )


def list_directory_entries(
    path: PathLike,
    allowed_roots: Iterable[PathLike],
) -> tuple[Path, list[Path]]:
    """Return a resolved directory and its stable sorted entries."""

    directory = resolve_and_validate(path, allowed_roots)

    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    if not directory.is_dir():
        raise ValueError(f"Expected a directory path, got: {directory}")

    children = sorted(
        directory.iterdir(),
        key=lambda child: (
            not child.is_dir(),
            child.name.lower(),
        ),
    )
    return directory, children


def read_file_text(
    path: PathLike,
    allowed_roots: Iterable[PathLike],
    *,
    encoding: str = "utf-8",
) -> tuple[Path, str]:
    """Return a resolved file path and its UTF-8 text content."""

    file_path = resolve_and_validate(path, allowed_roots)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Expected a file path, got: {file_path}")

    return file_path, file_path.read_text(encoding=encoding)


def write_file_text(
    path: PathLike,
    content: str,
    allowed_roots: Iterable[PathLike],
    *,
    overwrite: bool = True,
    encoding: str = "utf-8",
) -> Path:
    """Write UTF-8 text inside an allowed filesystem root."""

    file_path = resolve_and_validate(path, allowed_roots)

    if file_path.exists() and not overwrite:
        raise FileExistsError(
            f"File already exists and overwrite is false: {file_path}"
        )

    if file_path.exists() and not file_path.is_file():
        raise ValueError(f"Expected a file path, got: {file_path}")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding=encoding)
    return file_path


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
