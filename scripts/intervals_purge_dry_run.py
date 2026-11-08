"""Dry run of the Intervals.icu ingest purge (#1728) on a COPY of the database.

The script opens the copy with the key in ``APP_PASSWORD`` (never printed), as
the application does. Inside one transaction it upgrades the schema if needed,
reconciles the local session load, runs the identical purge (``run_purge`` with
the rating-backfill gate ignored), reconciles the local load again, and then
rolls everything back: the file is left unchanged. It prints a counts-only JSON
report to stdout: Intervals.icu rows per table and kind before and after,
re-keyed and lost athlete items, the Garmin rating backfill counts, deleted and
re-bundled sessions, and the shift of the stored local load (M6) with the local
fitness and fatigue (M7) of the latest load day. No ids, names or dates.

Run it on a disposable copy only, in a container without network access::

    docker network create --internal ai-coach-dry-run
    docker run --rm --network ai-coach-dry-run -e APP_PASSWORD \\
      -v "<copy directory>:/copy" \\
      -v "<repository>/scripts/intervals_purge_dry_run.py:/app/scripts/intervals_purge_dry_run.py:ro" \\
      pacecraft:local python -m scripts.intervals_purge_dry_run /copy/intervals-coach.db

``-e APP_PASSWORD`` passes the variable from the calling shell without writing
its value on the command line. The copy directory must be writable for SQLite's
temporary WAL files; the database file itself is not modified.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.feedback import ActivityFeedbackService
from backend.athlete.profile import timezone_name
from backend.db import canonical_store, row_factory
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.repositories import ActivityFeedbackRepository, KeyValueRepository
from backend.db.schema import configure_cipher
from backend.performance.fitness_fatigue import local_fitness_fatigue
from backend.performance.local_tss import METHOD_ID as LOAD_METHOD_ID
from backend.performance.source_policy import preferences_from_profile
from backend.sync.garmin_rating_backfill import rating_backfill_counts
from backend.sync.intervals_purge import (
    intervals_row_counts,
    purge_status,
    run_purge,
)
from backend.sync.local_load import LocalLoadStage, daily_local_loads

# The local load stage writes both kinds; only the session load is compared.
_SESSION_LOAD = "session_load"


class _RolledBack(Exception):
    """Carries the report out of the transaction, which it rolls back."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("dry run rolled back")
        self.report = report


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _profile(db: Any, key_values: KeyValueRepository) -> dict[str, Any]:
    try:
        value = json.loads(key_values.get(db, "profile") or "{}")
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def _session_loads(db: Any) -> dict[str, float]:
    """The stored local session load per owning session id."""
    return {
        str(row["owner_record_id"]): float(row["value"])
        for row in canonical_store.derived_observation_rows(db, LOAD_METHOD_ID)
        if row["metric"] == _SESSION_LOAD
    }


def _load_shift(
    db: Any, before: Mapping[str, float], after: Mapping[str, float]
) -> dict[str, int]:
    """Compare session loads; a session that moved compares on its survivor."""
    effective = canonical_store.effective_session_ids(db, list(before))
    shift = {"changed": 0, "removed": 0, "added": 0, "unchanged": 0, "rekeyed": 0}
    matched: set[str] = set()
    for session, value in before.items():
        target = effective.get(session, session)
        if target not in after:
            shift["removed"] += 1
            continue
        matched.add(target)
        if abs(after[target] - value) > 1e-6:
            shift["changed"] += 1
        else:
            shift["unchanged"] += 1
            shift["rekeyed"] += target != session
    shift["added"] = len(set(after) - matched)
    return shift


def _fitness(loads: Mapping[str, float], day: date, zone: str) -> dict[str, Any]:
    curve = local_fitness_fatigue(
        loads,
        (),
        {},
        start=day,
        end=day,
        today=day + timedelta(days=1),
        complete_before=day + timedelta(days=1),
        timezone=zone,
    )
    rows = curve.get("days") or []
    row = rows[-1] if rows else {}
    return {key: row.get(key) for key in ("fitness", "fatigue", "form")}


def _fitness_shift(
    before: Mapping[str, float], after: Mapping[str, float], zone: str
) -> dict[str, Any]:
    days = [*before, *after]
    if not days:
        return {"status": "unavailable", "reason": "no_local_load"}
    # The latest day with a local load, before or after; the date is not reported.
    day = date.fromisoformat(max(days))
    return {
        "status": "available",
        "day": "latest_local_load_day",
        "before": _fitness(before, day, zone),
        "after": _fitness(after, day, zone),
    }


def _local_load_stage(
    manager: DatabaseManager, key_values: KeyValueRepository, zone: str
) -> LocalLoadStage:
    feedback = ActivityFeedbackService(
        manager, ActivityFeedbackRepository(_now)
    )  # Its reads join the open transaction.
    return LocalLoadStage(
        key_values=key_values,
        zone_provider=lambda: ZoneInfo(zone),
        clock=_now,
        preferences=lambda db: preferences_from_profile(_profile(db, key_values)),
        session_feedback=lambda keys: feedback.for_activity_ids(
            keys, sessions_only=True
        ),
    )


def _report(
    db: Any, manager: DatabaseManager, key_values: KeyValueRepository
) -> dict[str, Any]:
    zone = timezone_name(_profile(db, key_values).get("timezone"))
    stage = _local_load_stage(manager, key_values, zone)
    rating = rating_backfill_counts(db, key_values)
    state = purge_status(db, key_values)["status"]
    rows_before = intervals_row_counts(db)
    stage.run_batch(db)
    loads_before, days_before = _session_loads(db), daily_local_loads(db)
    counts = run_purge(db, key_values, now=_now(), ignore_gate=True) or {}
    stage.run_batch(db)
    loads_after, days_after = _session_loads(db), daily_local_loads(db)
    return {
        "rolled_back": True,
        "purge_state": state,
        "rating_backfill": rating,
        "intervals_rows": {"before": rows_before, "after": intervals_row_counts(db)},
        "purge": counts,
        "local_load": {
            "sessions_before": len(loads_before),
            "sessions_after": len(loads_after),
            "sessions": _load_shift(db, loads_before, loads_after),
            "days_changed": sum(
                1
                for day in {*days_before, *days_after}
                if abs(days_before.get(day, 0.0) - days_after.get(day, 0.0)) > 1e-6
            ),
            "fitness_fatigue": _fitness_shift(days_before, days_after, zone),
        },
    }


def dry_run(
    path: Path,
    password: str,
    *,
    backend: Any,
    configure: Callable[[Any, str], None] | None = configure_cipher,
) -> dict[str, Any]:
    """Run the purge on ``path`` inside one transaction, roll back, return the report."""
    if not path.is_file():
        raise FileNotFoundError("database copy not found")
    manager = DatabaseManager(
        path,
        backend,
        password=password,
        configure=configure,
        row_factory=row_factory,
        reader_count=1,
        persist_connections=False,
    )
    key_values = KeyValueRepository(_now)
    try:
        with manager.unit_of_work() as db:
            migrate_schema(db)
            raise _RolledBack(_report(db, manager, key_values))
    except _RolledBack as rolled_back:
        return rolled_back.report
    finally:
        manager.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database", type=Path, help="path to a COPY of the database")
    arguments = parser.parse_args(argv)
    password = os.environ.get("APP_PASSWORD", "")
    if len(password) < 12:
        print("APP_PASSWORD must be set (at least 12 characters).", file=sys.stderr)
        return 2
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
    except ImportError:
        print("SQLCipher is required; run the script in the image.", file=sys.stderr)
        return 2
    report = dry_run(arguments.database, password, backend=sqlcipher)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
