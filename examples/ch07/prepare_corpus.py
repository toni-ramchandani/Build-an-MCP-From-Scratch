"""Create a new synthetic corpus and its approval record outside the checkout."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from build_an_mcp_server.corpus_policy import validate_corpus


def prepare() -> dict[str, str]:
    directory = Path(tempfile.mkdtemp(prefix="mcp-security-"))
    root = directory / "corpus"
    root.mkdir()
    data = b"chapter-seven-security-canary\n"
    (root / "canary.txt").write_bytes(data)
    approval = directory / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "generation": "synthetic-g1",
                "files": {"canary.txt": hashlib.sha256(data).hexdigest()},
                "excluded": ["private.txt"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    generation = validate_corpus(root, approval)
    return {
        "directory": str(directory),
        "root": str(root),
        "approval": str(approval),
        "generation": generation,
    }


if __name__ == "__main__":
    print(json.dumps(prepare()))
