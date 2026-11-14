"""Measure `Test and publish container image` run times; read-only (#2816).

    python scripts/ci_run_stats.py --since 2026-11-14T08:17 --until 2026-11-14T11:20
        [--event pull_request] [--all-conclusions] [--first-attempts] [--queue]

The one definition for CI-speed baselines (docs/testing.md): publish-container.yml
runs created in [since, until) UTC for the event, successful only unless
--all-conclusions; a re-run counts with its whole span and is reported, and
--first-attempts leaves re-runs out; run time is
created_at to updated_at in minutes; median and p90 are linear-interpolated
(`statistics.quantiles`, inclusive). Each successful run's type comes from its
non-skipped jobs: `full` runs mobile or tablet browser shards, `desktop-only`
only desktop shards, `docs-only` neither browser shards nor container unit
tests, `other` everything else (a reused run). --queue adds job queue times
(created_at to started_at). Exit 0: printed; 1: no run in the window; 2: bad
input, a failed gh call, or more runs than the API returns (split the window).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime

from gh_cli import CliError, gh

WORKFLOW = "publish-container.yml"
SHARD = re.compile(r"^Browser checks \((\S+)(?: \d+/\d+)?\)$")
CONTAINER = "Container unit tests"
API_CAP = 1000  # the runs endpoint returns at most this many for a filter
TYPES = ("full", "desktop-only", "docs-only", "other")


def stamp(text: str) -> datetime:
    return datetime.fromisoformat(text)


def seconds(start: str, end: str) -> float:
    return (stamp(end) - stamp(start)).total_seconds()


def median_p90(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return values[0], values[0]
    return statistics.median(values), statistics.quantiles(
        values, n=10, method="inclusive"
    )[-1]


def run_type(jobs: list[dict]) -> str:
    ran = [job["name"] for job in jobs if job.get("conclusion") != "skipped"]
    projects = {m[1] for name in ran if (m := SHARD.match(name))}
    if projects - {"desktop"}:
        return "full"
    if projects:
        return "desktop-only"
    return "other" if CONTAINER in ran else "docs-only"


def lines(gh_args: list[str]) -> list[dict]:
    return [json.loads(line) for line in gh(*gh_args).splitlines() if line.strip()]


def fetch_runs(since: datetime, until: datetime, event: str) -> list[dict]:
    window = f"{since:%Y-%m-%dT%H:%M:%SZ}..{until:%Y-%m-%dT%H:%M:%SZ}"
    path = f"repos/{{owner}}/{{repo}}/actions/workflows/{WORKFLOW}/runs"
    query = f"?event={event}&created={window}&per_page=100"
    runs = lines(["api", "--paginate", path + query, "--jq", ".workflow_runs[]"])
    if len(runs) >= API_CAP:
        raise CliError(f"{len(runs)} runs reach the API cap; split the window")
    return [
        run
        for run in runs
        if since <= stamp(run["created_at"]) < until and run["status"] == "completed"
    ]


def fetch_jobs(run_id: int) -> list[dict]:
    path = f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs?per_page=100"
    return lines(["api", "--paginate", path, "--jq", ".jobs[]"])


def report(runs: list[dict], jobs: dict[int, list[dict]], queue: bool) -> list[str]:
    """Lines for the counted runs; `jobs` holds the successful runs' jobs."""
    minutes = {r["id"]: seconds(r["created_at"], r["updated_at"]) / 60 for r in runs}
    median, p90 = median_p90(list(minutes.values()))
    out = [f"runs {len(runs)}: median {median:.1f} min, p90 {p90:.1f} min"]
    conclusions = Counter(r["conclusion"] for r in runs)
    if set(conclusions) != {"success"}:
        out.append(
            "  conclusions: "
            + ", ".join(f"{k} {n}" for k, n in sorted(conclusions.items()))
        )
    groups: dict[str, list[int]] = {}
    for run_id, run_jobs in jobs.items():
        groups.setdefault(run_type(run_jobs), []).append(run_id)
    for kind in (kind for kind in TYPES if kind in groups):
        ids = groups[kind]
        counts = [sum(j["conclusion"] != "skipped" for j in jobs[i]) for i in ids]
        med, _ = median_p90([minutes[i] for i in ids])
        out.append(
            f"  {kind}: {len(ids)} runs, median {med:.1f} min, "
            f"jobs per run {min(counts)}-{max(counts)}"
        )
    waits = [
        seconds(j["created_at"], j["started_at"])
        for run_jobs in jobs.values()
        for j in run_jobs
        if j.get("started_at") and j["conclusion"] != "skipped"
    ]
    if queue and waits:
        q_median, q_p90 = median_p90(waits)
        out.append(f"job queue: median {q_median:.0f} s, p90 {q_p90:.0f} s")
    return out


def utc(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=utc, required=True)
    parser.add_argument("--until", type=utc, required=True)
    parser.add_argument("--event", default="pull_request")
    parser.add_argument("--all-conclusions", action="store_true")
    parser.add_argument("--first-attempts", action="store_true")
    parser.add_argument("--queue", action="store_true")
    args = parser.parse_args(argv)
    try:
        found = [
            r
            for r in fetch_runs(args.since, args.until, args.event)
            if args.all_conclusions or r["conclusion"] == "success"
        ]
        # Re-runs among the runs the conclusion filter keeps (Gitar finding).
        reruns = sum(r.get("run_attempt", 1) > 1 for r in found)
        runs = [
            r for r in found if not args.first_attempts or r.get("run_attempt", 1) == 1
        ]
        jobs = {
            r["id"]: fetch_jobs(r["id"]) for r in runs if r["conclusion"] == "success"
        }
    except (CliError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"{WORKFLOW} {args.event} {args.since:%Y-%m-%dT%H:%MZ}..{args.until:%Y-%m-%dT%H:%MZ}"
    )
    if reruns:
        verdict = "left out" if args.first_attempts else "included"
        print(f"  re-run attempts {verdict}: {reruns}")
    if not runs:
        print("no run in the window")
        return 1
    for line in report(runs, jobs, args.queue):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
