"""Garmin performance history from canonical observations.

The snapshot cache (``performance_history``) kept the current Garmin metrics on
their measurement day across syncs. Its stored rows are canonical observations
(athlete decision 2026-10-26), and the canonical history also holds every other
dated provider record (a superset accepted on 2026-10-25), so each cached day and
value, including days from earlier syncs, must reappear in it. Synthetic fixture
snapshots only; no account, network or real data is used.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import MetricKind
from backend.performance import body, chart_history, trends
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS
from backend.performance.garmin_canonical import read_garmin_state
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.sync import garmin_metric_history
from backend.sync.garmin_performance_history import append_garmin_performance_history

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers" / "garmin"
TODAY = date(2026, 10, 11)
SYNCED_AT = "2026-10-11T06:00:00+00:00"
ZONE = ZoneInfo("Europe/Berlin")
SKIPPED = ("activities", "gear", "gear_stats", "user_profile")


class MappedReader:
    def __init__(self, sections: dict[str, Any]) -> None:
        self.records = map_garmin_health(
            sections, zone=ZONE, retrieved_at=datetime(2026, 10, 11, 6, tzinfo=UTC)
        ).records

    def observations(self, db: Any, kind: MetricKind, **_: Any) -> tuple:
        return tuple(record for record in self.records if record.kind is kind)


def fixture_snapshot() -> dict[str, Any]:
    payload: dict[str, Any] = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in FIXTURES.glob("*.json")
        if path.stem not in SKIPPED
    }
    payload["synced_at"] = SYNCED_AT
    # Each value is current; undated ones (thresholds, predictions, zones) on the sync day.
    payload["source_freshness"] = {
        section: {
            "freshness": "current",
            "observed_at": "2026-10-10"
            if section
            not in ("running_threshold", "race_predictions", "heart_rate_zones")
            else TODAY.isoformat(),
            "fetched_at": SYNCED_AT,
        }
        for section in list(payload)
    }
    return payload


class StoredHistoryPrecedenceTests(unittest.TestCase):
    """A later sync's accumulated history never replaces a dedicated value."""

    def write(self, db: Any, synced_at: str, **sections: Any) -> None:
        from backend.db.repositories import KeyValueRepository
        from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

        GarminSnapshotWriter(KeyValueRepository(lambda: synced_at), lambda: ZONE).write(
            db, {"synced_at": synced_at, **sections}
        )

    def test_the_dedicated_ftp_of_a_day_survives_the_next_sync(self) -> None:
        from backend.db import DatabaseManager, row_factory
        from backend.db.schema import initialize_schema
        from backend.sync.canonical_table_reader import CanonicalTableReader

        day = "2026-10-10"
        with tempfile.TemporaryDirectory() as directory:
            manager = DatabaseManager(
                Path(directory) / "history.db", sqlite3, row_factory=row_factory
            )
            try:
                with manager.unit_of_work() as db:
                    initialize_schema(db)
                    self.write(
                        db,
                        "2026-10-10T06:00:00+00:00",
                        cycling_ftp_history=[
                            {"calendarDate": day, "functionalThresholdPower": 280}
                        ],
                        performance_history=[
                            {"date": day, "metrics": {"cycling_ftp_watts": 279}}
                        ],
                    )
                    # The next sync re-sends the accumulated history only.
                    self.write(
                        db,
                        "2026-10-11T06:00:00+00:00",
                        performance_history=[
                            {"date": day, "metrics": {"cycling_ftp_watts": 279}},
                            {
                                "date": "2026-10-11",
                                "metrics": {"cycling_ftp_watts": 281},
                            },
                        ],
                    )
                with manager.reader() as db:
                    ftp = {
                        item.observed_on.isoformat(): item.value.value
                        for item in CanonicalTableReader().observations(
                            db, MetricKind.FTP
                        )
                    }
            finally:
                manager.close()
        self.assertEqual(ftp, {day: 280.0, "2026-10-11": 281.0})

    def test_history_refills_a_day_whose_dedicated_row_is_outdated(self) -> None:
        # A dedicated row from an older mapper whose raw element is gone: no
        # record re-projects it, so the stored history must serve that day.
        from backend.canonical.records import MetricValue, Observation, Provenance
        from backend.canonical.vocabulary import (
            ProviderId,
            RecordingOrigin,
            SourceKind,
            Sport,
        )
        from backend.db import DatabaseManager, canonical_store, row_factory
        from backend.db.schema import initialize_schema
        from backend.providers.garmin_health_mapping import MAPPER_VERSION
        from backend.sync.canonical_table_reader import CanonicalTableReader

        day = date(2026, 10, 10)
        stale = Observation(
            kind=MetricKind.FTP,
            value=MetricValue(275.0, MetricKind.FTP.unit),
            observed_on=day,
            observed_at=None,
            sport=Sport.RIDE,
            provenance=Provenance(
                provider=ProviderId.GARMIN,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id="cycling_ftp:2026-10-10",
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=datetime(2026, 10, 10, 6, tzinfo=UTC),
                label="Garmin Connect",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            manager = DatabaseManager(
                Path(directory) / "history.db", sqlite3, row_factory=row_factory
            )
            try:
                with manager.unit_of_work() as db:
                    initialize_schema(db)
                    canonical_store.upsert_observation(
                        db,
                        stale,
                        mapper_version=MAPPER_VERSION - 1,
                        now="2026-10-10T06:00:00+00:00",
                    )
                    self.write(
                        db,
                        "2026-10-11T06:00:00+00:00",
                        performance_history=[
                            {
                                "date": day.isoformat(),
                                "metrics": {"cycling_ftp_watts": 279},
                            }
                        ],
                    )
                with manager.reader() as db:
                    (served,) = CanonicalTableReader().observations(db, MetricKind.FTP)
            finally:
                manager.close()
        self.assertEqual((served.observed_on, served.value.value), (day, 279.0))


class PerformanceHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = fixture_snapshot()
        # Days an earlier sync cached; the current payload no longer reports them.
        earlier = {
            "performance_history": [
                {
                    "date": (TODAY - timedelta(days=offset)).isoformat(),
                    "metrics": {
                        "cycling_ftp_watts": 250 + offset,
                        "running_vo2max_ml_kg_min": 50,
                        "readiness": 60 + offset,
                    },
                }
                for offset in (40, 30, 20)
            ]
        }
        append_garmin_performance_history(self.snapshot, earlier, TODAY)
        self.history = read_garmin_state(
            MappedReader(self.snapshot), None
        ).metrics.performance_history

    def test_every_cached_day_reappears_with_its_value(self) -> None:
        cached = {
            (row["date"], key): value
            for row in self.snapshot["performance_history"]
            for key, value in row["metrics"].items()
        }
        self.assertTrue(cached)
        for (day, key), value in cached.items():
            with self.subTest(key=key, day=day):
                self.assertEqual(self.history[key][date.fromisoformat(day)], value)

    def cached_values(self, key: str, start: date) -> dict[date, float]:
        """The days the snapshot cache and the FTP history held for ``key``."""
        values: dict[date, float] = {}
        for row in self.snapshot["performance_history"]:
            day = date.fromisoformat(row["date"])
            if start <= day <= TODAY and row["metrics"].get(key) is not None:
                values[day] = row["metrics"][key]
        if key == "cycling_ftp_watts":
            for point in garmin_metric_history.ftp_points(
                self.snapshot.get("cycling_ftp_history"), start=start, end=TODAY
            ):
                values[date.fromisoformat(point["date"])] = point["value"]
        return values

    def test_comparison_averages_match_the_cache(self) -> None:
        start = TODAY - timedelta(days=29)
        for key in ("cycling_ftp_watts", "cycling_vo2max_ml_kg_min", "readiness"):
            with self.subTest(key=key):
                cached = self.cached_values(key, start)
                self.assertEqual(
                    trends.garmin_history_average(key, 30, TODAY, self.history),
                    round(sum(cached.values()) / len(cached), 2),
                )

    def test_chart_and_body_ftp_read_the_canonical_history(self) -> None:
        metrics = read_garmin_state(MappedReader(self.snapshot), None).metrics
        start = TODAY - timedelta(days=89)
        self.assertEqual(
            chart_history._garmin_values("cycling_ftp_watts", start, TODAY, metrics),
            {
                day.isoformat(): value
                for day, value in self.cached_values("cycling_ftp_watts", start).items()
            },
        )
        canonical_ftp = body._garmin_ftp(
            NO_GARMIN_SYNC_STATUS,
            TODAY,
            metrics.performance_history["cycling_ftp_watts"],
        )
        self.assertEqual(
            {day: value[0] for day, value in canonical_ftp.items()},
            self.cached_values("cycling_ftp_watts", date.min),
        )


if __name__ == "__main__":
    unittest.main()
