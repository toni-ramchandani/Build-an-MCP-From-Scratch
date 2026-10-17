from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, cast


class CorpusRejected(ValueError):
    """The complete candidate corpus failed approval validation."""


def _walk_error(error: OSError) -> None:
    raise error


def validate_corpus(root: Path, approval_file: Path) -> str:
    """Validate one immutable, operator-controlled generation before serving.

    These small-corpus bounds are application policy, not MCP requirements.
    The operator prevents writes during validation and while serving.
    """
    try:
        with approval_file.open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise ValueError()
        approval: Any = json.loads(raw)
        if not isinstance(approval, dict):
            raise ValueError()
        approval = cast(dict[str, Any], approval)
        if set(approval) != {"generation", "files", "excluded"}:
            raise ValueError()
        generation, files, excluded = (
            approval["generation"],
            approval["files"],
            approval["excluded"],
        )
        if not isinstance(generation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", generation):
            raise ValueError()
        if not isinstance(files, dict):
            raise ValueError()
        files = cast(dict[str, Any], files)
        if not 1 <= len(files) <= 256:
            raise ValueError()
        if not isinstance(excluded, list):
            raise ValueError()
        excluded = cast(list[Any], excluded)
        if len(excluded) > 256 or any(not isinstance(p, str) for p in excluded):
            raise ValueError()
        parents: set[str] = {"."}
        for name, digest in files.items():
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or path.as_posix() != name
                or ".." in path.parts
                or any(part.startswith(".") for part in path.parts)
                or "\\" in name
                or ":" in name
                or name in excluded
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError()
            parents.update(str(p) for p in path.parents)
        observed: set[str] = set()
        total = 0
        count = 0
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=_walk_error):
            for name in dirs + names:
                count += 1
                if count > 1024:
                    raise ValueError()
                item = Path(directory) / name
                relative = item.relative_to(root).as_posix()
                if item.is_symlink():
                    raise ValueError()
                if item.is_dir():
                    if relative not in parents:
                        raise ValueError()
                    continue
                if relative not in files or not item.is_file():
                    raise ValueError()
                with item.open("rb") as stream:
                    data = stream.read(65_537)
                total += len(data)
                if len(data) > 65_536 or total > 1_048_576:
                    raise ValueError()
                data.decode("utf-8")
                if hashlib.sha256(data).hexdigest() != files[relative]:
                    raise ValueError()
                observed.add(relative)
        if observed != set(files):
            raise ValueError()
        return generation
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise CorpusRejected("The candidate corpus does not match its approval policy.") from exc
