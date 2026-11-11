"""Print the orchestrator ledger line for an issue closed by a merged PR.

    python scripts/ledger_line.py --issue N --pr M [--note-file F]

Prints: <YYYY-MM-DD> #N closed via PR #M <sha> prod +a/-b tests +c/-d other
+e/-f: <first line of the note, else the PR title>. The merge commit must be
fetched locally. Exit 0 ok; 1 refused, the PR is not merged; 2 bad input or a
failed gh/git call.
"""

from __future__ import annotations

import argparse
import sys

from gh_cli import CliError, gh_json, positive_int, read_body
from line_balance import balance

LABELS = (("prod", "production"), ("tests", "tests"), ("other", "other"))


def ledger_line(issue: int, pr: int, note: str | None = None) -> str | None:
    """The ledger line, or None when the PR is not merged."""
    data = gh_json("pr", "view", str(pr), "--json", "mergedAt,mergeCommit,title,state")
    sha = (data.get("mergeCommit") or {}).get("oid")
    if data["state"] != "MERGED" or not data.get("mergedAt") or not sha:
        return None
    counts = balance(commit=sha)
    parts = " ".join(
        f"{label} +{counts[name][0]}/-{counts[name][1]}" for label, name in LABELS
    )
    text = next((ln.strip() for ln in (note or "").splitlines() if ln.strip()), None)
    return (
        f"{data['mergedAt'][:10]} #{issue} closed via PR #{pr} {sha[:8]} {parts}: "
        f"{text or data['title']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--issue", type=positive_int, required=True)
    parser.add_argument("--pr", type=positive_int, required=True)
    parser.add_argument("--note-file")
    args = parser.parse_args(argv)
    try:
        note = read_body(args.note_file) if args.note_file else None
        line = ledger_line(args.issue, args.pr, note)
    except (CliError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if line is None:
        print(f"refused: PR #{args.pr} is not merged")
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
