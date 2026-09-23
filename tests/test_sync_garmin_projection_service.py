from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.config import Config
from backend.observability import Redactor
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.sync.garmin_projection_service import GarminProjectionService


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
    def __init__(self, snapshot):
        self.value = snapshot

    def snapshot(self):
        return self.value


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


class _SyncStateRepository:
    def __init__(self, snapshot):
        self.value = snapshot

    def latest_snapshot(self):
        return self.value


class _MorningBodyBatteryService:
    def __init__(self, value):
        self.value = value
        self.snapshots = []

    def current(self, snapshot=None):
        self.snapshots.append(snapshot)
        return self.value


class _GarminClientFactory:
    def __init__(self, available=False):
        self.value = available

    def available(self):
        return self.value


def _config(*, email="", fixture="", tokenstore="synthetic-tokenstore"):
    return Config(
        port=8090,
        openai_api_key="",
        openai_base_url="",
        openai_model="",
        gemini_api_key="",
        gemini_model="",
        ai_provider="openai",
        intervals_api_key="",
        intervals_athlete_id="",
        garmin_email=email,
        garmin_password="synthetic-garmin-password",
        garmin_tokenstore=tokenstore,
        garmin_fixture_path=fixture,
        calendar_ical_url="",
        app_password="synthetic-app-password",
        secure_cookies=False,
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
        canonical=None,
        config=None,
        core_errors=None,
        body_battery=None,
        last_sync_at="2026-09-20T07:30:00Z",
        available=True,
        client_available=False,
    ):
        config = config or _config()
        redactor = Redactor(lambda: config)
        battery = _MorningBodyBatteryService(body_battery)
        service = GarminProjectionService(
            config=config,
            garmin_payload_service=_PayloadService(snapshot or {}),
            garmin_sync_service=_SyncService(available),
            garmin_sync_state_service=_SyncStateService(core_errors or []),
            sync_state_repository=_SyncStateRepository(canonical),
            morning_body_battery_service=battery,
            garmin_client_factory=_GarminClientFactory(client_available),
            database_manager=_DatabaseManager(),
            key_value_repository=_KeyValueRepository(
                {"last_garmin_sync_at": last_sync_at}
            ),
            redactor=redactor,
            local_now=lambda: datetime(2026, 9, 20, 8, tzinfo=timezone.utc),
        )
        return service, battery

    def test_public_state_preserves_status_metrics_dedup_and_redacted_core_errors(self):
        duplicate = {
            "activityId": 1,
            "startTimeLocal": "2026-09-19 08:00:00",
            "activityType": {"typeKey": "cycling"},
            "duration": 3600,
            "distance": 30000,
        }
        unique = {
            "activityId": 2,
            "startTimeLocal": "2026-09-18 08:00:00",
            "activityType": {"typeKey": "running"},
            "duration": 1800,
            "distance": 5000,
        }
        snapshot = {
            "source": "fixture",
            "synced_at": "2026-09-20T07:30:00Z",
            "provider_sync": {"pagination": {"activities": {"complete": False}}},
            "source_freshness": {
                "sleep": {"freshness": "partial", "observed_at": "2026-09-19"}
            },
            "activities": [duplicate, unique, "invalid"],
            "sleep": [{"date": "2026-09-19"}],
            "hrv": [{"date": "2026-09-19"}],
            "resting_hr": [{"date": "2026-09-19"}],
            "readiness": {"score": 72},
            "race_predictions": {"5k": 1200},
        }
        canonical = {
            "recent_activities": [
                {
                    "id": "intervals-1",
                    "start_date_local": "2026-09-19T08:00:00",
                    "type": "Ride",
                    "moving_time": 3600,
                    "distance": 30000,
                }
            ]
        }
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
                canonical=canonical,
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
        self.assertIs(battery.snapshots[0], snapshot)

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
        self.assertEqual(
            result["recovery"]["sleep"],
            {"calendarDate": "2026-09-20", "sleepScore": 82},
        )
        self.assertEqual(result["recovery"]["hrv"]["lastNightAvg"], 57)
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
