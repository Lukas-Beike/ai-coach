"""Activity readers served by the canonical selector instead of snapshot sections."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import Mock

from canonical_read_support import (
    CanonicalReadFixture,
    LatestSnapshot,
    make_selector,
    populate,
)

from backend.activities.duplicate_inspection import DuplicateInspector
from backend.activities.duplicate_service import DuplicateActivityService
from backend.activities.read_service import ActivityReadService
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.http_api.compact_activity_rows import (
    CompactActivityRows,
    compact_activity_rows,
)
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND

TODAY = date(2026, 10, 13)
REMOVAL_AT = "2026-10-13T09:00:00+00:00"
WAHOO_ID = "wahoo-dup-1"
GARMIN_ID = "garmin-dup-1"


def _duplicate_pair() -> list[dict[str, Any]]:
    base = {
        "type": "Ride",
        "moving_time": 7200,
        "distance": 60000.0,
        "icu_training_load": 80,
    }
    return [
        {
            **base,
            "id": WAHOO_ID,
            "source": "Wahoo",
            "start_date_local": "2026-10-26T07:00:00",
        },
        {
            **base,
            "id": GARMIN_ID,
            "source": "Garmin",
            "start_date_local": "2026-10-26T07:03:00",
            "moving_time": 7180,
        },
    ]


def _by_id(row: dict[str, Any]) -> str:
    return str(row["id"])


class _Feedback:
    def attach_to_activities(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return items


class _ActivityCase(CanonicalReadFixture):
    def setUp(self) -> None:
        super().setUp()
        pair = _duplicate_pair()
        self.intervals["raw_provider_data"]["activities"].extend(pair)
        self.intervals["recent_activities"].extend(compact_activity_rows(pair))
        self.snapshots = LatestSnapshot(self)

    def strip_canonical_sections(self) -> None:
        """Keep the sync marker only, as a snapshot that lost the canonical sections."""
        self.intervals = {"synced_at": self.intervals["synced_at"]}

    def read_service(self, selector: Any) -> ActivityReadService:
        return ActivityReadService(
            self.manager,
            CompactActivityRows(selector),
            _Feedback(),
        )

    def inspector(self, selector: Any) -> DuplicateInspector:
        return DuplicateInspector(self.manager, self.table, lambda: self.zone, selector)

    def ids(self, rows: Any) -> set[str]:
        return {str(row["id"]) for row in rows}


class DuplicateRemovalTests(_ActivityCase):
    def _service(self, selector: Any) -> DuplicateActivityService:
        return DuplicateActivityService(
            self.manager,
            self.inspector(selector),
            lambda: REMOVAL_AT,
            Mock(),
        )

    def _payload(self, selector: Any) -> dict[str, Any]:
        pair = self.inspector(selector).latest() or {}
        return {
            key: pair[key]
            for key in ("canonical_id", "duplicate_id", "snapshot_synced_at")
        }

    def test_removal_is_recorded_in_the_tables_and_leaves_the_snapshot(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.assertIn(GARMIN_ID, self.ids(self.read(selector.activity_rows)))
        snapshot = self.intervals["synced_at"]

        remote = Mock()
        self._service(selector).delete(self._payload(selector), remote)

        remote.delete_activity.assert_called_once_with(GARMIN_ID)
        for source in (selector, self.table):
            rows = self.read(source.activity_rows)
            self.assertNotIn(GARMIN_ID, self.ids(rows))
            self.assertIn(WAHOO_ID, self.ids(rows))
        # The snapshot is an ingestion artefact and is not rewritten by a delete.
        self.assertEqual(self.intervals["synced_at"], snapshot)
        self.assertIn(
            GARMIN_ID, self.ids(self.intervals["raw_provider_data"]["activities"])
        )
        recent = self.read_service(selector).recent(today=TODAY)["activities"]
        self.assertNotIn(GARMIN_ID, self.ids(recent))

    def test_removal_tombstones_record_session_and_provider_record(self) -> None:
        populate(self)
        selector = make_selector(self)
        self._service(selector).delete(self._payload(selector), Mock())

        for table in ("activity_records", "provider_records", "activity_sessions"):
            with self.subTest(table=table):
                self.assertTrue(
                    self.rows(f"SELECT state FROM {table} WHERE state = 'deleted'")
                )
        kept = self.rows(
            "SELECT state FROM activity_records WHERE provider_activity_id = ?",
            (WAHOO_ID,),
        )
        self.assertEqual([row["state"] for row in kept], ["active"])

    def test_inspector_stops_reporting_the_removed_pair(self) -> None:
        populate(self)
        selector = make_selector(self)
        before = self.inspector(selector).latest()
        self.assertEqual((before or {}).get("duplicate_id"), GARMIN_ID)
        self._service(selector).delete(self._payload(selector), Mock())
        self.assertIsNone(self.inspector(selector).latest())

    def test_mark_activity_deleted_reports_whether_anything_changed(self) -> None:
        populate(self)
        kwargs = {
            "record_kind": ACTIVITY_RECORD_KIND,
            "provider_activity_id": GARMIN_ID,
            "now": REMOVAL_AT,
        }
        provider = ProviderId.INTERVALS.value
        self.assertTrue(
            self.write(canonical_store.mark_activity_deleted, provider, **kwargs)
        )
        self.assertFalse(
            self.write(canonical_store.mark_activity_deleted, provider, **kwargs)
        )
        unknown = {**kwargs, "provider_activity_id": "never-stored"}
        self.assertFalse(
            self.write(canonical_store.mark_activity_deleted, provider, **unknown)
        )


class PendingAndTableReadTests(_ActivityCase):
    def test_read_service_lists_nothing_until_the_tables_serve(self) -> None:
        pending = self.read_service(make_selector(self))
        self.assertEqual(pending.page(today=TODAY)["activities"], [])
        self.assertEqual(pending.recent(today=TODAY)["activities"], [])

        populate(self)
        tables = self.read_service(make_selector(self))

        expected = [
            GARMIN_ID,
            WAHOO_ID,
            "i-act-005",
            "i-act-004",
            "i-act-001",
            "i-act-003",
            "i-act-002",
        ]
        page = tables.page(today=TODAY)
        self.assertEqual([row["id"] for row in page["activities"]], expected)
        self.assertEqual(
            {k: v for k, v in page.items() if k != "activities"},
            {"snapshot_synced_at": None, "next_cursor": None, "limit": 100, "days": -1},
        )
        recent = tables.recent(today=TODAY)
        self.assertEqual([row["id"] for row in recent["activities"]], expected)
        self.assertEqual(
            {k: v for k, v in recent.items() if k != "activities"},
            {"snapshot_synced_at": None, "days": -1},
        )

    def test_duplicate_inspection_reads_only_the_tables(self) -> None:
        # Before the first backfill nothing is in the tables:
        # no pair is offered, so nothing can be deleted twice.
        self.assertIsNone(self.inspector(make_selector(self)).latest())
        populate(self)
        pair = self.inspector(make_selector(self)).latest()
        self.assertEqual((pair or {}).get("duplicate_id"), GARMIN_ID)

    def test_compact_rows_drop_empty_and_unlisted_fields(self) -> None:
        raw = [{"id": "x", "type": "Ride", "name": None, "private_comment": "free"}]
        (compact,) = compact_activity_rows(raw)
        self.assertNotIn("name", compact)
        self.assertNotIn("private_comment", compact)
        self.assertEqual(compact["type"], "Ride")


class SnapshotWithoutCanonicalSectionsTests(_ActivityCase):
    def test_read_service_does_not_need_the_snapshot_sections(self) -> None:
        populate(self)
        selector = make_selector(self)
        service = self.read_service(selector)
        expected_page = service.page(today=TODAY)["activities"]
        expected_recent = service.recent(today=TODAY)["activities"]
        self.assertTrue(expected_page)

        self.strip_canonical_sections()

        self.assertEqual(service.page(today=TODAY)["activities"], expected_page)
        self.assertEqual(service.recent(today=TODAY)["activities"], expected_recent)

    def test_duplicate_inspection_does_not_need_the_snapshot_sections(self) -> None:
        populate(self)
        selector = make_selector(self)
        expected = self.inspector(selector).latest()
        self.assertIsNotNone(expected)

        self.strip_canonical_sections()

        self.assertEqual(self.inspector(selector).latest(), expected)

    def test_duplicate_removal_works_without_the_snapshot_sections(self) -> None:
        populate(self)
        selector = make_selector(self)
        payload = self._payload(selector)
        self.strip_canonical_sections()
        service = DuplicateActivityService(
            self.manager,
            self.inspector(selector),
            lambda: REMOVAL_AT,
            Mock(),
        )

        service.delete(payload, Mock())

        self.assertNotIn(GARMIN_ID, self.ids(self.read(selector.activity_rows)))

    def _payload(self, selector: Any) -> dict[str, Any]:
        pair = self.inspector(selector).latest() or {}
        return {
            key: pair[key]
            for key in ("canonical_id", "duplicate_id", "snapshot_synced_at")
        }
