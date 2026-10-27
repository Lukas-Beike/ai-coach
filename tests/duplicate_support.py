"""Synthetic canonical sessions of two providers for the duplicate-flow tests.

A helper module, not a test module. Rides are written straight into the canonical
tables of a temporary database; no snapshot exists, so the tests prove that the
duplicate flow reads only canonical records. All storage is temporary.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.duplicate_inspection import DuplicateInspector
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.sync.canonical_backfill import STATE_KEY as BACKFILL_STATE_KEY
from backend.sync.canonical_table_reader import CanonicalTableReader

ZONE = ZoneInfo("Europe/Berlin")
START = datetime(2026, 9, 20, 7, 0, tzinfo=ZONE)
FETCHED_AT = "2026-09-20T10:00:00+00:00"
WAHOO_ID = "wahoo-1"
GARMIN_ID = "garmin-1"


class TablesServe:
    """A serving port for tests whose canonical tables serve reads."""

    def serves_tables(self, db: object) -> bool:
        return True


def mark_tables_serving(server: Any) -> None:
    """Record a completed backfill so the running app serves reads from the tables."""
    with server.database_manager().unit_of_work() as db:
        server.KEY_VALUE_REPOSITORY.set(
            db, BACKFILL_STATE_KEY, json.dumps({"completed_once": True})
        )


class DuplicateCase(unittest.TestCase):
    """A temporary database with a Wahoo-recorded ride and its Garmin-recorded copy."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "duplicates.db"
        self.manager = self.open_manager()
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.reader = CanonicalTableReader()
        self.inspector = DuplicateInspector(
            self.manager, self.reader, lambda: ZONE, TablesServe()
        )

    def open_manager(self) -> DatabaseManager:
        manager = DatabaseManager(self.path, sqlite3, row_factory=row_factory)
        self.addCleanup(manager.close)
        return manager

    def seed_pair(self) -> tuple[str, str]:
        """Seed the Wahoo ride and its Garmin copy as Intervals.icu activities."""
        return (
            self.seed(WAHOO_ID, recorded_by=RecordingOrigin.WAHOO),
            self.seed(GARMIN_ID, recorded_by=RecordingOrigin.GARMIN, duration_s=3580.0),
        )

    def seed(
        self,
        source_id: str,
        *,
        provider: ProviderId = ProviderId.INTERVALS,
        recorded_by: RecordingOrigin = RecordingOrigin.UNKNOWN,
        started_at: datetime = START,
        duration_s: float = 3600.0,
        distance_m: float = 30000.0,
        sport: Sport = Sport.RIDE,
        fetched_at: str = FETCHED_AT,
        name: str | None = "Synthetic ride",
    ) -> str:
        """Write one activity record with its provider record; return its session id."""
        record = ActivityRecord(
            activity_id=source_id,
            provenance=Provenance(
                provider=provider,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=source_id,
                recorded_by=recorded_by,
                retrieved_at=datetime.fromisoformat(fetched_at),
                label=None,
            ),
            sport=sport,
            environment=Environment.OUTDOOR,
            started_at=started_at,
            duration_s=duration_s,
            distance_m=distance_m,
            load=50.0,
            load_model=LoadModel.INTERVALS_TRAINING_LOAD,
            avg_hr=140.0,
            avg_power=210.0,
            name=name,
        )
        with self.manager.unit_of_work() as db:
            canonical_store.upsert_activity_record(
                db,
                record,
                local_date=started_at.astimezone(ZONE).date(),
                mapper_version=1,
                fetched_at=fetched_at,
                now=fetched_at,
            )
            canonical_store.upsert_provider_record(
                db,
                provider=provider.value,
                record_kind=ACTIVITY_RECORD_KIND,
                source_record_id=source_id,
                payload={"id": source_id},
                mapper_version=1,
                fetched_at=fetched_at,
                now=fetched_at,
            )
            row = db.execute(
                "SELECT activity_id FROM activity_records "
                "WHERE provider = ? AND provider_activity_id = ?",
                (provider.value, source_id),
            ).fetchone()
        return str(row["activity_id"])

    def merge(self, drop: str, into: str) -> None:
        """Make session ``drop`` a heuristic alias of session ``into``."""
        with self.manager.unit_of_work() as db:
            self.assertTrue(
                canonical_store.merge_activity_session(
                    db, activity_id=drop, into=into, now=FETCHED_AT
                )
            )

    def query(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        with self.manager.reader() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]
