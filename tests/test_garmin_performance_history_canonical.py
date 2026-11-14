"""Garmin performance history from canonical observations.

The snapshot cache (``performance_history``) kept the current Garmin metrics on
their measurement day across syncs. Its stored rows are canonical observations
(athlete decision 2026-10-26), and the canonical history also holds every other
dated provider record (a superset accepted on 2026-10-25), so each cached day and
value, including days from earlier syncs, must reappear in it. Synthetic fixture
snapshots only; no account, network or real data is used.
"""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from support import temp_database

from backend.canonical.vocabulary import MetricKind
from backend.db import garmin_store
from backend.db.repositories import KeyValueRepository
from backend.performance import body, chart_history, trends
from backend.performance import freshness as performance_freshness
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.context import current_performance_context
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS
from backend.performance.garmin_canonical import read_garmin_recovery, read_garmin_state
from backend.performance.garmin_metrics import garmin_performance_context
from backend.providers import canonical_plans
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.sync.canonical_backfill import CanonicalBackfill
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin import GarminPayloadService
from backend.sync.garmin_performance_history import append_garmin_performance_history
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.state import SyncStateRepository

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
        from backend.db import row_factory
        from backend.db.schema import initialize_schema
        from backend.sync.canonical_table_reader import CanonicalTableReader

        day = "2026-10-10"
        manager = temp_database(self, "history.db", row_factory=row_factory)
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
                for item in CanonicalTableReader().observations(db, MetricKind.FTP)
            }
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
        from backend.db import canonical_store, row_factory
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
        manager = temp_database(self, "history.db", row_factory=row_factory)
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
            # The fixture's range rows date by ``from``, its latest rows by ``calendarDate``.
            for row in self.snapshot.get("cycling_ftp_history") or []:
                day = date.fromisoformat(str(row.get("from") or row["calendarDate"]))
                if start <= day <= TODAY:
                    values[day] = row.get("value", row.get("functionalThresholdPower"))
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


# The golden history of ``HistoryReprojectionGoldenTests`` (#2081); regenerate it
# only for an intended change, with PACECRAFT_WRITE_GOLDEN=1.
GOLDEN = (
    Path(__file__).resolve().parent / "fixtures" / "garmin_history_reprojection.json"
)
FIRST_DAY = date(2026, 10, 1)
DAYS = 12
# Each observation's value-level fields and its provenance, in this order.
OBSERVATION_COLUMNS = (
    "metric",
    "sport",
    "observed_on",
    "value",
    "unit",
    "source_kind",
    "recorded_by",
    "label",
    "method",
    "aggregation",
    "observed_at",
    "details",
    "state",
    "source_record_id",
    "owner_record_id",
    "retrieved_at",
)
# Generated ids, re-projection versions and write times.
GENERATED = frozenset(
    {"id", "mapped_version", "mapper_version", "created_at", "updated_at"}
)
_SOURCES = (
    "max_metrics",
    "running_threshold",
    "readiness",
    "race_predictions",
    "cycling_ftp",
    "cycling_ftp_history",
    "heart_rate_zones",
    "endurance_score",
    "running_tolerance",
    "training_readiness_history",
    "weekly_training_status",
    "weight",
    "weigh_ins",
)


def _weight(index: int, iso: str) -> dict[str, Any]:
    """The weight section in the shapes Garmin and the legacy reader know."""
    if index == 3:
        return {
            "weigh_ins": {
                "dateWeightList": [
                    {
                        "calendarDate": iso,
                        "timestampGMT": f"{iso}T05:30:00",
                        "weight": 158.0,
                        "unit": "lbs",
                        "bodyFat": 0.18,
                        "bodyFatUnit": "fraction",
                    }
                ]
            }
        }
    if index == 5:
        return {
            "weigh_ins": [
                {
                    "calendarDate": iso,
                    "weight": 71.2,
                    "unit": "kg",
                    "sourceType": "MANUAL",
                }
            ]
        }
    if index in (7, 8):
        return {}
    return {
        "weight": [
            {
                "dailyWeightSummaries": [
                    {
                        "summaryDate": iso,
                        "latestWeight": {
                            "samplePk": index + 1,
                            "calendarDate": iso,
                            "weight": 72000.0 - 150 * index,
                            "bodyFat": 17.5 - index / 10,
                        },
                    }
                ]
            }
        ]
    }


def _race_predictions(index: int, iso: str) -> Any:
    if index % 4 == 1:
        return [
            {"calendarDate": iso, "raceDistance": "5K", "time": 1300 - index},
            {"calendarDate": iso, "raceDistance": "HALF_MARATHON", "time": "1:42:30"},
        ]
    if index % 4 == 2:
        return {
            "calendarDate": iso,
            "time5K": f"21:{10 + index:02d}",
            "time10K": 2760 - index,
            "timeHalfMarathon": 6100_000 + index * 1000,
            "timeMarathon": {"raceTime": 13000 - index},
        }
    # Day 8's prediction comes without a date.
    return {
        **({} if index == 8 else {"calendarDate": iso}),
        "5k": {"raceTime": 1320 - index},
        "10k": {"raceTime": 2790 - index},
        "halfMarathon": {"raceTime": 6150 - index},
        "marathon": {"raceTime": 13050 - index},
    }


