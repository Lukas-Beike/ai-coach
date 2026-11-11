"""Report the develop push workflow runs for a merged PR's merge commit.

    python scripts/develop_run_check.py (--pr N | --sha SHA)

One line per workflow. Exit 0: every run completed green; 1: a run failed, or
the PR is not merged; 2: bad input or a failed gh call; 3: a run is pending or
none has started yet. Failed runs get hints: a newer push run of the same
workflow supersedes it (never rerun a superseded run), and otherwise the
previous push run's conclusion and the failed job names are listed so the
caller can judge a flake.
"""

from __future__ import annotations

import argparse
import sys

from gh_cli import CliError, gh_json, positive_int

FIELDS = "databaseId,workflowName,status,conclusion,url,headSha,createdAt"
GREEN = {"success", "skipped", "neutral"}


def merge_sha(pr: int) -> str:
    data = gh_json("pr", "view", str(pr), "--json", "mergeCommit,mergedAt") or {}
    oid = (data.get("mergeCommit") or {}).get("oid")
    if not data.get("mergedAt") or not oid:
        raise LookupError(f"PR #{pr} is not merged; no merge commit to check.")
    return oid


def list_runs(*extra: str) -> list[dict]:
    return gh_json(
        "run", "list", "--branch", "develop", "--event", "push",
        "--limit", "100", "--json", FIELDS, *extra,
    )  # fmt: skip


def latest_per_workflow(runs: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for run in sorted(runs, key=lambda r: r["createdAt"]):
        latest[run["workflowName"]] = run
    return latest


def state(run: dict) -> str:
    if run["status"] != "completed":
        return "pending"
    return "green" if run["conclusion"] in GREEN else "failed"


def hints(run: dict, history: list[dict]) -> list[str]:
    same = sorted(
        (r for r in history if r["workflowName"] == run["workflowName"]),
        key=lambda r: r["createdAt"],
    )
    newer = [r for r in same if r["createdAt"] > run["createdAt"]]
    if newer:
        last = newer[-1]
        return [
            "hint superseded: newer push run "
            + f"{last['databaseId']} ({last['conclusion'] or last['status']}); "
            + "do not rerun this one"
        ]
    older = [r for r in same if r["createdAt"] < run["createdAt"]]
    jobs = gh_json("run", "view", str(run["databaseId"]), "--json", "jobs")["jobs"]
    failed = ", ".join(j["name"] for j in jobs if j["conclusion"] == "failure")
    if older:
        previous = older[-1]
        outcome = previous["conclusion"] or previous["status"]
        before = f"previous push run {previous['databaseId']} {outcome}"
    else:
        outcome, before = "", "no previous push run"
    flake = "possible flake: " if outcome == "success" else ""
    return [f"hint {flake}{before}; failed jobs: {failed or 'none listed'}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pr", type=positive_int)
    group.add_argument("--sha")
    args = parser.parse_args(argv)
    try:
        sha = args.sha or merge_sha(args.pr)
        runs = latest_per_workflow(list_runs("--commit", sha))
        if not runs:
            print(f"pending: no develop push runs for {sha[:8]} yet")
            return 3
        failing = any(state(run) == "failed" for run in runs.values())
        history = list_runs() if failing else []
        states = []
        for name, run in sorted(runs.items()):
            states.append(state(run))
            result = run["conclusion"] or run["status"]
            print(f"{name}: {states[-1]} ({result}) {run['url']}")
            if states[-1] == "failed":
                for line in hints(run, history):
                    print(f"  {line}")
        if failing:
            return 1
        return 3 if "pending" in states else 0
    except LookupError as exc:
        print(f"refused: {exc}")
        return 1
    except (CliError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
