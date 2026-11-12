"""Validate the OpenSpec main specs, and optionally one change or everything.

    python scripts/spec_validate.py [--change NAME] [--all]

Always runs `validate --specs`; --change adds that change and --all adds
`validate --all`. Exit 0: all valid; 1: a validation failed; 2: bad change
name or npm is missing.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys

from check_changed import run_steps

STRICT = ["--strict", "--no-interactive"]
CHANGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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
    return run_steps(build_steps(args.change, args.all))


if __name__ == "__main__":
    sys.exit(main())
