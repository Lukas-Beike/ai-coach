"""Shared fixture for canonical read and selector tests.

Builds a real canonical database through the backfill over the read-only wire
fixtures, and the legacy projection over the same in-memory data. This is a helper
module, not a test module. All storage is temporary.
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

from support import (
    PROVIDER_SYNCED_TEXT,
    garmin_payload_fixture,
    load_provider_fixture,
)

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.planning.context import compact_snapshot
from backend.sync.canonical_backfill import (
    DEFAULT_BATCH_SIZE,
    CanonicalBackfill,
)
from backend.sync.canonical_projection import CanonicalSnapshotProjection
from backend.sync.canonical_read_assembly import build_canonical_read
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

NOW = "2026-09-20T08:00:00+00:00"
CLOCK_AT = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
ZONE = ZoneInfo("Europe/Berlin")
MAX_BATCHES = 1000


def intervals_snapshot(*, athlete_weight: bool) -> dict[str, Any]:
    """One Intervals.icu snapshot: compact fields for the legacy and a raw section.

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


class CanonicalReadFixture(unittest.TestCase):
    def setUp(self) -> None:
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
        self.intervals_version = "row-1"
        self.zone: ZoneInfo = ZONE
        self.projection = CanonicalSnapshotProjection(
            intervals_snapshot=lambda db: self.intervals,
            intervals_version=lambda db: self.intervals_version,
            garmin_payload=lambda db: self.garmin,
            zone=lambda db: self.zone,
            clock=lambda: CLOCK_AT,
        )
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
    return build_canonical_read(legacy=case.projection, key_values=case.key_values)


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
    """Store the snapshot and Garmin payload, then backfill until complete."""
    with case.manager.unit_of_work() as db:
        db.execute(
            "INSERT INTO snapshots(payload, created_at, synced_at, recent_activity_count) "
            "VALUES (?, ?, ?, 0)",
            (json.dumps(case.intervals), NOW, str(case.intervals["synced_at"])),
        )
        store_garmin(case, db, case.garmin)
    backfill = new_backfill(case)
    for _ in range(MAX_BATCHES):
        with case.manager.unit_of_work() as db:
            if backfill.run_batch(db).done:
                return backfill
    case.fail("backfill did not finish")


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
