"""Shared fixture for canonical read and selector tests.

Builds a real canonical database through the backfill over the read-only wire
fixtures. This is a helper module, not a test module. All storage is temporary.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from intervals_compaction import compact_snapshot, ingest_intervals_partial_snapshot
from intervals_plan_stub import intervals_test_world
from support import (
    PROVIDER_SYNCED_TEXT,
    garmin_payload_fixture,
    load_provider_fixture,
)

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import wahoo_ingest_plan
from backend.sync.canonical_backfill import (
    DEFAULT_BATCH_SIZE,
    CanonicalBackfill,
)
from backend.sync.canonical_ingest import ingest_plan
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.canonical_wiring import build_canonical_read
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

NOW = "2026-09-20T08:00:00+00:00"
CLOCK_AT = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
ZONE = ZoneInfo("Europe/Berlin")
MAX_BATCHES = 1000


def intervals_snapshot(*, athlete_weight: bool) -> dict[str, Any]:
    """One Intervals.icu snapshot: the compact fields and a raw section.

    The athlete weight is optional. It falls on the same day as a wellness weight
    and has its own observation key, so both values are kept in the tables.
    """
    athlete = load_provider_fixture("intervals/athlete.json")
    if not athlete_weight:
        athlete = {key: value for key, value in athlete.items() if key != "weight"}
    activities = load_provider_fixture("intervals/activities.json")
    wellness = load_provider_fixture("intervals/wellness.json")
    events = load_provider_fixture("intervals/events.json")
    compact = compact_snapshot(
        athlete,
        activities,
        wellness,
        events,
        all_sync_days=42,
        synced_at=PROVIDER_SYNCED_TEXT,
    )
    return {
        **compact,
        "raw_provider_data": {
            "activities": activities,
            "wellness": wellness,
            "athlete": athlete,
        },
    }


class LatestSnapshot:
    """Stands in for the snapshot repository reader over the fixture's payload."""

    def __init__(self, fixture: CanonicalReadFixture) -> None:
        self._fixture = fixture

    def latest_snapshot(self, db: Any) -> dict[str, Any] | None:
        return self._fixture.intervals


class FixtureProfile:
    """Stands in for the athlete profile; its time zone follows the fixture."""

    def __init__(self, fixture: CanonicalReadFixture) -> None:
        self._fixture = fixture

    def get(self) -> dict[str, Any]:
        return {"timezone": str(self._fixture.zone)}


class CanonicalReadFixture(unittest.TestCase):
    def setUp(self) -> None:
        # Provider-neutral logic runs over Intervals.icu-shaped records as one provider.
        self.enterContext(intervals_test_world())
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.manager = DatabaseManager(
            Path(self.temporary.name) / "read.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.intervals: dict[str, Any] = intervals_snapshot(athlete_weight=False)
        self.garmin: dict[str, Any] = garmin_payload_fixture()
        self.zone: ZoneInfo = ZONE
        self.table = CanonicalTableReader()

    def read(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        with self.manager.reader() as db:
            return fn(db, *args, **kwargs)

    def write(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        with self.manager.unit_of_work() as db:
            return fn(db, *args, **kwargs)

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.manager.reader() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(sql, params)


def make_selector(case: CanonicalReadFixture) -> Any:
    return build_canonical_read(
        key_values=case.key_values,
        profile=FixtureProfile(case),
    )


def new_backfill(case: CanonicalReadFixture) -> CanonicalBackfill:
    return CanonicalBackfill(
        key_values=case.key_values,
        zone_provider=lambda: case.zone,
        clock=lambda: NOW,
        batch_size=DEFAULT_BATCH_SIZE,
    )


def store_garmin(case: CanonicalReadFixture, db: Any, payload: dict[str, Any]) -> None:
    """Write a Garmin collection through the per-element writer."""
    GarminSnapshotWriter(case.key_values, lambda: case.zone).write(db, payload)


def populate(case: CanonicalReadFixture) -> CanonicalBackfill:
    """Store the Intervals.icu-shaped snapshot and Garmin payload, then complete the backfill."""
    with case.manager.unit_of_work() as db:
        db.execute(
            "INSERT INTO snapshots(payload, created_at, synced_at, recent_activity_count) "
            "VALUES (?, ?, ?, 0)",
            (json.dumps(case.intervals), NOW, str(case.intervals["synced_at"])),
        )
        ingest_intervals_partial_snapshot(db, case.intervals, zone=case.zone)
        store_garmin(case, db, case.garmin)
    backfill = new_backfill(case)
    for _ in range(MAX_BATCHES):
        with case.manager.unit_of_work() as db:
            if backfill.run_batch(db).done:
                return backfill
    case.fail("backfill did not finish")


def drop_intervals_activities(case: CanonicalReadFixture) -> None:
    """Leave the Intervals.icu activity copies out of what `populate` ingests.

    The Garmin activities stay, so the tables serve the Garmin records alone.
    """
    case.intervals["raw_provider_data"]["activities"] = []


# The Wahoo recording of the fixture's Garmin-only run 910002 (18:05 Berlin time).
WAHOO_RUN_COPY = "990002"


def store_wahoo_run_copy(case: CanonicalReadFixture) -> None:
    """Ingest a Wahoo copy of Garmin's 910002, so linking bundles a Garmin+Wahoo pair."""
    payload = {
        "synced_at": NOW,
        "workouts": [
            {
                "id": WAHOO_RUN_COPY,
                "starts": "2026-10-09T16:05:00.000Z",
                "workout_type_id": 1,
                "workout_summary": {
                    "duration_active_accum": "2400",
                    "distance_accum": "7600",
                },
            }
        ],
    }
    with case.manager.unit_of_work() as db:
        ingest_plan(
            db,
            wahoo_ingest_plan(payload, zone=case.zone),
            retrieved_at=datetime.fromisoformat(NOW),
            deletion_window=None,
            zone=case.zone,
        )


def first_activity_name(case: CanonicalReadFixture) -> str:
    return str(case.intervals["raw_provider_data"]["activities"][0]["name"])


def without_garmin_history(inputs: Any) -> Any:
    """The inputs without the canonical Garmin performance history.

    The canonical history also holds days the legacy snapshot cache never kept (a
    superset accepted on 2026-10-25), so byte-parity tests of the rest of the
    context leave it out; its own parity is pinned in
    tests/test_garmin_performance_history_canonical.py.
    """
    if inputs is None or inputs.garmin is None:
        return inputs
    return replace(inputs, garmin=replace(inputs.garmin, performance_history={}))
