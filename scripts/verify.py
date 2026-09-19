"""Run deterministic source, runtime and installed-package gates used by CI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

COMMANDS = (
    (sys.executable, "-m", "ruff", "format", "--check", "."),
    (sys.executable, "-m", "ruff", "check", "."),
    (sys.executable, "-m", "pyright"),
    (sys.executable, "-m", "pytest", "-m", "not integration", "-ra"),
    (sys.executable, str(Path(__file__).with_name("verify_installed.py"))),
)


def _run(command: tuple[str, ...]) -> None:
    print(f"\n$ {' '.join(command)}", flush=True)
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    for command in COMMANDS:
        _run(command)


if __name__ == "__main__":
    main()
