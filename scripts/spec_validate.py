"""Validate the OpenSpec main specs, and optionally one change or everything.

    python scripts/spec_validate.py [--change NAME] [--all]

Always runs `validate --specs`; --change adds that change and --all adds
`validate --all`. First, every `tests/<file>.py:<name>` evidence reference in
the main specs must name a class or test that the file defines. Exit 0: all valid; 1: a validation failed; 2: bad change
name or npm is missing.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from check_changed import run_steps

STRICT = ["--strict", "--no-interactive"]
CHANGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DEFINES = r"^\s*(?:(?:async\s+)?def\s+{0}\b|class\s+{0}\b|{0}\s*[:=])"
EVIDENCE = re.compile(r"(tests/[\w/]+\.py):{1,2}([A-Za-z_][\w.]*\w)")


def stale_evidence(root: Path) -> list[str]:
    """Spec lines that cite a missing test file, class or test function."""
    stale = []
    for spec in sorted((root / "openspec" / "specs").glob("*/spec.md")):
        lines = spec.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            for path, name in EVIDENCE.findall(line):
                source = root / path
                text = source.read_text(encoding="utf-8") if source.is_file() else ""
                if not text or any(
                    not re.search(DEFINES.format(re.escape(part)), text, re.MULTILINE)
                    for part in name.split(".")
                ):
                    where = spec.relative_to(root).as_posix()
                    stale.append(f"{where}:{number}: {path}:{name}")
    return stale


def build_steps(change: str | None, everything: bool) -> list[tuple[str, list[str]]]:
    npm = shutil.which("npm") or "npm"  # npm.cmd on Windows
    base = [npm, "run", "openspec", "--", "validate"]
    steps = [("specs", [*base, "--specs", *STRICT])]
    if change:
        steps.append((f"change {change}", [*base, change, *STRICT]))
    if everything:
        steps.append(("all", [*base, "--all", *STRICT]))
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--change", help="also validate this change")
    parser.add_argument("--all", action="store_true", help="also validate all")
    args = parser.parse_args(argv)
    # Review text and check output carry emoji; a Windows console is cp1252.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.change is not None and not CHANGE_NAME.match(args.change):
        print("error: --change takes a name such as add-example", file=sys.stderr)
        return 2
    stale = stale_evidence(Path(__file__).resolve().parents[1])
    for entry in stale:
        print(f"stale evidence {entry}")
    if stale:
        return 1
    return run_steps(build_steps(args.change, args.all))


if __name__ == "__main__":
    sys.exit(main())
