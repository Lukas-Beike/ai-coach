"""Print the line balance of a diff as production, tests and other lines.

    python scripts/line_balance.py [--base origin/develop] [--head HEAD] [--commit SHA]

Compares base...head, or SHA^..SHA with --commit. Production is backend/,
server.py and public/; tests are tests/ and e2e/; everything else (docs,
skills, scripts, configuration) is other. Binary files count as 0. Exit 0 ok,
2 bad input or a failed git call.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gh_cli import CliError, git

PRODUCTION = ("backend/", "public/", "server.py")
TESTS = ("tests/", "e2e/")


def category(path: str) -> str:
    if path.startswith(PRODUCTION):
        return "production"
    return "tests" if path.startswith(TESTS) else "other"


def balance(
    base: str = "origin/develop",
    head: str = "HEAD",
    commit: str | None = None,
    cwd: Path | None = None,
) -> dict[str, tuple[int, int]]:
    """Added and removed lines per category for base...head, or for one commit."""
    span = f"{commit}^..{commit}" if commit else f"{base}...{head}"
    totals = {"production": [0, 0], "tests": [0, 0], "other": [0, 0]}
    for line in git("diff", "--numstat", "--no-renames", span, cwd=cwd).splitlines():
        added, removed, path = line.split("\t", 2)
        if added.isdigit() and removed.isdigit():  # binary files show "-"
            totals[category(path)][0] += int(added)
            totals[category(path)][1] += int(removed)
    return {name: (added, removed) for name, (added, removed) in totals.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/develop")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--commit")
    args = parser.parse_args(argv)
    try:
        result = balance(args.base, args.head, args.commit)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for name, (added, removed) in result.items():
        print(f"{name}: +{added} / -{removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
