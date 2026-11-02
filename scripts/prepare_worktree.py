"""Prepare Node development tools and the shared local Graphify environment."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

QUALITY_TOOLS = ("ruff", "mypy")


def quality_requirements(lock_text: str) -> str:
    """Return the hash-locked blocks for the quality tools and mypy's dependencies.

    The full development lock needs SQLCipher, which has no Windows wheel.
    """
    blocks = re.split(r"(?m)^(?=[A-Za-z0-9][\w.-]*==)", lock_text)[1:]
    selected = [
        block
        for block in blocks
        if block.partition("==")[0] in QUALITY_TOOLS
        or re.search(r"(?m)^\s*#.*mypy", block)
    ]
    names = {block.partition("==")[0] for block in selected}
    if not set(QUALITY_TOOLS) <= names:
        raise OSError("requirements-dev.txt does not pin the quality tools")
    return "".join(selected)


def install_quality_tools(root: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="quality-tools-") as directory:
        lock = Path(directory) / "requirements.txt"
        lock.write_text(
            quality_requirements(
                (root / "requirements-dev.txt").read_text(encoding="utf-8")
            ),
            encoding="utf-8",
        )
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--only-binary=:all:",
            "--disable-pip-version-check",
            "--no-input",
            "-r",
            str(lock),
        ]
        return subprocess.run(command, cwd=root, check=False).returncode


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    worker = str(root / "scripts/graphify_local.py")
    steps = [
        ("Node dependencies", [npm, "ci", "--ignore-scripts"] if npm else None),
        ("Graphify setup", [sys.executable, worker, "setup"]),
        ("Graphify update", [sys.executable, worker, "update", "--preparation"]),
        ("Quality tools", lambda: install_quality_tools(root)),
    ]
    failed = False
    for label, command in steps:
        print(f"Preparing {label}", flush=True)
        try:
            if command is None:
                raise FileNotFoundError("npm/npm.cmd unavailable")
            code = (
                command()
                if callable(command)
                else subprocess.run(command, cwd=root, check=False).returncode
            )
        except OSError as exc:
            print(f"{label} failed: {exc}", file=sys.stderr)
            code = 1
        if code:
            print(f"{label} failed (exit {code})", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
