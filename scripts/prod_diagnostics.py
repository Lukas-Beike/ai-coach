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


def extract(report: dict[str, Any], now: datetime) -> dict[str, Any]:
    database = report.get("database") or {}
    sync = report.get("sync") or {}
    plan = report.get("plan_sync") or {}
    jobs = plan.get("recent_jobs") or []
    error_classes: dict[str, int] = {}
    for job in jobs:
        for item in [job, *(job.get("items") or [])]:
            kind = item.get("error_class")
            if kind:
                error_classes[str(kind)[:64]] = error_classes.get(str(kind)[:64], 0) + 1
    stuck = sum(
        1
        for job in jobs
        if job.get("status") in OPEN_JOB
        and (hours_since(job.get("created_at"), now) or 0) > STUCK_HOURS
    )
    providers = {
        name: {
            "last_sync_hours": hours_since(times.get("last_sync_at"), now),
            "last_plan_sync_hours": hours_since(times.get("last_plan_sync_at"), now),
        }
        for name, times in (sync.get("providers") or {}).items()
        if isinstance(times, dict)
    }
    calendar = report.get("external_calendar") or {}
    return {
        "kind": "diagnostics",
        "generated_at": now.isoformat(timespec="seconds"),
        "version": (report.get("app") or {}).get("version"),
        "schema": database.get("schema_version"),
        "sync_error_set": bool(sync.get("last_error")),
        "providers": providers,
        "calendar_sync_hours": hours_since(calendar.get("last_sync_at"), now)
        if calendar.get("configured")
        else None,
        "counts": {name: database.get(name) for name in COUNTS},
        "library_state": numbers(database.get("workout_library_state")),
        "unsynced_total": plan.get("unsynced_total"),
        "units_with_error": sum(
            1 for unit in plan.get("unsynced_units") or [] if unit.get("has_error")
        ),
        "plan_error_classes": error_classes,
        "stuck_jobs": stuck,
        "memory": numbers((report.get("runtime") or {}).get("process_memory")),
    }


def checks(
    result: dict[str, Any],
    previous: dict[str, Any] | None,
    expect_version: str | None,
    expect_schema: int | None,
) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []

    def add(ok: bool, text: str) -> None:
        lines.append(("ok" if ok else "FAIL", text))

    add(
        expect_version in (None, result["version"]),
        f"version {result['version']}"
        + (f" (expected {expect_version})" if expect_version else ""),
    )
    add(
        expect_schema in (None, result["schema"]),
        f"schema {result['schema']}"
        + (f" (expected {expect_schema})" if expect_schema is not None else ""),
    )
    add(
        not result["sync_error_set"], f"sync last_error set: {result['sync_error_set']}"
    )
    for name, ages in result["providers"].items():
        age = ages["last_sync_hours"]
        # Intervals.icu is output-only, and an unconfigured provider never syncs.
        if age is None or name == "intervals":
            text = "never" if age is None else f"{age:.1f} h ago"
            lines.append(("info", f"provider {name} last sync {text}"))
        else:
            add(age <= STALE_HOURS, f"provider {name} last sync {age:.1f} h ago")
    if result["calendar_sync_hours"] is not None:
        age = result["calendar_sync_hours"]
        add(age <= STALE_HOURS, f"calendar last sync {age:.1f} h ago")
    add(result["stuck_jobs"] == 0, f"stuck plan-sync jobs: {result['stuck_jobs']}")
    kinds = ", ".join(
        f"{k} {v}" for k, v in sorted(result["plan_error_classes"].items())
    )
    lines.append(
        (
            "info",
            f"plan sync: {result['unsynced_total']} unsynced, "
            f"{result['units_with_error']} with error"
            + (f"; error kinds: {kinds}" if kinds else ""),
        )
    )
    before = (previous or {}).get("counts") or {}
    for name, count in result["counts"].items():
        old = before.get(name)
        if isinstance(count, int) and isinstance(old, int):
            add(count >= old, f"count {name} {old} -> {count}")
        else:
            lines.append(("info", f"count {name} {count}"))
    old_memory = (previous or {}).get("memory") or {}
    for name, value in result["memory"].items():
        was = old_memory.get(name)
        lines.append(
            ("info", f"memory {name} {value}" + (f" (was {was})" if was else ""))
        )
    return lines


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
