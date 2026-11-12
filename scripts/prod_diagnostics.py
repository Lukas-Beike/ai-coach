"""Read named fields and counts from a running app's health and diagnostics.

    python scripts/prod_diagnostics.py --url <app address> --password-file <secret file>
        [--expect-version 2.1.2] [--expect-schema 27] [--out result.json]
        [--compare previous.json] [--ca-file ca.pem]

Prints one line per check (`ok` / `FAIL` / `info`); never a response body,
cookie, password or error text. Exit 0 all ok, 1 a check failed (a count
dropped against --compare, a version mismatch, a stale or stuck sync), 2 the
app could not be reached or read.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from prod_client import ProdError, Session, read_result, write_result

COUNTS = (
    "messages",
    "workout_library",
    "competitions",
    "athlete_checkins",
    "activity_feedback",
    "change_history",
    "external_calendar_events",
)
MEMORY = ("rss_bytes", "peak_rss_bytes")
STALE_HOURS = 36
STUCK_HOURS = 2
OPEN_JOB = {"queued", "running", "pending"}


def hours_since(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return (now - then).total_seconds() / 3600


def numbers(value: Any) -> dict[str, int | float]:
    """Only numeric leaves: summaries may hold text that must not be printed."""
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(item, int | float) and not isinstance(item, bool)
    }


def plan_errors(jobs: list[dict[str, Any]]) -> dict[str, int]:
    """Error kinds (never error text) of the recent plan-sync jobs and their items."""
    kinds: dict[str, int] = {}
    for job in jobs:
        for item in [job, *(job.get("items") or [])]:
            kind = str(item.get("error_class") or "")[:64]
            if kind:
                kinds[kind] = kinds.get(kind, 0) + 1
    return kinds


def stuck_jobs(jobs: list[dict[str, Any]], now: datetime) -> int:
    return sum(
        1
        for job in jobs
        if job.get("status") in OPEN_JOB
        and (hours_since(job.get("created_at"), now) or 0) > STUCK_HOURS
    )


def extract(report: dict[str, Any], now: datetime) -> dict[str, Any]:
    database = report.get("database") or {}
    sync = report.get("sync") or {}
    plan = report.get("plan_sync") or {}
    jobs = plan.get("recent_jobs") or []
    calendar = report.get("external_calendar") or {}
    memory = numbers((report.get("runtime") or {}).get("process_memory"))
    return {
        "kind": "diagnostics",
        "generated_at": now.isoformat(timespec="seconds"),
        "version": (report.get("app") or {}).get("version"),
        "schema": database.get("schema_version"),
        "sync_error_set": bool(sync.get("last_error")),
        "providers": {
            name: {"last_sync_hours": hours_since(times.get("last_sync_at"), now)}
            for name, times in (sync.get("providers") or {}).items()
            if isinstance(times, dict)
        },
        "calendar_sync_hours": hours_since(calendar.get("last_sync_at"), now)
        if calendar.get("configured")
        else None,
        "counts": {name: database.get(name) for name in COUNTS},
        "library_state": numbers(database.get("workout_library_state")),
        "unsynced_total": plan.get("unsynced_total"),
        "units_with_error": sum(
            1 for unit in plan.get("unsynced_units") or [] if unit.get("has_error")
        ),
        "plan_error_classes": plan_errors(jobs),
        "stuck_jobs": stuck_jobs(jobs, now),
        "memory": {key: memory[key] for key in MEMORY if key in memory},
    }


def mark(ok: bool, text: str) -> tuple[str, str]:
    return ("ok" if ok else "FAIL", text)


def expected(name: str, value: Any, wanted: Any) -> tuple[str, str]:
    suffix = "" if wanted is None else f" (expected {wanted})"
    return mark(wanted in (None, value), f"{name} {value}{suffix}")


def freshness_lines(result: dict[str, Any]) -> list[tuple[str, str]]:
    lines = []
    for name, ages in result["providers"].items():
        age = ages["last_sync_hours"]
        # Intervals.icu is output-only, and an unconfigured provider never syncs.
        if age is None or name == "intervals":
            text = "never" if age is None else f"{age:.1f} h ago"
            lines.append(("info", f"provider {name} last sync {text}"))
        else:
            lines.append(
                mark(age <= STALE_HOURS, f"provider {name} last sync {age:.1f} h ago")
            )
    age = result["calendar_sync_hours"]
    if age is not None:
        lines.append(mark(age <= STALE_HOURS, f"calendar last sync {age:.1f} h ago"))
    return lines


def plan_line(result: dict[str, Any]) -> tuple[str, str]:
    kinds = ", ".join(
        f"{k} {v}" for k, v in sorted(result["plan_error_classes"].items())
    )
    text = (
        f"plan sync: {result['unsynced_total']} unsynced, "
        f"{result['units_with_error']} with error"
    )
    return ("info", f"{text}; error kinds: {kinds}" if kinds else text)


def comparison_lines(
    result: dict[str, Any], previous: dict[str, Any] | None
) -> list[tuple[str, str]]:
    """Record counts must not drop against the previous result; memory is shown."""
    before = (previous or {}).get("counts") or {}
    lines = []
    for name, count in result["counts"].items():
        old = before.get(name)
        if isinstance(count, int) and isinstance(old, int):
            lines.append(mark(count >= old, f"count {name} {old} -> {count}"))
        else:
            lines.append(("info", f"count {name} {count}"))
    old_memory = (previous or {}).get("memory") or {}
    for name, value in result["memory"].items():
        was = old_memory.get(name)
        lines.append(
            ("info", f"memory {name} {value}" + (f" (was {was})" if was else ""))
        )
    return lines


def checks(
    result: dict[str, Any],
    previous: dict[str, Any] | None,
    expect_version: str | None,
    expect_schema: int | None,
) -> list[tuple[str, str]]:
    return [
        expected("version", result["version"], expect_version),
        expected("schema", result["schema"], expect_schema),
        mark(
            not result["sync_error_set"],
            f"sync last_error set: {result['sync_error_set']}",
        ),
        *freshness_lines(result),
        mark(
            result["stuck_jobs"] == 0, f"stuck plan-sync jobs: {result['stuck_jobs']}"
        ),
        plan_line(result),
        (
            "info",
            "workout library: "
            + (
                ", ".join(
                    f"{k} {v}" for k, v in sorted(result["library_state"].items())
                )
                or "no counts"
            ),
        ),
        *comparison_lines(result, previous),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--expect-version")
    parser.add_argument("--expect-schema", type=int)
    parser.add_argument("--out")
    parser.add_argument("--compare")
    parser.add_argument("--ca-file")
    args = parser.parse_args(argv)
    try:
        previous = read_result(args.compare)
        session = Session(args.url, args.ca_file)
        health = session.get_json("/api/health")
        healthy = isinstance(health, dict) and health.get("status") == "ok"
        print(f"{'ok' if healthy else 'FAIL'} health")
        session.login(args.password_file)
        try:
            report = session.get_json("/api/diagnostics")
        finally:
            logout = session.logout()
            print(f"{'ok' if logout == 200 else 'FAIL'} logout {logout}")
        result = extract(report, datetime.now(UTC))
        write_result(args.out, result)
    except ProdError as exc:
        print(f"FAIL {exc}")
        return 2
    lines = checks(result, previous, args.expect_version, args.expect_schema)
    for state, text in lines:
        print(f"{state} {text}")
    failed = not healthy or logout != 200 or any(s == "FAIL" for s, _ in lines)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
