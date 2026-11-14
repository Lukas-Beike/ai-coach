"""Read named fields and counts from a running app's health and diagnostics.

    python scripts/prod_diagnostics.py --url <app address> --password-file <secret file>
        [--expect-version 2.1.2] [--expect-schema 27] [--out result.json]
        [--compare previous.json] [--ca-file ca.pem]
    python scripts/prod_diagnostics.py --url <app address> --password-file <secret file>
        --section <name> [--section <name> ...]

Prints one line per check (`ok` / `FAIL` / `info`); never a response body,
cookie, password or error text. Exit 0 all ok, 1 a check failed (a count
dropped against --compare, a version mismatch, a stale or stuck sync), 2 the
app could not be reached or read. `--section <name>` (repeatable) prints,
instead of the checks, only the allow-listed counts, flags, state words and
ages in hours (a `*_at` time as `*_hours`) of the sections in SECTION_FIELDS;
the state words in FAIL_STATES and a missing section print as FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
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
# Storage and runtime health compared between releases (#2848).
STORAGE = ("file_bytes", "wal_bytes", "data_dir_free_bytes")
STALE_HOURS = 36
STUCK_HOURS = 2
OPEN_JOB = {"queued", "running", "pending"}
# What `--section` prints of a section: dotted paths of numbers and flags, and
# state words from STATES; nothing else of the section is printed (#2779, #2781).
SECTION_FIELDS = {
    "decoupling_eligibility": re.compile(
        r"status|available|current|days|groups\.(ride|run)/(outdoor|indoor)\."
        r"(sessions|without_streams|evaluation_error|counts\.[a-z0-9_]+"
        r"|max_half_distribution\.[a-z0-9_]+\.(n|p[0-9]+))"
    ),
    # Storage and runtime health for the post-release check (#2848).
    "database": re.compile(
        "|".join(("schema_version", *COUNTS, *STORAGE))
        + r"|(workout_library_state|stored_payload_bytes)\.[a-z_]+"
    ),
    "runtime": re.compile(r"uptime_s|malloc_arena_max|process_memory\.[a-z_]+"),
    "recovery_copies": re.compile(
        r"status|available|count|newest_age_hours|total_bytes"
    ),
    "garmin_past_workout_removal": re.compile(
        r"status|one_time_done|checked|removed|last_run_hours|last_outcome"
        r"|past_links_pending"
    ),
    "stream_backfill": re.compile(
        r"status|(garmin|wahoo)\.(candidates|with_streams|stored|no_file|no_streams"
        r"|skipped_by_error|blocked|cursor|finished)"
    ),
    # Per recording origin and sport (their vocabularies, in backend/canonical):
    # files, and files per FIT message or field number.
    "fit_inventory": re.compile(
        r"status|(garmin|wahoo|strava|zwift|manual|upload|unknown)\."
        r"(ride|run|swim|walk|hike|strength|row|nordic_ski|alpine_ski|yoga|other"
        r"|unknown)\.(files|(messages|unmapped_fields|developer_fields)\.[0-9.]+)"
    ),
}
STATES = {
    "ready",
    "pending",
    "ok",
    "skipped",
    "finished",
    "in_progress",
    "not_started",
    "failed",
    "unavailable",
    "blocked",
}
FAIL_STATES = {"failed", "unavailable", "blocked"}


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
    runtime = report.get("runtime") or {}
    memory = numbers(runtime.get("process_memory"))
    copies = report.get("recovery_copies") or {}
    storage = {name: database.get(name) for name in STORAGE}
    storage |= {name: runtime.get(name) for name in ("uptime_s", "malloc_arena_max")}
    storage |= {f"recovery_{name}": value for name, value in copies.items()}
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
        "storage": numbers(storage),
    }


def leaves(value: Any, path: str = "") -> list[tuple[str, Any]]:
    """The dotted path and value of every leaf, sorted by path."""
    if not isinstance(value, dict):
        return [(path, value)]
    return [
        leaf
        for key in sorted(value, key=str)
        for leaf in leaves(value[key], f"{path}.{key}" if path else str(key))
    ]


def printable(value: Any) -> bool:
    if isinstance(value, str):
        return value in STATES
    return value is None or isinstance(value, int | float)


def aged(leaf: tuple[str, Any], now: datetime) -> tuple[str, Any]:
    """A `*_at` time as its age `*_hours`; every other leaf unchanged."""
    path, value = leaf
    if not (path.endswith("_at") and isinstance(value, str)):
        return leaf
    age = hours_since(value, now)
    return path[:-3] + "_hours", None if age is None else round(age, 1)


def section_lines(
    report: dict[str, Any], name: str, now: datetime | None = None
) -> list[tuple[str, str]]:
    """The allow-listed fields of one section, sorted by path."""
    section = report.get(name)
    if not isinstance(section, dict):
        return [("FAIL", f"section {name} missing")]
    allowed = SECTION_FIELDS[name]
    lines = []
    for leaf in leaves(section):
        path, value = aged(leaf, now or datetime.now(UTC))
        if allowed.fullmatch(path) and printable(value):
            state = "FAIL" if value in FAIL_STATES else "info"
            lines.append((state, f"{name}.{path} {json.dumps(value)}"))
    return lines or [("info", f"section {name} empty")]


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
    """Record counts must not drop against the previous result.

    Memory and storage (database, WAL, free space, uptime, arena limit,
    recovery copies) are shown with the previous value.

    The calendar sync refills external_calendar_events from today on every
    refresh, so a drop there is no data loss.
    """
    before = (previous or {}).get("counts") or {}
    lines = []
    for name, count in result["counts"].items():
        old = before.get(name)
        if isinstance(count, int) and isinstance(old, int):
            line = mark(count >= old, f"count {name} {old} -> {count}")
            calendar = name == "external_calendar_events"
            lines.append(("info", line[1]) if calendar else line)
        else:
            lines.append(("info", f"count {name} {count}"))
    return lines + shown_lines(result, previous)


def shown_lines(
    result: dict[str, Any], previous: dict[str, Any] | None
) -> list[tuple[str, str]]:
    """Memory and storage values, each with the previous release's value."""
    lines = []
    for group in ("memory", "storage"):
        old = (previous or {}).get(group) or {}
        for name, value in (result.get(group) or {}).items():
            was = old.get(name)
            suffix = "" if was is None else f" (was {was})"
            lines.append(("info", f"{group} {name} {value}{suffix}"))
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
    parser.add_argument("--section", action="append", choices=sorted(SECTION_FIELDS))
    args = parser.parse_args(argv)
    checks_asked = (args.out, args.compare, args.expect_version, args.expect_schema)
    if args.section and any(value is not None for value in checks_asked):
        parser.error("--section prints sections; it runs no checks or results")
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
        if not args.section:
            result = extract(report, datetime.now(UTC))
            write_result(args.out, result)
    except ProdError as exc:
        print(f"FAIL {exc}")
        return 2
    lines = (
        [line for name in args.section for line in section_lines(report, name)]
        if args.section
        else checks(result, previous, args.expect_version, args.expect_schema)
    )
    for state, text in lines:
        print(f"{state} {text}")
    failed = not healthy or logout != 200 or any(s == "FAIL" for s, _ in lines)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