def _readiness(index: int, iso: str) -> Any:
    if index % 3 == 0:
        return [
            {"calendarDate": iso, "timestamp": f"{iso}T14:00:00", "score": 40},
            {
                "calendarDate": iso,
                "timestamp": f"{iso}T06:10:00",
                "inputContext": "AFTER_WAKEUP_RESET",
                "score": 60 + index,
            },
        ]
    return {"calendarDate": iso, "score": 70 + index, "level": "HIGH"}


def _performance_sections(index: int, day: date) -> dict[str, Any]:
    iso = day.isoformat()
    week_ago = (day - timedelta(days=7)).isoformat()
    speed = 3.6 + index / 100
    # The lactate threshold carries its day; day 2's answer comes without one.
    dated = {} if index == 2 else {"calendarDate": iso}
    return {
        "max_metrics": [
            {
                "generic": {
                    "calendarDate": iso,
                    "vo2MaxPreciseValue": 57.0 + index / 5,
                },
                "cycling": {
                    "calendarDate": iso,
                    "vo2MaxPreciseValue": 59.0 + index / 4,
                },
            }
        ],
        "running_threshold": {
            "speed_and_heart_rate": {
                **dated,
                # Garmin's scaled speed below 1 on one day.
                "speed": speed / 10 if index == 4 else speed,
                "heartRate": 166 + index % 3,
                "heartRateCycling": 158 + index % 2,
            },
            "power": {
                **dated,
                "sport": "RUNNING",
                "functionalThresholdPower": 285 + index,
            },
        },
        "readiness": _readiness(index, iso),
        "race_predictions": _race_predictions(index, iso),
        "cycling_ftp": {"sport": "CYCLING", "functionalThresholdPower": 250 + index}
        if index == 6
        else {
            "calendarDate": iso,
            "sport": "CYCLING",
            "functionalThresholdPower": 250 + index,
        },
        "cycling_ftp_history": [
            {"from": week_ago, "value": 245 + index},
            {
                "calendarDate": iso,
                "sport": "CYCLING",
                "functionalThresholdPower": 250 + index,
            },
        ],
        "heart_rate_zones": [
            {"sport": "CYCLING", "maxHeartRateUsed": 186 + index % 2},
            {"sport": "RUNNING", "maxHeartRateUsed": 255 if index == 9 else 192},
        ],
        "endurance_score": [{"calendarDate": iso, "overallScore": 6800 + 10 * index}],
        "running_tolerance": [{"calendarDate": iso, "toleranceScore": 60 + index}],
        "training_readiness_history": [
            {"calendarDate": iso, "score": 55 + index, "level": "MODERATE"}
        ],
        "weekly_training_status": [
            {
                "calendarDate": iso,
                "trainingStatus": 4,
                "weeklyTrainingLoad": 400 + index,
            }
        ],
        **_weight(index, iso),
    }


def day_payload(index: int, day: date) -> dict[str, Any]:
    """One collected sync of ``day``; day 10 skips the latest-value sections."""
    iso = day.isoformat()
    sections = {} if index == 10 else _performance_sections(index, day)
    # Day 7's VO2max read fails: its stored value stays and turns stale.
    failed = "max_metrics" if index == 7 else None
    if failed:
        sections.pop(failed, None)
    return {
        "start": iso,
        "end": iso,
        "synced_at": f"{iso}T07:00:00",
        "errors": [{"source": failed}] if failed else [],
        "provider_sync": {
            "pagination": {
                source: {"complete": source != failed} for source in _SOURCES
            },
            "daily_metrics_on": iso,
        },
        **sections,
    }


