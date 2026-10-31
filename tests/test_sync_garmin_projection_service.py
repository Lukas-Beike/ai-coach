from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from support import make_config

from backend.observability import Redactor
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance.freshness import GarminSyncStatus
from backend.performance.garmin_canonical import (
    GarminCanonicalMetrics,
    GarminCanonicalState,
)
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.sync.garmin_projection_service import (
    GarminCanonicalSources,
    GarminProjectionService,
)


class _DatabaseManager:
    @contextmanager
    def reader(self):
        yield object()

    def unit_of_work(self):
        raise AssertionError("A read projection must not acquire a writer.")


class _KeyValueRepository:
    def __init__(self, values):
        self.values = values

    def get(self, _db, key):
        return self.values.get(key)


class _PayloadService:
    """Serves the stored Garmin sync status of a synthetic state."""

    def __init__(self, snapshot):
        self.value = snapshot
        self.reads = 0

    def sync_status(self):
        self.reads += 1
        return GarminSyncStatus.from_state(self.value)

    def sync_status_in(self, _db):
        return self.sync_status()


class _SyncService:
    def __init__(self, available):
        self.value = available

    def available(self):
        return self.value


class _SyncStateService:
    def __init__(self, errors):
        self.value = errors

    def core_error_entries(self):
        return self.value


class _Summaries:
    """The canonical activity summaries."""

    def __init__(self, summaries):
        self.summaries = tuple(summaries)

    def activity_summaries(self, _db, **_bounds):
        return self.summaries


class _MappedObservations:
    """Serves the observations the production mapper makes of a raw Garmin payload."""

    def __init__(self, payload):
        self.records = map_garmin_health(
            dict(payload), zone=UTC, retrieved_at=datetime(2026, 9, 20, 8, tzinfo=UTC)
        ).records

    def observations(self, _db, kind, *, start=None, end=None, sport=None):
        return tuple(
            item
            for item in self.records
            if item.kind is kind and (start is None or item.observed_on >= start)
        )


class _MorningBodyBatteryService:
    def __init__(self, value):
        self.value = value
        self.reads = 0

    def current(self):
        self.reads += 1
        return self.value


class _GarminClientFactory:
    def __init__(self, available=False):
        self.value = available

    def available(self):
        return self.value


def _config(*, email="", fixture="", tokenstore="synthetic-tokenstore"):
    return make_config(
        openai_base_url="",
        openai_model="",
        intervals_api_key="",
        intervals_athlete_id="",
        garmin_email=email,
        garmin_password="synthetic-garmin-password",
        garmin_tokenstore=tokenstore,
        garmin_fixture_path=fixture,
        app_password="synthetic-app-password",
        data_retention_days=30,
    )


def _metrics():
    keys = (
        "cycling_ftp_watts",
        "run_threshold_watts",
        "run_threshold_pace_seconds_per_km",
        "bike_threshold_hr_bpm",
        "run_threshold_hr_bpm",
        "weight_kg",
        "cycling_max_hr_bpm",
        "running_max_hr_bpm",
        "cycling_vo2max_ml_kg_min",
        "running_vo2max_ml_kg_min",
        "run_5k_seconds",
        "run_10k_seconds",
        "run_half_marathon_seconds",
        "run_marathon_seconds",
    )
    return {key: {"value": None} for key in keys}


