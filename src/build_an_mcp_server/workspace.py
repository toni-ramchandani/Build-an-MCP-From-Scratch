from __future__ import annotations

import hashlib
import hmac
import mimetypes
import os
import tempfile
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath
from typing import Literal

from .errors import PublicToolError
from .models import (
    DirectoryEntry,
    DirectoryListing,
    TextFileRead,
    WorkspaceManifest,
    WorkspaceRootInfo,
    WriteFileReceipt,
)


@dataclass(frozen=True)
class WorkspaceRoot:
    root_id: str
    label: str
    path: Path


class WorkspaceAdapter:
    """Bounded filesystem I/O behind opaque public root identifiers."""

    def __init__(
        self,
        roots: tuple[Path, ...],
        *,
        max_file_read_bytes: int,
        max_directory_entries: int,
        max_write_bytes: int,
        max_digest_bytes: int,
    ) -> None:
        self._write_lock = threading.Lock()
        self._roots = tuple(
            WorkspaceRoot(root_id=f"root-{index}", label=root.name or f"root-{index}", path=root)
            for index, root in enumerate(roots, start=1)
        )
        self._by_id = {root.root_id: root for root in self._roots}
        self.max_file_read_bytes = max_file_read_bytes
        self.max_directory_entries = max_directory_entries
        self.max_write_bytes = max_write_bytes
        self.max_digest_bytes = max_digest_bytes
        self._max_directory_scan = max(1_000, max_directory_entries * 10)

    def manifest(self, *, read_only: bool) -> WorkspaceManifest:
        return WorkspaceManifest(
            roots=[
                WorkspaceRootInfo(root_id=root.root_id, label=root.label) for root in self._roots
            ],
            read_only=read_only,
            max_file_read_bytes=self.max_file_read_bytes,
            max_directory_entries=self.max_directory_entries,
        )

    def list_directory(self, root_id: str, relative_path: str, *, offset: int) -> DirectoryListing:
        root, relative, directory = self._resolve(root_id, relative_path)
        if not directory.exists():
            raise PublicToolError("The requested directory does not exist.")
        if not directory.is_dir():
            raise PublicToolError("The requested path is not a directory.")

        entries: list[DirectoryEntry] = []
        try:
            with os.scandir(directory) as scanner:
                for index, item in enumerate(scanner, start=1):
                    if index > self._max_directory_scan:
                        raise PublicToolError(
                            "The directory is too large to list safely; request a narrower path."
                        )
                    item_relative = relative / item.name
                    entries.append(
                        DirectoryEntry(
                            name=item.name,
                            kind=self._entry_kind(item),
                            relative_path=self._public_path(item_relative),
                        )
                    )
        except PublicToolError:
            raise
        except OSError as exc:
            raise PublicToolError("The directory could not be read.") from exc

        entries.sort(
            key=lambda entry: (entry.kind != "directory", entry.name.casefold(), entry.name)
        )
        page = entries[offset : offset + self.max_directory_entries]
        next_offset = offset + len(page)
        truncated = next_offset < len(entries)
        return DirectoryListing(
            root_id=root.root_id,
            relative_path=self._public_path(relative),
            offset=offset,
            returned=len(page),
            entries=page,
            truncated=truncated,
            next_offset=next_offset if truncated else None,
        )

    def read_text(self, root_id: str, relative_path: str, *, offset_bytes: int) -> TextFileRead:
        root, relative, file_path = self._resolve(root_id, relative_path)
        if not file_path.exists():
            raise PublicToolError("The requested file does not exist.")
        if not file_path.is_file():
            raise PublicToolError("The requested path is not a regular file.")

        try:
            with file_path.open("rb") as stream:
                total_bytes = os.fstat(stream.fileno()).st_size
                if offset_bytes > total_bytes:
                    raise PublicToolError(
                        "The requested byte offset is beyond the end of the file."
                    )
                if total_bytes <= self.max_digest_bytes:
                    snapshot = stream.read(self.max_digest_bytes + 1)
                    if len(snapshot) != total_bytes:
                        raise PublicToolError(
                            "The file changed while it was being read; try again."
                        )
                    candidate = snapshot[offset_bytes : offset_bytes + self.max_file_read_bytes + 4]
                    digest = hashlib.sha256(snapshot).hexdigest()
                else:
                    stream.seek(offset_bytes)
                    candidate = stream.read(self.max_file_read_bytes + 4)
                    digest = None
            content, consumed = self._decode_utf8_prefix(candidate, self.max_file_read_bytes)
        except PublicToolError:
            raise
        except (OSError, UnicodeError) as exc:
            raise PublicToolError("The file could not be read as UTF-8 text.") from exc

        next_offset = offset_bytes + consumed
        truncated = next_offset < total_bytes
        return TextFileRead(
            root_id=root.root_id,
            relative_path=self._public_path(relative),
            mime_type=mimetypes.guess_type(file_path.name)[0] or "text/plain",
            content=content,
            offset_bytes=offset_bytes,
            bytes_read=consumed,
            total_bytes=total_bytes,
            truncated=truncated,
            next_offset_bytes=next_offset if truncated else None,
            sha256=digest,
        )

    def write_text(
        self,
        root_id: str,
        relative_path: str,
        content: str,
        *,
        expected_sha256: str,
    ) -> WriteFileReceipt:
        # Serialize writes owned by this adapter; this does not lock external writers.
        with self._write_lock:
            try:
                return self._write_text(root_id, relative_path, content, expected_sha256)
            except OSError as exc:
                raise PublicToolError("The file could not be written.") from exc

    def _write_text(
        self, root_id: str, relative_path: str, content: str, expected_sha256: str
    ) -> WriteFileReceipt:
        encoded = content.encode("utf-8")
        if len(encoded) > self.max_write_bytes:
            raise PublicToolError("The proposed write exceeds the configured output budget.")

        root, relative, target = self._resolve(root_id, relative_path)
        if relative == Path("."):
            raise PublicToolError("A file path is required.")
        self._reject_symlink_components(root, relative)

        parent = target.parent
        if not parent.exists() or not parent.is_dir():
            raise PublicToolError("The destination directory does not exist.")
        if target.exists() and not target.is_file():
            raise PublicToolError("The destination is not a regular file.")

        created = not target.exists()
        if created:
            if expected_sha256 != "absent":
                raise PublicToolError("The file state changed; read it again before writing.")
        else:
            if target.stat().st_size > self.max_write_bytes:
                raise PublicToolError("The existing file is too large for a bounded write.")
            actual = self._sha256(target)
            if expected_sha256 == "absent" or not hmac.compare_digest(actual, expected_sha256):
                raise PublicToolError("The file state changed; read it again before writing.")

        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=parent, delete=False) as temporary:
                temp_name = temporary.name
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            if not created:
                os.chmod(temp_name, target.stat().st_mode)
            os.replace(temp_name, target)
            temp_name = None
        except OSError as exc:
            raise PublicToolError("The file could not be written.") from exc
        finally:
            if temp_name is not None:
                with suppress(OSError):
                    Path(temp_name).unlink(missing_ok=True)

        return WriteFileReceipt(
            root_id=root.root_id,
            relative_path=self._public_path(relative),
            created=created,
            bytes_written=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )

    def _resolve(self, root_id: str, relative_path: str) -> tuple[WorkspaceRoot, Path, Path]:
        root = self._by_id.get(root_id)
        if root is None:
            raise PublicToolError("The requested workspace root is not available.")

        relative = self._validated_relative_path(relative_path)
        try:
            candidate = (root.path / relative).resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise PublicToolError("The requested path could not be resolved safely.") from exc
        try:
            candidate.relative_to(root.path)
        except ValueError as exc:
            raise PublicToolError(
                "The requested path is outside the allowed workspace root."
            ) from exc
        return root, relative, candidate

    @staticmethod
    def _validated_relative_path(value: str) -> Path:
        if "\x00" in value:
            raise PublicToolError("The requested path is invalid.")
        relative = Path(value or ".")
        if relative.is_absolute() or relative.drive or ".." in PurePath(relative).parts:
            raise PublicToolError("The requested path must be relative and remain inside its root.")
        return relative

    @staticmethod
    def _public_path(path: Path) -> str:
        if path == Path("."):
            return "."
        return PurePosixPath(*path.parts).as_posix()

    @staticmethod
    def _entry_kind(
        entry: os.DirEntry[str],
    ) -> Literal["directory", "file", "symlink", "other"]:
        if entry.is_symlink():
            return "symlink"
        if entry.is_dir(follow_symlinks=False):
            return "directory"
        if entry.is_file(follow_symlinks=False):
            return "file"
        return "other"

    @staticmethod
    def _decode_utf8_prefix(data: bytes, limit: int) -> tuple[str, int]:
        candidate = data[:limit]
        for removed in range(0, min(4, len(candidate) + 1)):
            prefix = candidate if removed == 0 else candidate[:-removed]
            try:
                return prefix.decode("utf-8"), len(prefix)
            except UnicodeDecodeError as exc:
                if exc.reason != "unexpected end of data" or exc.start < len(prefix) - 4:
                    raise PublicToolError("The file is not valid UTF-8 text.") from exc
        raise PublicToolError("The file is not valid UTF-8 text.")

    def _sha256(self, path: Path) -> str:
        with path.open("rb") as stream:
            snapshot = stream.read(self.max_write_bytes + 1)
        if len(snapshot) > self.max_write_bytes:
            raise PublicToolError("The existing file is too large for a bounded write.")
        return hashlib.sha256(snapshot).hexdigest()

    @staticmethod
    def _reject_symlink_components(root: WorkspaceRoot, relative: Path) -> None:
        cursor = root.path
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise PublicToolError("Writes through symbolic links are not allowed.")
