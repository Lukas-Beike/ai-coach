"""Prepare Node development tools and the shared local Graphify environment."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

QUALITY_TOOLS = ("ruff", "mypy")
PIP_INPUTS = ("requirements.in", "requirements-dev.in", "requirements-graphify.in")
PYPI_URL = "https://pypi.org/pypi/{}/json"
CHECK_TIMEOUT = 10


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


def _newer(latest: str, pinned: str) -> bool:
    def key(version: str) -> tuple[int, ...] | None:
        return (
            tuple(map(int, version.split(".")))
            if re.fullmatch(r"\d+(?:\.\d+)*", version)
            else None
        )

    latest_key, pinned_key = key(latest), key(pinned)
    if latest_key is None or pinned_key is None:
        return latest != pinned
    return latest_key > pinned_key


def pip_pins(root: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for name in PIP_INPUTS:
        text = (root / name).read_text(encoding="utf-8")
        for package, version in re.findall(
            r"(?m)^([A-Za-z0-9][\w.-]*)(?:\[[^\]]*\])?==([^\s;#]+)", text
        ):
            pins[package] = version
    return pins


def pypi_latest(package: str) -> str:
    with urllib.request.urlopen(
        PYPI_URL.format(package), timeout=CHECK_TIMEOUT
    ) as response:
        return str(json.load(response)["info"]["version"])


def npm_outdated(root: Path, npm: str) -> dict[str, tuple[str, str]]:
    result = subprocess.run(
        [npm, "outdated", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    data = json.loads(result.stdout or "{}")
    return {
        name: (str(info.get("current") or info.get("wanted")), str(info["latest"]))
        for name, info in data.items()
        if info.get("latest")
    }


def newer_versions(root: Path, npm: str | None) -> list[str]:
    """Return pinned packages with a newer release; installs stay lock-based."""
    notes = []
    for package, pinned in sorted(pip_pins(root).items()):
        try:
            latest = pypi_latest(package)
        except (OSError, ValueError, KeyError) as exc:
            notes.append(f"{package}: check unavailable ({type(exc).__name__})")
            continue
        if _newer(latest, pinned):
            notes.append(f"{package} {pinned} -> {latest}")
    if npm:
        try:
            outdated = npm_outdated(root, npm)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            notes.append(f"npm: check unavailable ({type(exc).__name__})")
        else:
            notes.extend(
                f"{name} {current} -> {latest}"
                for name, (current, latest) in sorted(outdated.items())
                if _newer(latest, current)
            )
    return notes


def report_newer_versions(root: Path, npm: str | None) -> None:
    """Print available updates without changing lockfiles or the exit code."""
    print("Checking for newer package versions", flush=True)
    try:
        notes = newer_versions(root, npm)
    except Exception as exc:  # noqa: BLE001 - advisory only
        print(f"Version check skipped: {type(exc).__name__}")
        return
    if not notes:
        print("All pinned packages are current")
        return
    print("Newer versions available (installed from the lockfiles):")
    for note in notes:
        print(f"  {note}")


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
    report_newer_versions(root, npm)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
