from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceRootInfo(BaseModel):
    """One opaque public identifier for a configured workspace root."""

    root_id: str = Field(description="Opaque root identifier used by workspace tools.")
    label: str = Field(description="Human-readable root label; never an absolute path.")


class WorkspaceManifest(BaseModel):
    """Public description of the configured workspace boundary."""

    roots: list[WorkspaceRootInfo]
    read_only: bool = Field(description="Whether mutation tools are absent from this surface.")
    max_file_read_bytes: int
    max_directory_entries: int


class DirectoryEntry(BaseModel):
    """One bounded entry in a workspace directory listing."""

    name: str
    kind: Literal["directory", "file", "symlink", "other"]
    relative_path: str


class DirectoryListing(BaseModel):
    """Stable structured result for a directory listing."""

    root_id: str
    relative_path: str
    offset: int
    returned: int
    entries: list[DirectoryEntry]
    truncated: bool
    next_offset: int | None


class TextFileRead(BaseModel):
    """A bounded UTF-8 file chunk and the information needed to continue."""

    root_id: str
    relative_path: str
    mime_type: str
    content: str
    offset_bytes: int
    bytes_read: int
    total_bytes: int
    truncated: bool
    next_offset_bytes: int | None
    sha256: str | None = Field(
        description=(
            "Digest of the complete file when the file is within the bounded mutation budget; "
            "otherwise null."
        )
    )


class WriteFileReceipt(BaseModel):
    """Evidence returned after an explicitly enabled atomic workspace write."""

    root_id: str
    relative_path: str
    created: bool
    bytes_written: int
    sha256: str


class GitHubRepositorySummary(BaseModel):
    """Stable, provider-independent repository metadata."""

    repository: str
    description: str | None
    default_branch: str
    primary_language: str | None
    visibility: str
    archived: bool
    open_issues_count: int
    updated_at: str


class GitHubIssueContext(BaseModel):
    """Bounded issue or pull-request context from one allowed repository."""

    repository: str
    number: int
    kind: Literal["issue", "pull_request"]
    title: str
    state: str
    author: str | None
    labels: list[str]
    body: str
    body_truncated: bool
    html_url: str


class BrowserPageSummary(BaseModel):
    """Bounded page data associated with an opaque application handle."""

    handle: str
    url: str
    url_truncated: bool
    title: str
    title_truncated: bool
    text: str
    text_truncated: bool
    expires_in_seconds: int = Field(
        description="Inactivity window before this application-owned handle expires."
    )


class BrowserCloseReceipt(BaseModel):
    """Idempotent close result for a browser handle."""

    handle: str
    closed: bool
