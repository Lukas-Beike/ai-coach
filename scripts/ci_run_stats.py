"""Measure `Test and publish container image` run times; read-only (#2816).

    python scripts/ci_run_stats.py --since 2026-11-14T08:17 --until 2026-11-14T11:20
        [--event pull_request] [--all-conclusions] [--queue]

The one definition for CI-speed baselines (docs/testing.md): runs of
publish-container.yml created in [since, until) UTC for the event, successful
only unless --all-conclusions; run time is created_at to updated_at in minutes;
median and p90 are linear-interpolated (`statistics.quantiles`, inclusive).
Each run's type comes from its non-skipped jobs: `full` runs mobile or tablet
browser shards, `desktop-only` only desktop shards, `docs-only` neither browser
shards nor container unit tests, `other` everything else (a reused run).
--queue adds job queue times (created_at to started_at). Exit 0: printed;
2: bad input or a failed gh call.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import UTC, datetime

from gh_cli import CliError, gh

WORKFLOW = "publish-container.yml"
SHARD = re.compile(r"^Browser checks \((\S+) \d+/\d+\)$")
CONTAINER = "Container unit tests"


def stamp(text: str) -> datetime:
    return datetime.fromisoformat(text)


def minutes(start: str, end: str) -> float:
    return (stamp(end) - stamp(start)).total_seconds() / 60


def median_p90(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0], values[0]) if values else (0.0, 0.0)
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


def fetch_runs(since: datetime, until: datetime, event: str, every: bool) -> list[dict]:
    window = f"{since:%Y-%m-%dT%H:%M:%SZ}..{until:%Y-%m-%dT%H:%M:%SZ}"
    path = f"repos/{{owner}}/{{repo}}/actions/workflows/{WORKFLOW}/runs"
    query = f"?event={event}&created={window}&per_page=100"
    runs = lines(["api", "--paginate", path + query, "--jq", ".workflow_runs[]"])
    return [
        run
        for run in runs
        if since <= stamp(run["created_at"]) < until
        and run.get("status") == "completed"
        and (every or run.get("conclusion") == "success")
    ]


def fetch_jobs(run_id: int) -> list[dict]:
    path = f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs?per_page=100"
    return lines(["api", "--paginate", path, "--jq", ".jobs[]"])


def report(runs: list[dict], jobs: dict[int, list[dict]], queue: bool) -> list[str]:
    times = sorted(minutes(r["created_at"], r["updated_at"]) for r in runs)
    median, p90 = median_p90(times)
    out = [f"runs {len(times)}: median {median:.1f} min, p90 {p90:.1f} min"]
    by_type: dict[str, list[dict]] = {}
    for run in runs:
        by_type.setdefault(run_type(jobs[run["id"]]), []).append(run)
    for kind in ("full", "desktop-only", "docs-only", "other"):
        if group := by_type.get(kind):
            counts = [
                sum(j.get("conclusion") != "skipped" for j in jobs[r["id"]])
                for r in group
            ]
            med, _ = median_p90(
                [minutes(r["created_at"], r["updated_at"]) for r in group]
            )
            out.append(
                f"  {kind}: {len(group)} runs, median {med:.1f} min, "
                f"jobs per run {min(counts)}-{max(counts)}"
            )
    if queue:
        waits = [
            minutes(j["created_at"], j["started_at"]) * 60
            for run in runs
            for j in jobs[run["id"]]
            if j.get("started_at") and j.get("conclusion") != "skipped"
        ]
        q_median, q_p90 = median_p90(sorted(waits))
        out.append(f"job queue: median {q_median:.0f} s, p90 {q_p90:.0f} s")
    return out


def utc(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=utc, required=True)
    parser.add_argument("--until", type=utc, required=True)
    parser.add_argument("--event", default="pull_request")
    parser.add_argument("--all-conclusions", action="store_true")
    parser.add_argument("--queue", action="store_true")
    args = parser.parse_args(argv)
    try:
        runs = fetch_runs(args.since, args.until, args.event, args.all_conclusions)
        jobs = {run["id"]: fetch_jobs(run["id"]) for run in runs}
    except (CliError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"{WORKFLOW} {args.event} {args.since:%Y-%m-%d %H:%M}..{args.until:%H:%M} UTC"
    )
    for line in report(runs, jobs, args.queue):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
