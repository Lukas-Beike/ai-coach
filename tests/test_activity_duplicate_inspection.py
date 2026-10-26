"""Duplicate inspection reads canonical Intervals.icu records, never the snapshot."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from duplicate_support import (
    FETCHED_AT,
    GARMIN_ID,
    START,
    WAHOO_ID,
    ZONE,
    DuplicateCase,
)

from backend.activities.duplicate_inspection import latest_wahoo_garmin_duplicate
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, Sport
from backend.db import canonical_store
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.intervals_activity_mapping import map_intervals_activities

LATER = "2026-09-21T08:00:00+00:00"


class InspectionTests(DuplicateCase):
    def test_current_pair_is_found_without_any_snapshot(self) -> None:
        self.seed_pair()

        pair = self.inspector.latest()

        self.assertEqual(
            pair,
            {
                "canonical_id": WAHOO_ID,
                "canonical_name": "Synthetic ride",
                "duplicate_id": GARMIN_ID,
                "duplicate_name": "Synthetic ride",
                "start_date_local": "2026-09-20T07:00:00",
                "moving_time": 3600.0,
                "distance": 30000.0,
                "snapshot_synced_at": FETCHED_AT,
            },
        )
        self.assertEqual(self.query("SELECT 1 FROM snapshots"), [])

    def test_a_missing_name_falls_back_to_the_source_label(self) -> None:
        self.seed(WAHOO_ID, recorded_by=RecordingOrigin.WAHOO, name=None)
        self.seed(GARMIN_ID, recorded_by=RecordingOrigin.GARMIN, name=None)

        pair = self.inspector.latest() or {}

        self.assertEqual(pair["canonical_name"], "Wahoo-Radeinheit")
        self.assertEqual(pair["duplicate_name"], "Garmin-Radeinheit")

    def test_other_providers_records_do_not_change_the_pair(self) -> None:
        self.seed_pair()
        # The same ride also arrived through the Garmin and Wahoo providers.
        self.seed("garmin-direct", provider=ProviderId.GARMIN)
        self.seed(
            "wahoo-direct", provider=ProviderId.WAHOO, recorded_by=RecordingOrigin.WAHOO
        )

        pair = self.inspector.latest() or {}

        self.assertEqual(
            (pair["canonical_id"], pair["duplicate_id"]), (WAHOO_ID, GARMIN_ID)
        )

    def test_merged_alias_session_is_still_a_pair(self) -> None:
        wahoo, garmin = self.seed_pair()
        self.merge(garmin, wahoo)

        self.assertEqual((self.inspector.latest() or {})["duplicate_id"], GARMIN_ID)

    def test_a_newer_unrelated_activity_blocks_the_pair(self) -> None:
        self.seed_pair()
        self.seed(
            "new-run",
            recorded_by=RecordingOrigin.GARMIN,
            started_at=START + timedelta(days=1),
            sport=Sport.RUN,
        )

        self.assertIsNone(self.inspector.latest())

    def test_a_tombstoned_copy_is_no_longer_reported(self) -> None:
        self.seed_pair()
        with self.manager.unit_of_work() as db:
            canonical_store.mark_activity_deleted(
                db,
                ProviderId.INTERVALS.value,
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id=GARMIN_ID,
                now=LATER,
            )

        self.assertIsNone(self.inspector.latest())

    def test_no_activities_and_unrelated_rides_give_no_pair(self) -> None:
        self.assertIsNone(self.inspector.latest())
        self.seed(WAHOO_ID, recorded_by=RecordingOrigin.WAHOO)
        self.seed(
            GARMIN_ID,
            recorded_by=RecordingOrigin.GARMIN,
            started_at=START + timedelta(hours=3),
        )

        self.assertIsNone(self.inspector.latest())

    def test_the_token_follows_the_newest_fetch_of_either_record(self) -> None:
        self.seed_pair()
        before = (self.inspector.latest() or {})["snapshot_synced_at"]
        # A later fetch of the Garmin copy changes nothing but its fetch time.
        self.seed(
            GARMIN_ID,
            recorded_by=RecordingOrigin.GARMIN,
            duration_s=3580.0,
            fetched_at=LATER,
        )

        after = (self.inspector.latest() or {})["snapshot_synced_at"]

        self.assertEqual((before, after), (FETCHED_AT, LATER))


class PairRuleTests(DuplicateCase):
    """The records are compared with the canonical Wahoo/Garmin ride rule."""

    def pair(self, **garmin: object):
        self.seed(WAHOO_ID, recorded_by=RecordingOrigin.WAHOO)
        self.seed(GARMIN_ID, recorded_by=RecordingOrigin.GARMIN, **garmin)  # type: ignore[arg-type]
        return self.inspector.latest()

    def test_start_window_is_inclusive_at_thirty_minutes(self) -> None:
        self.assertIsNotNone(self.pair(started_at=START + timedelta(minutes=30)))

    def test_start_beyond_the_window_is_no_pair(self) -> None:
        self.assertIsNone(self.pair(started_at=START + timedelta(minutes=31)))

    def test_duration_tolerance_is_relative_to_the_larger_side(self) -> None:
        self.assertIsNotNone(self.pair(duration_s=4000.0))

    def test_duration_beyond_the_tolerance_is_no_pair(self) -> None:
        self.assertIsNone(self.pair(duration_s=4001.0))

    def test_distance_beyond_the_tolerance_is_no_pair(self) -> None:
        self.assertIsNone(self.pair(distance_m=34000.0))

    def test_only_rides_pair(self) -> None:
        self.assertIsNone(self.pair(sport=Sport.RUN))

    def test_the_pure_rule_needs_both_recorders(self) -> None:
        self.seed(WAHOO_ID, recorded_by=RecordingOrigin.WAHOO)
        self.seed(GARMIN_ID, recorded_by=RecordingOrigin.UNKNOWN)
        with self.manager.reader() as db:
            records = self.reader.activities(db)

        self.assertIsNone(latest_wahoo_garmin_duplicate(records, zone=ZONE))


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "intervals-1",
        "type": "Ride",
        "start_date_local": "2026-05-04T07:00:00",
        "moving_time": 3600,
        "distance": 30_000,
    }
    row.update(overrides)
    return row


def _inspect(*rows: dict[str, object]):
    mapped = map_intervals_activities(
        list(rows), zone=ZONE, retrieved_at=datetime(2026, 5, 4, 8, 0, tzinfo=UTC)
    )
    return latest_wahoo_garmin_duplicate(mapped.records, zone=ZONE)


class RawRowCharacterizationTests(unittest.TestCase):
    """Intervals.icu rows mapped by the real mapper, as the sync stores them."""

    def test_newest_pair_is_selected_by_the_wahoo_start(self) -> None:
        # The newest activity is the Garmin copy, so both Wahoo rides pair with
        # it. The pair whose Wahoo ride starts later wins.
        pair = _inspect(
            _row(
                id="wahoo-early", source="Wahoo", start_date_local="2026-05-04T09:45:00"
            ),
            _row(
                id="wahoo-late", source="Wahoo", start_date_local="2026-05-04T10:00:00"
            ),
            _row(
                id="garmin-latest",
                source="Garmin",
                start_date_local="2026-05-04T10:10:00",
            ),
        )
        assert pair is not None
        self.assertEqual(pair["canonical_id"], "wahoo-late")
        self.assertEqual(pair["duplicate_id"], "garmin-latest")

    def test_device_provenance_reads_device_name_and_external_id(self) -> None:
        pair = _inspect(
            _row(id="wahoo", source=None, device_name="ELEMNT BOLT"),
            _row(
                id="garmin",
                source=None,
                external_id="garmin:42",
                moving_time=3_560,
                distance=29_800,
            ),
        )
        assert pair is not None
        self.assertEqual(
            (pair["canonical_id"], pair["duplicate_id"]), ("wahoo", "garmin")
        )

    def test_garmin_provenance_must_be_explicit(self) -> None:
        self.assertIsNone(
            _inspect(
                _row(id="wahoo", source="Wahoo"), _row(id="unlabelled", source=None)
            )
        )

    def test_elapsed_time_backs_a_missing_moving_time(self) -> None:
        pair = _inspect(
            _row(
                id="wahoo",
                source="Wahoo",
                name=None,
                moving_time=None,
                elapsed_time=3_600,
            ),
            _row(id="garmin", source="Garmin", name=None),
        )
        assert pair is not None
        self.assertEqual(pair["moving_time"], 3_600)
        self.assertEqual(pair["distance"], 30_000)
        self.assertEqual(pair["canonical_name"], "Wahoo-Radeinheit")


if __name__ == "__main__":
    unittest.main()
