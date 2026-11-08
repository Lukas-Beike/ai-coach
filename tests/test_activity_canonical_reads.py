"""Activity readers served by the canonical selector instead of snapshot sections."""

from __future__ import annotations

import base64
import json
from datetime import date
from typing import Any

from canonical_read_support import (
    CanonicalReadFixture,
    LatestSnapshot,
    make_selector,
    populate,
)
from intervals_compaction import compact_activity_rows

from backend.activities.activity_reference import ActivityReferences
from backend.activities.detail_store import summary_fingerprint
from backend.activities.read_service import ActivityReadService
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.sync.canonical_table_reader import CanonicalTableReader

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

    def for_activity_ids(self, activity_ids: Any, **_options: Any) -> list[Any]:
        return []


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
            selector,
            _Feedback(),
        )

    def ids(self, rows: Any) -> set[str]:
        return {str(row["id"]) for row in rows}


class DuplicateRemovalTests(_ActivityCase):
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

        with self.manager.reader() as db:
            sessions = make_selector(self).activity_summaries(db)
        expected = [summary["id"] for summary in sessions]
        page = tables.page(today=TODAY)
        listed = page["activities"]
        self.assertEqual([row["id"] for row in listed], expected)
        # Each session once: the Intervals duplicate pair is one entry and the
        # Garmin-only session is listed.
        intervals_ids = [
            row["record_ids"].get("intervals")
            for row in listed
            if "intervals" in row["record_ids"]
        ]
        self.assertEqual(len(intervals_ids), len(set(intervals_ids)))
        self.assertEqual(
            1,
            sum(
                row["record_ids"].get("intervals") in (WAHOO_ID, GARMIN_ID)
                for row in listed
            ),
        )
        self.assertIn({"garmin": "910002"}, [row["record_ids"] for row in listed])
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

    def test_limit_one_pages_walk_every_session_and_old_cursors_restart(self) -> None:
        populate(self)
        service = self.read_service(make_selector(self))
        expected = [row["id"] for row in service.page(today=TODAY)["activities"]]
        walked: list[str] = []
        page = service.page(today=TODAY, limit=1)
        while True:
            walked.extend(row["id"] for row in page["activities"])
            if page["next_cursor"] is None:
                break
            page = service.page(page["next_cursor"], 1, today=TODAY)
        self.assertEqual(walked, expected)
        version_2 = base64.urlsafe_b64encode(
            json.dumps({"v": 2, "after": ["2026-10-26T07:00:00", "x"]}).encode()
        ).decode()
        restarted = service.page(version_2, 1, today=TODAY)
        self.assertEqual([row["id"] for row in restarted["activities"]], expected[:1])

    def test_list_rows_carry_neutral_names_only(self) -> None:
        populate(self)
        (row, *_rest) = self.read_service(make_selector(self)).page(today=TODAY)[
            "activities"
        ]
        for key in ("id", "started_at", "started_at_local", "sport", "record_ids"):
            self.assertIn(key, row)
        self.assertNotIn("detail_error", row)
        self.assertFalse(
            [
                key
                for key in row
                if key.startswith("icu_")
                or key
                in ("moving_time", "start_date_local", "type", "local_activity_id")
            ]
        )


class SessionListFreshnessTests(_ActivityCase):
    def test_fingerprints_keep_the_stored_values(self) -> None:
        """Intervals keeps summary_fingerprint of its row, others the payload hash."""
        populate(self)
        selector = make_selector(self)
        with self.manager.reader() as db:
            rows = [
                json.loads(text)
                for text in canonical_store.active_activity_payload_texts(
                    db,
                    provider=ProviderId.INTERVALS.value,
                    record_kind=ACTIVITY_RECORD_KIND,
                )
            ]
            keys = [("intervals", str(row["id"])) for row in rows]
            keys += [("garmin", "910002"), ("intervals", "missing")]
            current = selector.summary_fingerprints(db, keys)
            garmin_hash = canonical_store.active_provider_record_hash(
                db, "garmin", ACTIVITY_RECORD_KIND, "910002"
            )
        self.assertEqual(
            {("intervals", str(row["id"])): summary_fingerprint(row) for row in rows}
            | {("garmin", "910002"): garmin_hash},
            current,
        )
        self.assertIsNotNone(garmin_hash)

    def test_garmin_only_session_is_listed_and_its_detail_loads(self) -> None:
        populate(self)
        selector = make_selector(self)
        service = ActivityAnalysisReadService(
            self.manager,
            selector,
            _Feedback(),
            references=ActivityReferences(self.manager),
            canonical=CanonicalPerformanceSource(
                lambda: self.manager,
                lambda: selector,
                activity_summaries=lambda: selector,
            ),
            session_records=CanonicalTableReader().session_activities,
        )
        (garmin_only,) = [
            row
            for row in service.recent(today=TODAY)["activities"]
            if row["record_ids"] == {"garmin": "910002"}
        ]
        detail = service.detail(
            garmin_only["id"],
            garmin_status=NO_GARMIN_SYNC_STATUS,
            profile={},
            today=TODAY,
        )
        self.assertEqual(garmin_only["id"], detail["session"]["activity_id"])


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
