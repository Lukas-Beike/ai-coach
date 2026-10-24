"""Prepare Node development tools and the shared local Graphify environment."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    worker = str(root / "scripts/graphify_local.py")
    steps = [
        ("Node dependencies", [npm, "ci", "--ignore-scripts"] if npm else None),
        ("Graphify setup", [sys.executable, worker, "setup"]),
        ("Graphify update", [sys.executable, worker, "update"]),
    ]
    failed = False
    for label, command in steps:
        print(f"Preparing {label}", flush=True)
        try:
            if command is None:
                raise FileNotFoundError("npm/npm.cmd unavailable")
            code = subprocess.run(command, cwd=root, check=False).returncode
        except OSError as exc:
            print(f"{label} failed: {exc}", file=sys.stderr)
            code = 1
        if code:
            print(f"{label} failed (exit {code})", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
