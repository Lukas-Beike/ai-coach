"""Characterize activity pagination, recent reads and analysis fingerprints.

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
from datetime import date
from pathlib import Path
from typing import Any, cast

from activity_row_support import (
    SnapshotActivityRows,
    canonical_source,
)
from canonical_detail_support import NOW, seed_intervals_activity

from backend.activities.activity_reference import ActivityReferences
from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
from backend.activities.workout_profile import recorded_profile
from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.detail_envelope import activity_equipment
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS
from backend.sync.activity_detail_canonical import CanonicalDetailWriter
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


def _save_canonical(database: Any, record: dict[str, Any]) -> None:
    """Store a detail record in the canonical tables, the only source analyses are read from."""
    manager = cast(DatabaseManager, database)
    seed_intervals_activity(manager, record["activity_id"])
    record = {**record, "calendar_profile": recorded_profile(record["activity"])}
    with manager.unit_of_work() as db:
        CanonicalDetailWriter().write_legacy(db, record=record, now=NOW)


def _detail_service(
    database: Any, snapshots: _Snapshots, **kwargs: Any
) -> ActivityAnalysisReadService:
    """Serve ``activity_detail.v1`` documents from the canonical tables."""
    rows = SnapshotActivityRows(snapshots)
    return ActivityAnalysisReadService(
        database,
        rows,
        _Feedback(),
        ActivityDetailStore(database),
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


BASE_SUMMARY: dict[str, Any] = {
    "start_date_local": DAY,
    "name": "Threshold",
    "type": "Ride",
    "moving_time": 3600,
}


class ActivitySummaryFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_a_sha256_hex_digest(self) -> None:
        digest = summary_fingerprint(BASE_SUMMARY)
        self.assertEqual(64, len(digest))
        int(digest, 16)

    def test_fingerprint_ignores_provider_id_and_source(self) -> None:
        first = {**BASE_SUMMARY, "id": "ride-1", "source": "Intervals.icu"}
        second = {**BASE_SUMMARY, "id": "ride-2", "source": "Garmin"}
        self.assertEqual(summary_fingerprint(first), summary_fingerprint(second))

    def test_fingerprint_changes_when_a_detail_field_changes(self) -> None:
        original = summary_fingerprint(BASE_SUMMARY)
        self.assertNotEqual(
            original, summary_fingerprint({**BASE_SUMMARY, "moving_time": 3601})
        )
        self.assertNotEqual(
            original, summary_fingerprint({**BASE_SUMMARY, "name": "Other"})
        )

    def test_fingerprint_ignores_recorded_zone_times(self) -> None:
        # Records stored before zone times entered the projection stay current.
        with_zones = {
            **BASE_SUMMARY,
            "icu_hr_zone_times": [600, 1800, 600],
            "icu_zone_times": [{"id": "Z1", "secs": 300}],
        }
        self.assertEqual(
            summary_fingerprint(BASE_SUMMARY), summary_fingerprint(with_zones)
        )

    def test_fingerprint_ignores_threshold_heart_rate(self) -> None:
        # The compact calendar rows carry no threshold, so it must not count.
        self.assertEqual(
            summary_fingerprint(BASE_SUMMARY),
            summary_fingerprint({**BASE_SUMMARY, "lthr": 168}),
        )

    def test_fingerprint_ignores_streams_and_laps(self) -> None:
        with_detail = {
            **BASE_SUMMARY,
            "streams": {"watts": [200, 210]},
            "laps": [{"name": "Lap 1", "moving_time": 600}],
        }
        changed_detail = {
            **BASE_SUMMARY,
            "streams": {"watts": [1, 2, 3]},
            "laps": [],
        }
        self.assertEqual(
            summary_fingerprint(BASE_SUMMARY), summary_fingerprint(with_detail)
        )
        self.assertEqual(
            summary_fingerprint(BASE_SUMMARY), summary_fingerprint(changed_detail)
        )

    def test_fingerprint_ignores_fields_outside_the_detail_projection(self) -> None:
        extra = {
            **BASE_SUMMARY,
            "private_field": "excluded",
            "description": "not projected",
            "activity_feedback": {"notes": "ignored"},
        }
        self.assertEqual(summary_fingerprint(BASE_SUMMARY), summary_fingerprint(extra))

    def test_non_finite_numbers_count_as_absent(self) -> None:
        # Quirk pinned: NaN is projected to None and then omitted entirely.
        without = {"name": "Threshold"}
        with_nan = {"name": "Threshold", "moving_time": float("nan")}
        self.assertEqual(summary_fingerprint(without), summary_fingerprint(with_nan))

    def test_fingerprint_does_not_depend_on_input_key_order(self) -> None:
        reordered = dict(reversed(list(BASE_SUMMARY.items())))
        self.assertEqual(
            summary_fingerprint(BASE_SUMMARY), summary_fingerprint(reordered)
        )

    def test_integer_and_float_values_fingerprint_differently(self) -> None:
        # Quirk pinned: JSON serialisation keeps 3600 and 3600.0 distinct.
        self.assertNotEqual(
            summary_fingerprint({"moving_time": 3600}),
            summary_fingerprint({"moving_time": 3600.0}),
        )

    def test_name_is_only_fingerprinted_up_to_500_characters(self) -> None:
        # Quirk pinned: the projection truncates names at 500 characters.
        prefix = "x" * 500
        self.assertEqual(
            summary_fingerprint({"name": prefix + "a"}),
            summary_fingerprint({"name": prefix + "b"}),
        )


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

    def _save_analysis(self, **overrides: Any) -> None:
        record: dict[str, Any] = {
            "activity_id": "ride-1",
            "activity": {
                "name": "Threshold",
                "moving_time": 3600,
                "streams": {"time": [0, 1], "watts": [200, 210]},
            },
            "source": "Intervals.icu",
            "observed_at": "2026-05-04T06:00:00Z",
            "summary_sha256": summary_fingerprint(self.RAW),
            "session_analysis": {"aerobic": {"status": "ok"}},
            **overrides,
        }
        with cast(DatabaseManager, self.database).unit_of_work() as db:
            CanonicalDetailWriter().write_legacy(db, record=record, now=NOW)

    def test_intervals_detail_is_never_served(self) -> None:
        # Athlete decision 2026-11-07 (#1685): no Intervals.icu fallback, so the
        # stored copy, its failure note and its summary row stay unread.
        self._save_analysis()
        ActivityDetailStore(self.database).save_failure(
            self.RAW["id"], summary_fingerprint(self.RAW), "Synthetic note", NOW
        )
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
