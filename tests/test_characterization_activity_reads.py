"""Characterize activity pagination, recent reads and stored detail staleness.

These tests pin current behaviour, quirks included, as the parity reference for
the provider-neutral refactor. Storage is a temporary SQLite database and
providers are in-memory fakes; no server, network or real athlete data is used.
"""

import builtins
import sqlite3
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from activity_row_support import (
    SnapshotActivityRows,
    canonical_source,
)
from canonical_detail_support import NOW, seed_intervals_activity

from backend.activities.activity_reference import ActivityReferences
from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db.activity_detail_store import replace_detail_set
from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.detail_envelope import activity_equipment
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS
from backend.sync.canonical_table_reader import CanonicalTableReader

TODAY = date(2026, 5, 4)
DAY = "2026-05-04T08:00:00"
PREVIOUS_DAY = "2026-05-03T08:00:00"


class _Database:
    """Minimal unit-of-work manager over a temporary SQLite key/value table."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self.unit_of_work() as db:
            initialize_schema(db)

    @contextmanager
    def unit_of_work(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def reader(self) -> Any:
        return self.unit_of_work()

    read_snapshot = reader


class _Snapshots:
    def __init__(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    def latest_snapshot(self, _db: Any) -> Any:
        return self._snapshot


class _Feedback:
    """Simplified feedback attachment: copies dict rows and drops everything else.

    Matches on id only; the production fallback to activityId/external_id is not
    exercised here.
    """

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def list(self, _limit: int = 100) -> builtins.list[dict[str, Any]]:
        return self._rows

    def for_activity_ids(
        self, activity_ids: builtins.list[str], **_options: Any
    ) -> builtins.list[dict[str, Any]]:
        return [
            row
            for key in activity_ids
            for row in self._rows
            if str(row["activity_id"]) == key
        ]

    def attach_to_activities(
        self, activities: builtins.list[Any]
    ) -> builtins.list[dict[str, Any]]:
        by_id = {str(row["activity_id"]): row for row in self._rows}
        attached = []
        for item in activities:
            if not isinstance(item, dict):
                continue
            copy = dict(item)
            key = str(item.get("id"))
            if key in by_id:
                copy["activity_feedback"] = by_id[key]
            attached.append(copy)
        return attached


class _StorageCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = _Database(Path(directory.name) / "fixture.sqlite")


def _detail_service(
    database: Any, snapshots: _Snapshots, **kwargs: Any
) -> ActivityAnalysisReadService:
    """Serve ``activity_detail.v1`` documents from the canonical tables."""
    rows = SnapshotActivityRows(snapshots)
    return ActivityAnalysisReadService(
        database,
        rows,
        _Feedback(),
        references=ActivityReferences(database),
        canonical=canonical_source(rows, lambda: database),
        session_records=CanonicalTableReader().session_activities,
        **kwargs,
    )


def _intervals_entry(detail: dict[str, Any]) -> dict[str, Any]:
    (entry,) = detail["detail_data"]["providers"]
    assert entry["provider"] == "intervals", entry
    return entry


def _activity(activity_id: Any, start: str = DAY, **fields: Any) -> dict[str, Any]:
    return {
        "id": activity_id,
        "start_date_local": start,
        "type": "Ride",
        "moving_time": 3600,
        **fields,
    }


def _snapshot(activities: Any, raw: Any = None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "synced_at": "2026-05-04T06:00:00+00:00",
        "athlete": {},
        "recent_wellness": [],
        "recent_activities": activities,
    }
    if raw is not None:
        snapshot["raw_provider_data"] = {"activities": raw}
    return snapshot


class ActivityDetailStalenessCharacterizationTests(_StorageCase):
    RAW = _activity("ride-1", DAY, name="Threshold", moving_time=3600)

    def setUp(self) -> None:
        super().setUp()
        self._ingest(self.RAW)

    def _ingest(self, raw: dict[str, Any]) -> None:
        """Ingest the summary row the way the snapshot sync of ``raw`` does."""
        fields = {key: value for key, value in raw.items() if key != "id"}
        seed_intervals_activity(
            cast(DatabaseManager, self.database), "ride-1", **fields
        )

    def _detail(
        self, raw: list[dict[str, Any]], read_equipment: Any = None
    ) -> dict[str, Any]:
        service = _detail_service(
            self.database,
            _Snapshots(_snapshot([], raw)),
            **({} if read_equipment is None else {"read_equipment": read_equipment}),
        )
        return service.detail(
            "ride-1", garmin_status=NO_GARMIN_SYNC_STATUS, profile={}, today=TODAY
        )

    def test_detail_reads_the_equipment_of_its_own_activity(self) -> None:
        requested: list[str] = []

        def read_equipment(activity_id: str) -> dict[str, Any]:
            requested.append(activity_id)
            return {
                "items": [{"id": "bike"}, {"id": "meter"}],
                "assignments": [
                    {"activity_id": activity_id, "equipment_id": "bike"},
                    {"activity_id": activity_id, "equipment_id": "meter"},
                ],
            }

        result = self._detail([self.RAW], read_equipment)
        self.assertEqual([result["session"]["activity_id"]], requested)
        self.assertTrue(requested[0].startswith("act_"))
        self.assertEqual(["bike", "meter"], [row["id"] for row in result["equipment"]])

    def _save_streams(self) -> None:
        """Store an Intervals.icu stream set under the activity, as an old database holds it."""
        detail = ActivityStreamSet(
            provider_activity_id="ride-1",
            provenance=Provenance(
                provider=ProviderId.INTERVALS,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=None,
                recorded_by=RecordingOrigin.UNKNOWN,
                retrieved_at=datetime.fromisoformat(NOW),
                label="Intervals.icu",
            ),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={
                StreamChannel.TIME_S: (0.0, 1.0),
                StreamChannel.POWER_W: (200.0, 210.0),
            },
        )
        with cast(DatabaseManager, self.database).unit_of_work() as db:
            replace_detail_set(
                db, detail, mapper_version=1, summary_sha256=None, now=NOW
            )

    def test_intervals_detail_is_never_served(self) -> None:
        # Athlete decision 2026-11-07 (#1685): no Intervals.icu fallback, so a stored
        # copy stays unread.
        self._save_streams()
        result = self._detail([self.RAW])
        entry = _intervals_entry(result)
        self.assertEqual(([], None), (entry["kinds"], entry["load_error"]))
        self.assertFalse(entry["refreshable"])
        self.assertIsNone(result["analysis"])
        self.assertIsNone(result["streams"])


class ActivityEquipmentTests(unittest.TestCase):
    def test_every_linked_main_item_and_its_components_are_listed(self) -> None:
        equipment = {
            "items": [
                {"id": "bike"},
                {"id": "chain", "parent_id": "bike"},
                {"id": "meter"},
                {"id": "shoes"},
            ],
            "assignments": [
                {"activity_id": "a1", "equipment_id": "bike"},
                {"activity_id": "a1", "equipment_id": "meter"},
                {"activity_id": "a2", "equipment_id": "shoes"},
                {"activity_id": "a3", "equipment_id": None},
            ],
        }
        self.assertEqual(
            ["bike", "chain", "meter"],
            [row["id"] for row in activity_equipment(equipment, "a1")],
        )
        self.assertEqual([], activity_equipment(equipment, "a3"))


if __name__ == "__main__":
    unittest.main()
