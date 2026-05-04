from __future__ import annotations

import mimetypes
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class AllowedRootsManifest(BaseModel):
    """Resource payload describing the filesystem boundary exposed by the server."""

    allowedRoots: list[str] = Field(
        description="Resolved filesystem roots exposed by this server."
    )
    readOnly: bool = Field(
        description="Whether write-capable filesystem tools are disabled."
    )


class DirectoryEntry(BaseModel):
    """One normalized entry in a directory listing."""

    name: str = Field(description="Base name of the entry.")
    kind: Literal["directory", "file", "other"] = Field(
        description="Filesystem entry kind."
    )
    path: str = Field(description="Resolved path.")


class DirectoryListing(BaseModel):
    """Structured result returned by the list_files tool."""

    path: str = Field(description="Resolved directory path.")
    count: int = Field(description="Number of entries returned.")
    entries: list[DirectoryEntry] = Field(
        description="Stable sorted directory entries."
    )


class TextFileRead(BaseModel):
    """Structured result returned by the read_file tool."""

    path: str = Field(description="Resolved file path.")
    mimeType: str = Field(description="Best-effort MIME type.")
    content: str = Field(description="UTF-8 text content.")
    bytesRead: int = Field(description="Number of UTF-8 bytes read.")


class WriteFileReceipt(BaseModel):
    """Structured result returned by the write_file tool."""

    path: str = Field(description="Resolved file path that was written.")
    bytesWritten: int = Field(description="Number of UTF-8 bytes written.")
    overwrite: bool = Field(
        description="Whether overwriting an existing file was allowed."
    )


def map_allowed_roots(
    roots: Iterable[Path],
    *,
    read_only: bool,
) -> AllowedRootsManifest:
    return AllowedRootsManifest(
        allowedRoots=[str(root) for root in roots],
        readOnly=read_only,
    )


def map_directory_listing(
    directory: Path,
    children: Iterable[Path],
) -> DirectoryListing:
    entries = [
        DirectoryEntry(
            name=child.name,
            kind=_entry_kind(child),
            path=str(child),
        )
        for child in children
    ]

    return DirectoryListing(
        path=str(directory),
        count=len(entries),
        entries=entries,
    )


def map_text_file(path: Path, content: str) -> TextFileRead:
    mime_type = mimetypes.guess_type(path.name)[0] or "text/plain"
    return TextFileRead(
        path=str(path),
        mimeType=mime_type,
        content=content,
        bytesRead=len(content.encode("utf-8")),
    )


def map_write_receipt(
    path: Path,
    content: str,
    overwrite: bool,
) -> WriteFileReceipt:
    return WriteFileReceipt(
        path=str(path),
        bytesWritten=len(content.encode("utf-8")),
        overwrite=overwrite,
    )


def resource_json(model: BaseModel) -> str:
    """Serialize a resource payload as stable JSON text."""

    return model.model_dump_json(indent=2)


def _entry_kind(path: Path) -> Literal["directory", "file", "other"]:
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"