class HistoryReprojectionGoldenTests(unittest.TestCase):
    """A synthetic sync history re-projects to the pinned observations and context.

    Each simulated day runs one sync through ``GarminPayloadService`` and the
    snapshot writer on temporary storage. The latest-value sections change from
    day to day, so the accumulated ``performance_history`` is the only stored
    record of earlier days. The golden file pins the stored history rows, the
    provider charts, every canonical Garmin observation and the Coach's Garmin
    context after the live ingest, and how a forced re-projection of the stored
    raw records differs from it.
    """

    def setUp(self) -> None:
        self.manager = temp_database(self, "history.db", schema=True)
        self.today = FIRST_DAY

    def sync_history(self) -> dict[str, str]:
        """Run every simulated day's sync; return each day's provider charts by digest."""
        charts = {}
        for index in range(DAYS):
            day = FIRST_DAY + timedelta(days=index)
            self.today = day
            synced_at = f"{day.isoformat()}T07:00:00"
            key_values = KeyValueRepository(partial(str, synced_at))
            service = GarminPayloadService(
                self.manager,
                key_values,
                SyncStateRepository(self.manager, key_values, partial(str, synced_at)),
                partial(date.fromordinal, day.toordinal()),
            )
            payload = service.prepare_remote(day_payload(index, day))
            charts[day.isoformat()] = _digest(payload["provider_metrics"])
            with self.manager.unit_of_work() as db:
                GarminSnapshotWriter(key_values, lambda: ZONE).write(db, payload)
        return charts

    def rows(self) -> dict[str, Any]:
        """The canonical Garmin rows: observations one compact line each, raw records by digest."""
        with self.manager.reader() as db:
            observations = sorted(
                "|".join(str(row[column]) for column in OBSERVATION_COLUMNS)
                for row in db.execute("SELECT * FROM observations").fetchall()
            )
            raw = sorted(
                json.dumps(
                    {k: v for k, v in dict(row).items() if k not in GENERATED},
                    sort_keys=True,
                )
                for row in db.execute("SELECT * FROM provider_records").fetchall()
            )
        return {
            "observations": observations,
            "raw_records": len(raw),
            "raw_records_sha256": hashlib.sha256("\n".join(raw).encode()).hexdigest(),
        }

    def reproject(self) -> None:
        bumped = {
            key: value + 1 for key, value in canonical_plans._MAPPER_VERSIONS.items()
        }
        backfill = CanonicalBackfill(
            key_values=KeyValueRepository(lambda: "2026-10-13T08:00:00"),
            zone_provider=lambda: ZONE,
            clock=lambda: "2026-10-13T08:00:00",
        )
        with patch.dict(canonical_plans._MAPPER_VERSIONS, bumped):
            for _ in range(1000):
                with self.manager.unit_of_work() as db:
                    if backfill.run_batch(db).done:
                        return
        self.fail("re-projection did not finish")

    def coach_context(self) -> dict[str, Any]:
        """The Garmin parts of the Coach context, read as the projection service reads them."""
        today = self.today
        reader = CanonicalTableReader()
        with self.manager.reader() as db:
            status = performance_freshness.GarminSyncStatus.from_state(
                garmin_store.read_state(db),
                stored_sections=garmin_store.section_names(db),
            )
            state = read_garmin_state(reader, db)
            recovery = read_garmin_recovery(
                reader, db, start=today - timedelta(days=13)
            )
            inputs = read_performance_inputs(
                reader, db, activity_reader=_NoActivities(), as_of=today
            )
        assert inputs is not None
        return {
            "source_freshness": performance_freshness.garmin_source_freshness(
                status, today
            ),
            "recovery": recovery,
            "performance": garmin_performance_context(status, today, state.metrics),
            "performance_history": {
                key: {day.isoformat(): value for day, value in sorted(values.items())}
                for key, values in sorted(state.metrics.performance_history.items())
            },
            "analysis_provider_metrics": chart_history.analysis_history(
                status, today, canonical=inputs
            )["provider_metrics"],
            "current_performance": current_performance_context(
                status, {"timezone": "Europe/Berlin"}, today, canonical=inputs
            ),
        }

    def test_the_history_reprojects_to_the_pinned_observations_and_context(
        self,
    ) -> None:
        charts = self.sync_history()
        with self.manager.reader() as db:
            history = garmin_store.read_view(db).get("performance_history")
        ingested = {**self.rows(), "coach_context": self.coach_context()}
        self.reproject()
        rows = self.rows()
        context = self.coach_context()

        self.assertEqual(rows["raw_records"], ingested["raw_records"])
        self.assertEqual(rows["raw_records_sha256"], ingested["raw_records_sha256"])
        # The re-projection equals the live ingest (#2782): every observation,
        # with its owner and provenance, and the Coach context.
        self.assertEqual(rows["observations"], ingested["observations"])
        self.assertEqual(context, ingested["coach_context"])
        before, after = set(ingested["observations"]), set(rows["observations"])
        reprojected = {
            "observations_removed": sorted(before - after),
            "observations_added": sorted(after - before),
            "coach_context_changed": sorted(
                key
                for key, value in context.items()
                if value != ingested["coach_context"][key]
            ),
            "coach_context": _digests(context),
        }
        actual = json.loads(
            json.dumps(
                {
                    "performance_history": history,
                    "provider_metrics": charts,
                    "ingested": {
                        **ingested,
                        "coach_context": _digests(ingested["coach_context"]),
                        "coach_performance_history": ingested["coach_context"][
                            "performance_history"
                        ],
                    },
                    "reprojected": reprojected,
                },
                sort_keys=True,
                default=str,
            )
        )
        if os.environ.get("PACECRAFT_WRITE_GOLDEN") == "1":
            GOLDEN.write_text(
                json.dumps(actual, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
        self.assertEqual(actual, json.loads(GOLDEN.read_text(encoding="utf-8")))


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def _digests(values: dict[str, Any]) -> dict[str, str]:
    return {key: _digest(value) for key, value in values.items()}


class _NoActivities:
    def activity_summaries(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[Any, ...]:
        return ()


if __name__ == "__main__":
    unittest.main()
