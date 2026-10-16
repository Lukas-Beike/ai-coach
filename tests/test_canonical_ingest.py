"""Canonical ingest use case: counters, deletion windows, skipped rows and secrets.

Each test uses a temporary SQLite file with the schema initialized. Provider rows
are synthetic and mocked; no account, network or real data directory is used.
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
)
from backend.db.canonical_store import WriteOutcome
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import IngestPlan, ObservationItem
from backend.sync import canonical_ingest as ingest
from backend.sync.snapshots import historical_chunk_snapshot, merge_historical_snapshot

ZONE = ZoneInfo("Europe/Berlin")
NOW = "2026-09-20T08:00:00+00:00"
EARLIER_SYNC = "2026-09-19T08:00:00+00:00"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers"
TODAY = date(2026, 9, 20)
EARLIEST = date(2026, 9, 1)
RETRIEVED_AT = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
SECRET = "synthetic-secret-value"
SIGNED_URL = "https://files.invalid/ride.fit?X-Amz-Signature=synthetic-signature"


def intervals_row(
    identifier: str, day: str = "2026-09-10", kind: str = "Ride"
) -> dict[str, Any]:
    return {
        "id": identifier,
        "start_date_local": f"{day}T07:00:00",
        "type": kind,
        "access_token": SECRET,
        "download": SIGNED_URL,
    }


def garmin_row(identifier: int = 910010) -> dict[str, Any]:
    return {
        "activityId": identifier,
        "activityName": "Synthetic ride",
        "activityType": {"typeKey": "cycling"},
        "startTimeLocal": "2026-09-10 07:15:00",
        "distance": 20000.0,
        "duration": 3600.0,
        "averageHR": 140,
        "activityTrainingLoad": 50.0,
        "access_token": SECRET,
    }


def intervals_snapshot(rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "synced_at": NOW,
        "raw_provider_data": {"activities": rows},
        **extra,
    }


def observation(value: float) -> Observation:
    return Observation(
        kind=MetricKind.WEIGHT,
        value=MetricValue(value=value, unit="kg"),
        observed_on=date(2026, 9, 10),
        observed_at=None,
        provenance=Provenance(
            provider=ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=RETRIEVED_AT,
            label=None,
        ),
        sport=None,
    )


def activity_states(db: sqlite3.Connection) -> dict[str, str]:
    return dict(
        db.execute(
            "SELECT provider_activity_id, state FROM activity_records"
        ).fetchall()
    )


def stored_payload_text(db: sqlite3.Connection) -> str:
    return "\n".join(
        row[0] for row in db.execute("SELECT payload FROM provider_records")
    )


def fixture(provider: str, name: str) -> Any:
    return json.loads((FIXTURES / provider / name).read_text(encoding="utf-8"))


class IngestFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = sqlite3.connect(Path(self.temporary.name) / "ingest.db")
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.db.commit()

    def count(self, table: str) -> int:
        return int(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


class CounterTests(unittest.TestCase):
    def test_each_outcome_increments_its_own_counter(self) -> None:
        counters = ingest.CanonicalIngestCounters()
        counters.count(WriteOutcome.WRITTEN)
        counters.count(WriteOutcome.UPDATED)
        counters.count(WriteOutcome.UNCHANGED)
        counters.count(WriteOutcome.UNCHANGED)
        self.assertEqual(
            counters.as_dict(),
            {
                "written": 1,
                "updated": 1,
                "unchanged": 2,
                "skipped_invalid": 0,
                "deleted": 0,
                "linked": 0,
            },
        )


class DeletionWindowTests(unittest.TestCase):
    def test_full_fetch_covers_the_inner_days_from_the_earliest_date(self) -> None:
        window = ingest.intervals_deletion_window(
            today=TODAY, activity_days=3, all_sync_days=3, earliest_date=EARLIEST
        )
        self.assertEqual(
            window,
            ingest.DeletionWindow(start=date(2026, 9, 2), end=date(2026, 9, 19)),
        )

    def test_partial_fetch_excludes_both_edge_days(self) -> None:
        window = ingest.intervals_deletion_window(
            today=TODAY, activity_days=14, all_sync_days=3, earliest_date=EARLIEST
        )
        self.assertEqual(window.start, date(2026, 9, 8))
        self.assertEqual(window.end, date(2026, 9, 19))

    def test_one_or_zero_days_leave_an_empty_window(self) -> None:
        for days in (0, 1, 2):
            with self.subTest(days=days):
                window = ingest.intervals_deletion_window(
                    today=TODAY,
                    activity_days=days,
                    all_sync_days=3,
                    earliest_date=EARLIEST,
                )
                self.assertGreater(window.start, window.end)


class IntervalsIngestTests(IngestFixture):
    def ingest(
        self, snapshot: dict[str, Any], activity_days: int | None
    ) -> ingest.CanonicalIngestCounters:
        return ingest.ingest_intervals_snapshot(
            self.db,
            snapshot,
            zone=ZONE,
            activity_days=activity_days,
            all_sync_days=3,
            earliest_date=EARLIEST,
        )

    def test_snapshot_without_a_sync_time_writes_nothing(self) -> None:
        counters = ingest.ingest_intervals_snapshot(
            self.db,
            {"raw_provider_data": {"activities": [intervals_row("i-1")]}},
            zone=ZONE,
            activity_days=3,
            all_sync_days=3,
            earliest_date=EARLIEST,
        )
        self.assertEqual(counters, ingest.CanonicalIngestCounters())
        self.assertEqual(self.count("provider_records"), 0)
        self.assertEqual(self.count("activity_records"), 0)

    def test_valid_activity_is_written_and_its_raw_record_stored(self) -> None:
        counters = self.ingest(intervals_snapshot([intervals_row("i-1")]), 3)
        self.assertEqual(counters.written, 1)
        self.assertEqual(counters.skipped_invalid, 0)
        self.assertEqual(self.count("provider_records"), 1)

    def test_invalid_rows_are_skipped_and_counted(self) -> None:
        counters = self.ingest(
            intervals_snapshot([intervals_row("i-1"), {"type": "Ride"}]), None
        )
        self.assertEqual((counters.written, counters.skipped_invalid), (1, 1))

    def test_chunked_historical_ingest_matches_one_full_ingest(self) -> None:
        def snapshot(activities: list[str], wellness: list[str]) -> dict[str, Any]:
            return {
                "synced_at": NOW,
                "raw_provider_data": {
                    "athlete": {"id": "athlete-1"},
                    "activities": [
                        intervals_row(name, day=f"2026-09-{index + 2:02d}")
                        for index, name in enumerate(activities)
                    ],
                    "wellness": [
                        {"id": f"2026-09-{index + 2:02d}", "weight": 70.0 + index}
                        for index, _ in enumerate(wellness)
                    ],
                },
            }

        base = snapshot(["i-1", "i-2"], ["w-1", "w-2"])
        older = snapshot(["i-0", "i-2"], ["w-0"])
        older["raw_provider_data"]["wellness"][0]["id"] = "2026-09-01"
        oldest = snapshot(["i-3"], [])
        merged = base
        chunks = []
        for incoming in (older, oldest):
            current = merged
            merged = merge_historical_snapshot(current, incoming)
            chunks.append(historical_chunk_snapshot(current, merged))
        self.assertEqual(
            [len(chunk["raw_provider_data"]["activities"]) for chunk in chunks],
            [1, 1],
        )

        def dump(db: sqlite3.Connection) -> dict[str, list[str]]:
            tables = [
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            # Generated ids (uuid text, autoincrement integers) depend on the
            # insertion order; compare everything else.
            generated = re.compile(r"[a-z]+_[0-9a-f]{32}")

            def stable_rows(table: str) -> list[str]:
                info = db.execute(f"PRAGMA table_info({table})").fetchall()
                keep = [
                    index
                    for index, column in enumerate(info)
                    if not (column[5] and column[2].upper() == "INTEGER")
                ]
                return sorted(
                    generated.sub("<id>", repr(tuple(row[i] for i in keep)))
                    for row in db.execute(f"SELECT * FROM {table}")
                )

            return {table: stable_rows(table) for table in tables}

        def ingest_all(db: sqlite3.Connection, snapshots: list[dict[str, Any]]):
            for item in snapshots:
                ingest.ingest_intervals_snapshot(
                    db,
                    item,
                    zone=ZONE,
                    activity_days=None,
                    all_sync_days=3,
                    earliest_date=EARLIEST,
                )

        ingest_all(self.db, [base, *chunks])
        with tempfile.TemporaryDirectory() as directory:
            full = sqlite3.connect(Path(directory) / "full.db")
            try:
                initialize_schema(full)
                ingest_all(full, [merged])
                expected = dump(full)
            finally:
                full.close()

        actual = dump(self.db)
        self.assertGreater(len(actual["activity_records"]), 0)
        self.assertEqual(actual.keys(), expected.keys())
        for table in expected:
            self.assertEqual(actual[table], expected[table], table)

    def test_historical_fetch_never_deletes(self) -> None:
        self.ingest(intervals_snapshot([intervals_row("i-1"), intervals_row("i-2")]), 3)
        counters = self.ingest(intervals_snapshot([intervals_row("i-1")]), None)
        self.assertEqual(counters.deleted, 0)
        self.assertEqual(activity_states(self.db), {"i-1": "active", "i-2": "active"})

    def test_incremental_fetch_never_deletes(self) -> None:
        self.ingest(intervals_snapshot([intervals_row("i-1"), intervals_row("i-2")]), 3)
        counters = self.ingest(
            intervals_snapshot([intervals_row("i-1")], incremental=True), 3
        )
        self.assertEqual(counters.deleted, 0)
        self.assertEqual(activity_states(self.db), {"i-1": "active", "i-2": "active"})

    def test_full_fetch_deletes_only_missing_activities_inside_its_window(self) -> None:
        self.ingest(intervals_snapshot([intervals_row("old", day="2026-08-20")]), None)
        self.ingest(intervals_snapshot([intervals_row("i-1"), intervals_row("i-2")]), 3)
        counters = self.ingest(intervals_snapshot([intervals_row("i-1")]), 3)
        self.assertEqual(counters.deleted, 1)
        self.assertEqual(
            activity_states(self.db),
            {"old": "active", "i-1": "active", "i-2": "deleted"},
        )

    def test_full_fetch_never_deletes_on_the_edge_days_of_its_window(self) -> None:
        edges = [
            intervals_row("first", day="2026-09-01"),
            intervals_row("today", day="2026-09-20"),
        ]
        self.ingest(intervals_snapshot([intervals_row("i-1"), *edges]), 3)
        counters = self.ingest(intervals_snapshot([intervals_row("i-1")]), 3)
        self.assertEqual(counters.deleted, 0)
        self.assertEqual(
            activity_states(self.db),
            {"i-1": "active", "first": "active", "today": "active"},
        )

    def test_full_fetch_without_an_activity_list_never_deletes(self) -> None:
        self.ingest(intervals_snapshot([intervals_row("i-1")]), 3)
        counters = self.ingest({"synced_at": NOW, "raw_provider_data": {}}, 3)
        self.assertEqual(counters.deleted, 0)
        self.assertEqual(activity_states(self.db), {"i-1": "active"})

    def test_secrets_are_not_stored_in_raw_records(self) -> None:
        self.ingest(intervals_snapshot([intervals_row("i-1")]), 3)
        text = stored_payload_text(self.db)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("X-Amz-Signature", text)
        self.assertIn("i-1", text)


class GarminIngestTests(IngestFixture):
    def test_payload_without_a_sync_time_writes_nothing(self) -> None:
        counters = ingest.ingest_garmin_payload(
            self.db, {"activities": [garmin_row()]}, zone=ZONE
        )
        self.assertEqual(counters, ingest.CanonicalIngestCounters())
        self.assertEqual(self.count("provider_records"), 0)

    def test_garmin_never_deletes_an_activity_missing_from_a_later_payload(
        self,
    ) -> None:
        ingest.ingest_garmin_payload(
            self.db,
            {"synced_at": NOW, "activities": [garmin_row(1), garmin_row(2)]},
            zone=ZONE,
        )
        counters = ingest.ingest_garmin_payload(
            self.db, {"synced_at": NOW, "activities": [garmin_row(1)]}, zone=ZONE
        )
        self.assertEqual(counters.deleted, 0)
        self.assertEqual(activity_states(self.db), {"1": "active", "2": "active"})

    def test_secrets_are_removed_from_garmin_raw_records(self) -> None:
        payload = {
            "synced_at": NOW,
            "activities": [garmin_row()],
            "sleep": {"apiKey": SECRET, "hours": 7, "download": SIGNED_URL},
        }
        ingest.ingest_garmin_payload(self.db, payload, zone=ZONE)
        text = stored_payload_text(self.db)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("X-Amz-Signature", text)
        self.assertIn("910010", text)

    def test_a_partial_refresh_keeps_the_fetch_time_of_retained_sections(
        self,
    ) -> None:
        hrv = fixture("garmin", "hrv.json")
        first = {"synced_at": EARLIER_SYNC, "hrv": hrv, "activities": [garmin_row()]}
        ingest.ingest_garmin_payload(self.db, first, zone=ZONE)
        # A later read failed for HRV and activities: both sections are retained.
        retained = {
            **first,
            "synced_at": NOW,
            "source_freshness": {
                "hrv": {"freshness": "stale", "fetched_at": EARLIER_SYNC},
                "activities": {"freshness": "stale", "fetched_at": EARLIER_SYNC},
            },
        }
        counters = ingest.ingest_garmin_payload(self.db, retained, zone=ZONE)
        self.assertEqual((counters.written, counters.updated), (0, 0))
        self.assertGreater(counters.unchanged, 0)
        times = {
            row[0] for row in self.db.execute("SELECT retrieved_at FROM observations")
        } | {
            row[0] for row in self.db.execute("SELECT fetched_at FROM provider_records")
        }
        self.assertEqual(times, {EARLIER_SYNC})


class PlanObservationTests(IngestFixture):
    def test_duplicate_natural_keys_keep_the_first_and_count_the_rest(self) -> None:
        plan = IngestPlan(
            provider=ProviderId.INTERVALS,
            observations=(
                ObservationItem(observation(72.5), mapper_version=2),
                ObservationItem(observation(80.0), mapper_version=2),
            ),
            skipped_invalid=1,
        )
        counters = ingest.ingest_plan(
            self.db, plan, retrieved_at=RETRIEVED_AT, deletion_window=None, zone=ZONE
        )
        self.assertEqual((counters.written, counters.skipped_invalid), (1, 2))
        self.assertEqual(
            self.db.execute("SELECT value FROM observations").fetchone()[0], 72.5
        )


if __name__ == "__main__":
    unittest.main()
