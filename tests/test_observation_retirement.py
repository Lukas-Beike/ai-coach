"""A value a provider clears or deletes is retired from the canonical observations.

An observation records the raw record whose projection emits it. When a sync maps
that record again and the value is gone, the row is retired: it stays in the table
(and in backups) but no canonical read serves it. A section that was not fetched,
or a value another record emits, is never retired. Temporary databases and
synthetic payloads only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.db import canonical_store
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import (
    current_observation_mapper_versions,
)
from backend.sync import canonical_backfill
from backend.sync import canonical_ingest as ingest

ZONE = ZoneInfo("Europe/Berlin")
NOW = "2026-09-20T08:00:00+00:00"
LATER = "2026-09-20T09:00:00+00:00"
NEXT_DAY = "2026-09-21T08:00:00+00:00"
DAY = "2026-09-18"
OTHER_DAY = "2026-09-17"


def intervals(
    wellness: list[dict[str, Any]], *, synced_at: str = NOW, **raw: Any
) -> dict[str, Any]:
    return {"synced_at": synced_at, "raw_provider_data": {"wellness": wellness, **raw}}


def garmin(synced_at: str = NOW, **sections: Any) -> dict[str, Any]:
    return {"synced_at": synced_at, **sections}


class ObservationRetirementTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = sqlite3.connect(Path(temporary.name) / "retire.db")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.db.commit()

    def ingest_intervals(
        self, snapshot: dict[str, Any]
    ) -> ingest.CanonicalIngestCounters:
        return ingest.ingest_intervals_snapshot(
            self.db,
            snapshot,
            zone=ZONE,
            activity_days=None,
            all_sync_days=3,
            earliest_date=date(2026, 9, 1),
        )

    def ingest_garmin(self, payload: dict[str, Any]) -> ingest.CanonicalIngestCounters:
        return ingest.ingest_garmin_payload(self.db, payload, zone=ZONE)

    def served(self, metric: str) -> list[tuple[str, float]]:
        rows = canonical_store.current_observation_rows(
            self.db, metric, current_observation_mapper_versions()
        )
        return [(row["observed_on"], row["value"]) for row in rows]

    def states(self, metric: str) -> dict[str, str]:
        return {
            row["observed_on"]: row["state"]
            for row in self.db.execute(
                "SELECT observed_on, state FROM observations WHERE metric = ?",
                (metric,),
            )
        }

    def test_cleared_intervals_wellness_value_is_retired_and_revived(self) -> None:
        self.ingest_intervals(
            intervals(
                [{"id": DAY, "restingHR": 84}, {"id": OTHER_DAY, "restingHR": 47}]
            )
        )
        self.assertEqual(self.served("resting_hr"), [(OTHER_DAY, 47.0), (DAY, 84.0)])

        counters = self.ingest_intervals(
            intervals([{"id": DAY, "restingHR": None}], synced_at=LATER)
        )

        self.assertEqual(counters.retired, 1)
        self.assertEqual(self.served("resting_hr"), [(OTHER_DAY, 47.0)])
        self.assertEqual(
            self.states("resting_hr"), {DAY: "retired", OTHER_DAY: "active"}
        )
        totals = canonical_store.provider_totals(self.db, "intervals")
        self.assertEqual(totals["observations"], 1)

        self.ingest_intervals(
            intervals([{"id": DAY, "restingHR": 48}], synced_at=LATER)
        )
        self.assertEqual(self.served("resting_hr"), [(OTHER_DAY, 47.0), (DAY, 48.0)])

    def test_removed_athlete_threshold_is_retired(self) -> None:
        ride = {"types": ["Ride"], "ftp": 250}
        self.ingest_intervals(
            intervals([], athlete={"id": "i1", "sportSettings": [ride]})
        )
        self.assertEqual(len(self.served("ftp")), 1)

        self.ingest_intervals(
            intervals(
                [],
                synced_at=LATER,
                athlete={"id": "i1", "sportSettings": [{"types": ["Ride"]}]},
            )
        )
        self.assertEqual(self.served("ftp"), [])

    def test_a_snapshot_record_keeps_the_values_of_earlier_days(self) -> None:
        athlete = {"id": "i1", "sportSettings": [{"types": ["Ride"], "ftp": 250}]}
        self.ingest_intervals(intervals([], athlete=athlete))
        self.ingest_intervals(intervals([], synced_at=NEXT_DAY, athlete=athlete))
        self.assertEqual(sorted(self.states("ftp").values()), ["active", "active"])

        cleared = {"id": "i1", "sportSettings": [{"types": ["Ride"]}]}
        counters = self.ingest_intervals(
            intervals([], synced_at=NEXT_DAY, athlete=cleared)
        )
        # Only the day the record speaks for is retired; the earlier day is history.
        self.assertEqual(counters.retired, 1)
        self.assertEqual(self.served("ftp"), [("2026-09-20", 250.0)])

    def test_a_whole_garmin_section_keeps_the_values_of_earlier_days(self) -> None:
        ftp = {"sport": "CYCLING", "functionalThresholdPower": 260}
        self.ingest_garmin(garmin(cycling_ftp=ftp))
        self.ingest_garmin(garmin(NEXT_DAY, cycling_ftp=ftp))
        self.assertEqual(sorted(self.states("ftp").values()), ["active", "active"])

    def test_a_payload_without_the_record_retires_nothing(self) -> None:
        self.ingest_intervals(intervals([{"id": DAY, "restingHR": 50}]))
        counters = self.ingest_intervals(
            intervals([{"id": OTHER_DAY, "restingHR": 51}], synced_at=LATER)
        )
        self.assertEqual(counters.retired, 0)
        self.assertEqual(self.served("resting_hr"), [(OTHER_DAY, 51.0), (DAY, 50.0)])

    def test_a_garmin_element_without_its_value_is_retired(self) -> None:
        self.ingest_garmin(
            garmin(resting_hr=[{"calendarDate": DAY, "restingHeartRate": 49}])
        )
        self.assertEqual(self.served("resting_hr"), [(DAY, 49.0)])

        self.ingest_garmin(garmin(LATER, resting_hr=[{"calendarDate": DAY}]))

        self.assertEqual(self.served("resting_hr"), [])
        self.assertEqual(self.states("resting_hr"), {DAY: "retired"})

    def test_a_failed_or_skipped_garmin_section_retires_nothing(self) -> None:
        self.ingest_garmin(
            garmin(resting_hr=[{"calendarDate": DAY, "restingHeartRate": 49}])
        )
        # The section failed: the payload keeps only what this read fetched.
        self.ingest_garmin(garmin(LATER, sleep={"calendarDate": DAY}))
        # The fetch came back empty: an empty list carries no element.
        self.ingest_garmin(garmin(LATER, resting_hr=[]))
        self.assertEqual(self.states("resting_hr"), {DAY: "active"})

    def test_a_row_of_another_owner_is_untouched(self) -> None:
        self.ingest_intervals(intervals([{"id": DAY, "restingHR": 50}]))
        self.db.execute(
            "UPDATE observations SET owner_record_id = NULL WHERE metric = 'resting_hr'"
        )
        counters = self.ingest_intervals(
            intervals([{"id": DAY, "restingHR": None}], synced_at=LATER)
        )
        self.assertEqual(counters.retired, 0)
        self.assertEqual(self.states("resting_hr"), {DAY: "active"})

    def test_reprojection_retires_a_value_its_stored_row_no_longer_carries(
        self,
    ) -> None:
        self.ingest_intervals(intervals([{"id": DAY, "restingHR": 84}]))
        # A stored row the current mapper reads without the value, as after a fix.
        self.db.execute(
            "UPDATE provider_records SET payload = ? WHERE record_kind = 'wellness'",
            (f'{{"id": "{DAY}"}}',),
        )
        row = dict(
            self.db.execute(
                "SELECT * FROM provider_records WHERE record_kind = 'wellness'"
            ).fetchone()
        )
        work = canonical_backfill._reprojection_work(row, ZONE)
        self.assertEqual(work.observation_owners, {DAY: DAY})
        retired = canonical_backfill._retire_unemitted_observations(
            self.db, row, work, now=LATER
        )
        self.assertEqual(retired, 1)
        self.assertEqual(self.served("resting_hr"), [])


if __name__ == "__main__":
    unittest.main()