class GarminProjectionServiceTests(unittest.TestCase):
    def _service(
        self,
        *,
        snapshot=None,
        summaries=(),
        state=None,
        config=None,
        core_errors=None,
        body_battery=None,
        last_sync_at="2026-09-20T07:30:00Z",
        available=True,
        client_available=False,
        payload=None,
        metric_export_status=None,
    ):
        config = config or _config()
        redactor = Redactor(lambda: config)
        battery = _MorningBodyBatteryService(body_battery)
        patcher = patch(
            "backend.sync.garmin_projection_service.read_garmin_state",
            return_value=state
            or GarminCanonicalState(metrics=GarminCanonicalMetrics()),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        service = GarminProjectionService(
            config=config,
            garmin_payload_service=payload or _PayloadService(snapshot or {}),
            garmin_sync_service=_SyncService(available),
            garmin_sync_state_service=_SyncStateService(core_errors or []),
            morning_body_battery_service=battery,
            garmin_client_factory=_GarminClientFactory(client_available),
            database_manager=_DatabaseManager(),
            key_value_repository=_KeyValueRepository(
                {
                    "last_garmin_sync_at": last_sync_at,
                    "last_garmin_metric_export_status": metric_export_status,
                }
            ),
            redactor=redactor,
            local_now=lambda: datetime(2026, 9, 20, 8, tzinfo=UTC),
            canonical=GarminCanonicalSources(
                activity_rows=lambda: object(),
                observations=lambda: _MappedObservations(snapshot or {}),
                activity_summaries=lambda: _Summaries(summaries),
            ),
        )
        return service, battery

    def test_public_state_includes_the_durable_metric_export_receipt(self):
        receipt = "Intervals.icu: 2 Messwerte gesendet, 1 Konflikte, 0 fehlgeschlagen."
        service, _ = self._service(metric_export_status=receipt)
        with patch.object(
            performance_garmin_metrics,
            "garmin_performance_metrics",
            return_value=_metrics(),
        ):
            self.assertEqual(service.public_state()["metric_export_status"], receipt)

    def test_missing_export_receipt_is_omitted_but_disabled_consent_is_explicit(self):
        service, _ = self._service()
        with patch.object(
            performance_garmin_metrics,
            "garmin_performance_metrics",
            return_value=_metrics(),
        ):
            result = service.public_state()
        self.assertNotIn("metric_export_status", result)
        self.assertIs(result["metric_export_enabled"], False)

    def test_public_state_preserves_status_metrics_dedup_and_redacted_core_errors(self):
        # Canonical reads (#1416): sessions replace the raw Garmin activity rows.
        summaries = [
            {"id": "s1", "record_ids": {"intervals": "intervals-1", "garmin": "1"}},
            {"id": "s2", "record_ids": {"garmin": "2"}},
        ]
        snapshot = {
            "source": "fixture",
            "synced_at": "2026-09-20T07:30:00Z",
            "provider_sync": {"pagination": {"activities": {"complete": False}}},
            "source_freshness": {
                "sleep": {"freshness": "partial", "observed_at": "2026-09-19"}
            },
            "sleep": [{"date": "2026-09-19"}],
            "hrv": [{"date": "2026-09-19"}],
            "resting_hr": [{"date": "2026-09-19"}],
            "readiness": {"score": 72},
            "race_predictions": {"5k": 1200},
        }
        state = GarminCanonicalState(
            metrics=GarminCanonicalMetrics(race_predictions={"run_5k_seconds": 1200}),
            has_sleep=True,
            has_hrv=True,
            has_resting_hr=True,
            has_readiness=True,
        )
        metrics = _metrics()
        for key in (
            "cycling_ftp_watts",
            "run_threshold_pace_seconds_per_km",
            "weight_kg",
            "running_max_hr_bpm",
            "cycling_vo2max_ml_kg_min",
            "run_5k_seconds",
            "run_marathon_seconds",
        ):
            metrics[key]["value"] = 1
        with tempfile.TemporaryDirectory() as directory:
            service, battery = self._service(
                config=_config(tokenstore=str(Path(directory) / "tokens")),
                snapshot=snapshot,
                summaries=summaries,
                state=state,
                core_errors=[
                    {"source": "activities", "message": "synthetic-garmin-password"}
                ],
                body_battery={"status": "ready", "morning": {"value": 78}},
            )

            with patch.object(
                performance_garmin_metrics,
                "garmin_performance_metrics",
                return_value=metrics,
            ):
                result = service.public_state()

        self.assertTrue(result["available"])
        self.assertFalse(result["configured"])
        self.assertEqual(result["source"], "fixture")
        self.assertEqual(result["last_sync_at"], "2026-09-20T07:30:00Z")
        self.assertNotIn("synthetic-garmin-password", str(result["last_error"]))
        self.assertEqual(result["pagination"], snapshot["provider_sync"]["pagination"])
        self.assertEqual(result["source_freshness"]["sleep"]["freshness"], "partial")
        self.assertEqual(result["activities"], 1)
        self.assertEqual(result["duplicate_activities_skipped"], 1)
        for key in (
            "has_sleep",
            "has_hrv",
            "has_resting_hr",
            "has_thresholds",
            "has_readiness",
            "has_race_predictions",
            "has_weight",
            "has_max_hr",
            "has_vo2max",
            "has_estimated_run_times",
        ):
            self.assertTrue(result[key], key)
        self.assertEqual(
            result["morning_body_battery"],
            {"status": "ready", "morning": {"value": 78}},
        )
        self.assertEqual(battery.reads, 1)

    def test_public_state_keeps_library_fallback_and_fixture_configuration(self):
        service, _ = self._service(
            config=_config(fixture="synthetic-fixture.json"),
            snapshot={"source": None},
            available=False,
            client_available=True,
        )
        with patch.object(
            performance_garmin_metrics,
            "garmin_performance_metrics",
            return_value=_metrics(),
        ):
            result = service.public_state()

        self.assertTrue(result["configured"])
        self.assertFalse(result["available"])
        self.assertEqual(result["source"], "library")
        self.assertFalse(result["has_thresholds"])
        self.assertFalse(result["has_weight"])
        self.assertFalse(result["has_max_hr"])
        self.assertFalse(result["has_vo2max"])
        self.assertFalse(result["has_estimated_run_times"])

    def test_duplicates_are_counted_against_the_canonical_sessions_only(self):
        # Canonical reads (#1416): a Garmin record bundled with another provider's
        # record in one session is the duplicate; the raw view is not read.
        snapshot = {"activities": [{"activityId": 1}]}
        alone = {"id": "s1", "record_ids": {"garmin": "1"}}
        shared = {"id": "s1", "record_ids": {"intervals": "i1", "garmin": "1"}}
        intervals_only = {"id": "s2", "record_ids": {"intervals": "i2"}}
        # Only an Intervals.icu record makes the Garmin copy a skipped duplicate.
        with_wahoo = {"id": "s3", "record_ids": {"wahoo": "w1", "garmin": "3"}}
        for summaries, expected in (
            ([], (0, 0)),
            ([alone, intervals_only], (1, 0)),
            ([shared], (0, 1)),
            ([with_wahoo], (1, 0)),
        ):
            with self.subTest(summaries=len(summaries)):
                service, _ = self._service(snapshot=snapshot, summaries=summaries)
                with patch.object(
                    performance_garmin_metrics,
                    "garmin_performance_metrics",
                    return_value=_metrics(),
                ):
                    result = service.public_state()
                self.assertEqual(
                    (result["activities"], result["duplicate_activities_skipped"]),
                    expected,
                )

    def test_the_projection_requires_the_canonical_sources(self):
        with self.assertRaises(TypeError):
            GarminProjectionService(  # type: ignore[call-arg]
                config=_config(),
                garmin_payload_service=_PayloadService({}),
                garmin_sync_service=_SyncService(True),
                garmin_sync_state_service=_SyncStateService([]),
                morning_body_battery_service=_MorningBodyBatteryService(None),
                garmin_client_factory=_GarminClientFactory(),
                database_manager=_DatabaseManager(),
                key_value_repository=_KeyValueRepository({}),
                redactor=Redactor(lambda: _config()),
                local_now=lambda: datetime(2026, 9, 20, 8, tzinfo=UTC),
            )

    def test_public_state_reuses_a_status_the_caller_already_read(self):
        snapshot = {"source": "fixture", "sleep": [{"date": "2026-09-19"}]}
        payload = _PayloadService(snapshot)
        service, _battery = self._service(snapshot=snapshot, payload=payload)
        with patch.object(
            performance_garmin_metrics,
            "garmin_performance_metrics",
            return_value=_metrics(),
        ):
            expected = service.public_state()
            result = service.public_state(GarminSyncStatus.from_state(snapshot))

        self.assertEqual(result, expected)
        self.assertEqual(payload.reads, 1)

    def test_coach_context_keeps_recovery_scope_error_bounds_and_performance_fallback(
        self,
    ):
        secret = "synthetic-garmin-password"
        snapshot = {
            "synced_at": "2026-09-20T07:30:00Z",
            "start": "2026-09-01",
            "end": "2026-09-20",
            "source_freshness": {
                "weight": {"freshness": "stale", "observed_at": "2026-09-01"}
            },
            "sleep": [
                {"calendarDate": "2026-09-19", "sleepScore": 70},
                {
                    "calendarDate": "2026-09-20",
                    "sleepScore": 82,
                    "instruction": "ignored",
                },
            ],
            "hrv": [{"calendarDate": "2026-09-20", "lastNightAvg": 57}],
            "resting_hr": [{"calendarDate": "2026-09-20", "restingHeartRate": 48}],
            "readiness": {"calendarDate": "2026-09-20", "score": 78},
            "errors": ["", *[secret + "x" * 350 for _ in range(22)]],
            "activities": [{"activityId": 5, "activityName": "private activity"}],
        }
        battery = {"morning": {"value": 78}}
        service, _ = self._service(snapshot=snapshot, body_battery=battery)
        performance = {"source": "Garmin Connect", "thresholds": {}}

        with patch.object(
            performance_garmin_metrics,
            "garmin_performance_context",
            return_value=performance,
        ) as context_projection:
            basic = service.coach_context()
            result = service.coach_context(include_performance=True)

        self.assertEqual(
            basic["scope"],
            "Nur der aktuellste Garmin-Recovery-Datensatz. Leistungswerte und Aktivitäten stehen in den deduplizierten bzw. abgeleiteten Abschnitten.",
        )
        self.assertNotIn("performance", basic)
        self.assertEqual(
            result["scope"],
            "Kein Intervals.icu-Snapshot vorhanden; Garmin-Leistungswerte und der aktuellste Recovery-Datensatz werden als Fallback verwendet.",
        )
        self.assertEqual(result["performance"], performance)
        self.assertEqual(context_projection.call_count, 1)
        # Canonical reads (#1416): the latest canonical record of each section,
        # with neutral field names, replaces the raw Garmin record.
        self.assertEqual(
            result["recovery"]["sleep"], {"date": "2026-09-20", "sleep_score": 82}
        )
        self.assertEqual(result["recovery"]["hrv"]["last_night_avg_ms"], 57)
        self.assertEqual(
            result["recovery"]["resting_hr"],
            {"date": "2026-09-20", "resting_hr_bpm": 48},
        )
        self.assertEqual(result["recovery"]["readiness"]["score"], 78)
        self.assertEqual(result["recovery"]["body_battery"], battery)
        self.assertEqual(len(result["errors"]), 20)
        self.assertTrue(all(len(error) <= 300 for error in result["errors"]))
        self.assertNotIn(secret, "".join(result["errors"]))
        self.assertNotIn("activities", result)
        self.assertNotIn("instruction", result["recovery"]["sleep"])

    def test_configured_tokenstore_path_is_checked_without_reading_token_data(self):
        with tempfile.TemporaryDirectory() as directory:
            tokenstore = Path(directory) / "tokens"
            tokenstore.touch()
            service, _ = self._service(
                config=_config(tokenstore=str(tokenstore)), snapshot={}
            )
            with patch.object(
                performance_garmin_metrics,
                "garmin_performance_metrics",
                return_value=_metrics(),
            ):
                result = service.public_state()

        self.assertTrue(result["configured"])


if __name__ == "__main__":
    unittest.main()
