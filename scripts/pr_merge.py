"""Squash-merge one pull request through auto-merge and optionally wait for it.

    python scripts/pr_merge.py <pr> [--wait MINUTES]

Arms `gh pr merge --auto --squash`; when GitHub refuses that because the PR is
already in clean status, merges it at once with `--squash` (#2776). `--wait`
then polls every 20 s in the same turn until the PR is merged, closed or a check
fails, at most MINUTES (#2795): the host's PR watcher does not reliably wake on
the merge itself. Run it only when the pr workflow allows auto-merge.
Exit 0: merged (or armed, without --wait); 1: closed unmerged or a failing
check; 2: bad input or a failed gh call; 3: still open when the wait ended.
"""

from __future__ import annotations

import argparse
import sys
import time

from gh_cli import CliError, gh, gh_json, positive_int
from pr_state import check_outcome

POLLS_PER_MINUTE = 3


def arm(number: int) -> str:
    try:
        gh("pr", "merge", str(number), "--auto", "--squash")
        return "auto-merge armed"
    except CliError as exc:
        if "clean status" not in str(exc):
            raise
    gh("pr", "merge", str(number), "--squash")
    return "already clean, merged directly"


def wait(number: int, minutes: int) -> int:
    polls = minutes * POLLS_PER_MINUTE + 1
    for poll in range(polls):
        pr = gh_json(
            "pr", "view", str(number), "--json", "state,mergeCommit,statusCheckRollup"
        )
        if pr["state"] == "MERGED":
            print(f"PR #{number} merged: {pr['mergeCommit']['oid'][:10]}")
            return 0
        checks = map(check_outcome, pr.get("statusCheckRollup") or [])
        failing = [name for name, outcome in checks if outcome == "failing"]
        if pr["state"] == "CLOSED" or failing:
            print(f"PR #{number} {pr['state'].lower()}; failing: {failing}")
            return 1
        if poll < polls - 1:
            time.sleep(60 / POLLS_PER_MINUTE)
    print(f"PR #{number} still open after {minutes} min")
    return 3


def main(argv: list[str] | None = None) -> int:
    top = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    top.add_argument("number", type=positive_int)
    top.add_argument("--wait", type=int, default=0, metavar="MINUTES")
    args = top.parse_args(argv)
    try:
        print(f"PR #{args.number}: {arm(args.number)}")
        return wait(args.number, args.wait) if args.wait > 0 else 0
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
