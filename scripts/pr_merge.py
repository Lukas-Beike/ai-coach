"""Squash-merge one develop pull request through auto-merge and optionally wait.

    python scripts/pr_merge.py <pr> [--wait MINUTES]

Arms `gh pr merge --auto --squash` pinned to the current head, unless it is
armed already; when GitHub refuses because the PR is already in clean status,
merges that head at once with `--squash` (#2776). `--wait` then polls every 20 s
in the same turn until the PR is merged or closed, a check fails or new
feedback (comment or review) arrives, at most MINUTES (#2795): the host's PR
watcher does not reliably wake on the merge itself.
Exit 0: merged (or armed, without --wait); 1: refused (base is not develop),
closed unmerged, a failing check or new feedback; 2: bad input or a failed gh
call; 3: still open when the wait ended.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from gh_cli import CliError, gh, gh_json, positive_int
from pr_state import check_outcome

FIELDS = "state,baseRefName,headRefOid,autoMergeRequest,mergeCommit,statusCheckRollup,comments,reviews"
POLLS_PER_MINUTE = 3


def view(number: int) -> dict[str, Any]:
    return gh_json("pr", "view", str(number), "--json", FIELDS) or {}


def feedback(pr: dict[str, Any]) -> int:
    return len(pr.get("comments") or []) + len(pr.get("reviews") or [])


def arm(number: int, pr: dict[str, Any]) -> str:
    if pr.get("autoMergeRequest"):
        return "auto-merge already armed"
    pin = ["--squash", "--match-head-commit", pr["headRefOid"]]
    try:
        gh("pr", "merge", str(number), "--auto", *pin)
        return f"auto-merge armed on {pr['headRefOid'][:10]}"
    except CliError as exc:
        if "clean status" not in str(exc):
            raise
    gh("pr", "merge", str(number), *pin)
    return f"already clean, merged {pr['headRefOid'][:10]} directly"


def wait(number: int, minutes: int, seen: int) -> int:
    polls = minutes * POLLS_PER_MINUTE + 1
    for poll in range(polls):
        pr = view(number)
        if pr.get("state") == "MERGED":
            oid = (pr.get("mergeCommit") or {}).get("oid") or "?"
            print(f"PR #{number} merged: {oid[:10]}")
            return 0
        checks = map(check_outcome, pr.get("statusCheckRollup") or [])
        failing = [name for name, outcome in checks if outcome == "failing"]
        if pr.get("state") == "CLOSED" or failing or feedback(pr) > seen:
            print(f"PR #{number} {pr.get('state')}; failing: {failing}; read pr-state")
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
        pr = view(args.number)
        if pr.get("baseRefName") != "develop":
            print(f"refused: base is {pr.get('baseRefName')}, not develop")
            return 1
        if pr.get("state") == "OPEN":
            print(f"PR #{args.number}: {arm(args.number, pr)}")
            if args.wait <= 0:
                return 0
        return wait(args.number, max(args.wait, 0), feedback(pr))
    except (CliError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
