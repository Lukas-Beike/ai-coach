"""Server integration tests for performance."""

import unittest
from dataclasses import replace
from datetime import date, timedelta
from typing import ClassVar
from unittest.mock import patch

import intervals_compaction
from canonical_recovery_support import RecordingReader
from garmin_support import read_garmin, save_garmin
from performance_day_support import (
    SYNCED_AT,
    canonical_from_snapshot,
    garmin_metrics_from_payload,
)
from server_test_support import ServerTestCase, _current_performance_context, server
from support import store_garmin_activities

from backend.performance import context as performance_context
from backend.performance import planning_recovery as performance_planning_recovery
from backend.performance.freshness import GarminSyncStatus
from backend.performance.morning_battery_service import MORNING_BATTERY_HISTORY_KEY
from backend.providers import garmin as garmin_provider
from backend.runtime import clock as runtime_clock
from backend.weather import history as weather_history


def _mapped_performance_context(snapshot, today=None):
    today = today or server.ATHLETE_CLOCK.now().date()
    canonical = canonical_from_snapshot(snapshot, today)
    garmin = read_garmin()
    return performance_context.current_performance_context(
        GarminSyncStatus.from_state(garmin),
        server.ATHLETE_DATA.profile().get(),
        today,
        canonical=None
        if canonical is None
        else replace(canonical, garmin=garmin_metrics_from_payload(garmin)),
    )


class ServerPerformanceTests(ServerTestCase):
    def test_performance_assembly_returns_session_rpe_history(self):
        today = server.ATHLETE_CLOCK.now().date()
        store_garmin_activities(
            server,
            [
                {
                    "activityId": "assembly-test",
                    "activityType": {"typeKey": "cycling"},
                    "startTimeLocal": f"{today.isoformat()} 07:00:00",
                    "duration": 3600.0,
                    "directWorkoutRpe": 50,
                }
            ],
        )

        result = server.PUBLIC_STATE.performance_state_service().performance_state()

        load = result["performance"]["history"]["session_rpe_load"]
        self.assertEqual(load["totals"]["value"], 300.0)
        self.assertIsNotNone(load["computed_at"])

    def test_performance_exposes_thirty_day_trends_for_api_and_garmin_values(self):
        # The fixture maps the undated Garmin prediction to its fixed sync day,
        # so "today" is that day, not the wall clock: otherwise the dated
        # history point drifts onto the prediction's day or out of the window.
        today = SYNCED_AT.date()
        snapshot = {
            "synced_at": "now",
            "athlete": {},
            "recent_activities": [],
            "recent_wellness": [
                {
                    "id": today.isoformat(),
                    "readiness": 80,
                    "weight": 72,
                    "sport_info": [
                        {"types": ["Ride"], "ftp": 300},
                        {"types": ["Run"], "lthr": 175},
                    ],
                },
                {
                    "id": (today - timedelta(days=29)).isoformat(),
                    "readiness": 70,
                    "weight": 74,
                    "sport_info": [
                        {"types": ["Ride"], "ftp": 280},
                        {"types": ["Run"], "lthr": 170},
                    ],
                },
            ],
        }
        save_garmin(
            {
                "race_predictions": {"5k": 1500},
                "performance_history": [
                    {
                        "date": (today - timedelta(days=29)).isoformat(),
                        "metrics": {"run_5k_seconds": 1600},
                    }
                ],
            }
        )
        performance = _mapped_performance_context(snapshot, today)
        comparisons = performance["comparisons"]
        self.assertIsNone(comparisons["cycling_ftp_watts_30d"])
        self.assertIsNone(comparisons["bike_threshold_hr_bpm_30d"])
        # Intervals.icu readiness is no source, so there is no readiness trend.
        self.assertIsNone(comparisons["readiness_30d"])
        # The canonical Garmin history keeps today's prediction too (1500, 1600).
        self.assertEqual(comparisons["run_5k_seconds_30d"]["delta"], -50)
        self.assertEqual(comparisons["run_5k_seconds_30d"]["color"], "good")

    def test_morning_body_battery_loads_once_for_the_sleep_window(self):
        class FakeGarmin:
            sleep_calls: ClassVar = []
            body_battery_calls: ClassVar = []

            def __init__(self, *_args, **_kwargs):
                pass

            def login(self, _tokenstore):
                return False, None

            def get_sleep_data(self, checkin_date):
                self.sleep_calls.append(checkin_date)
                return {
                    "dailySleepDTO": {
                        "sleepStartTimestampGMT": "2026-09-03T21:30:00+00:00",
                        "sleepEndTimestampGMT": "2026-09-04T05:45:00+00:00",
                    }
                }

            def get_body_battery(self, start, end):
                self.body_battery_calls.append((start, end))
                return [
                    {
                        "bodyBatteryValuesArray": [
                            ["2026-09-03T21:25:00+00:00", 57],
                            ["2026-09-04T05:45:00+00:00", 78],
                        ]
                    }
                ]

        config = replace(
            server.CONFIG_HOLDER.value,
            garmin_email="test@example.invalid",
            garmin_password="test",
        )
        with (
            patch.object(server.CONFIG_HOLDER, "value", config),
            patch.object(
                garmin_provider.GarminClientFactory, "available", return_value=True
            ),
            patch.object(
                garmin_provider.GarminClientFactory, "create", side_effect=FakeGarmin
            ),
        ):
            first = server.morning_body_battery_service().sync(date(2026, 9, 4))
            second = server.morning_body_battery_service().sync(date(2026, 9, 4))

        self.assertEqual(first["status"], "ready")
        self.assertEqual(second["status"], "already_loaded")
        self.assertEqual(FakeGarmin.sleep_calls, ["2026-09-04"])
        self.assertEqual(FakeGarmin.body_battery_calls, [("2026-09-03", "2026-09-04")])
        self.assertEqual(
            server.GARMIN_ASSEMBLY.projection_service().public_state()[
                "morning_body_battery"
            ]["morning"]["value"],
            78,
        )
        self.assertEqual(
            weather_history.decode_history(
                server.key_value_service().get(MORNING_BATTERY_HISTORY_KEY)
            )["2026-09-04"],
            78,
        )
        save_garmin({})
        recovery = performance_planning_recovery.planning_recovery_view(
            RecordingReader({}),
            None,
            start=date(2026, 9, 1),
            end=date(2026, 9, 4),
            morning_battery_history=weather_history.decode_history(
                server.key_value_service().get(MORNING_BATTERY_HISTORY_KEY)
            ),
            morning_body_battery=None,
        )
        self.assertEqual(recovery["2026-09-04"]["body_battery"], 78)
        self.assertEqual(
            recovery["2026-09-04"]["sources"]["body_battery"], "Garmin Connect"
        )

    def test_activity_validation_exposes_cycling_power_as_percent_of_ftp(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        snapshot = intervals_compaction.compact_snapshot(
            {"sportSettings": [{"types": ["Ride"], "ftp": 300, "vo2max": 60}]},
            [
                {
                    "id": "latest-ride",
                    "type": "Ride",
                    "start_date_local": f"{today}T08:00:00",
                    "moving_time": 3600,
                    "distance": 30_000,
                    "average_watts": 200,
                    "normalized_power": 270,
                    "average_heartrate": 155,
                    "icu_intensity": 0.9,
                    "icu_ftp": 300,
                }
            ],
            [],
            [],
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=runtime_clock.utc_now(),
        )

        validation = _current_performance_context(snapshot)["activity_validation"]

        self.assertEqual(validation["activity"]["sport"], "Radfahren")
        # Without a Garmin, Wahoo or local FTP there is no local intensity and no
        # power ratio; the Intervals.icu FTP is no source.
        self.assertNotIn("intensity", validation["activity"])
        self.assertNotIn("power_as_percent_of_current_ftp", validation["activity"])
        self.assertTrue(
            all(item["value"] is None for item in validation["provider_references"])
        )
        self.assertEqual(
            validation["direct_activity_estimates"]["activity_configured_ftp_watts"],
            300,
        )
        self.assertNotEqual(
            validation["direct_activity_estimates"].get("activity_ftp_watts"), 300
        )

    def test_manual_body_profile_values_are_used_when_api_values_are_absent(self):
        server.ATHLETE_DATA.profile().save(
            {"weight_kg": "71,4", "body_fat_pct": "10.5", "height_cm": "181"}
        )
        # Canonical reads (#1416): the context needs some provider value; the
        # manual profile values then fill what the providers leave absent. Profile
        # values alone, without any synced provider data, keep it unavailable.
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        alone = _current_performance_context(
            {"synced_at": "now", "athlete": {}, "recent_wellness": []}
        )
        self.assertFalse(alone["available"])
        performance = _current_performance_context(
            {
                "synced_at": "now",
                "athlete": {},
                "recent_wellness": [{"id": today, "restingHR": 50}],
                "recent_activities": [],
            }
        )
        self.assertEqual(performance["metrics"]["weight_kg"]["value"], 71.4)
        self.assertEqual(performance["metrics"]["body_fat_pct"]["source"], "Manuell")
        self.assertEqual(performance["metrics"]["height_cm"]["value"], 181)
        metric = _current_performance_context(
            {
                "synced_at": "now",
                "athlete": {"height": 1.83},
                "recent_wellness": [{"id": today, "restingHR": 50}],
                "recent_activities": [],
            }
        )["metrics"]["height_cm"]
        # The Intervals.icu athlete height is no source; the profile's stands.
        self.assertEqual(metric["value"], 181)

    def test_performance_does_not_use_eftp_as_ftp_history(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        snapshot = intervals_compaction.compact_snapshot(
            {"sportSettings": [{"types": ["Ride"], "ftp": 300}]},
            [],
            [
                {
                    "id": today,
                    "restingHR": 50,
                    "sportInfo": [{"types": ["Ride"], "eFTP": 290}],
                }
            ],
            [],
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=runtime_clock.utc_now(),
        )

        performance = _current_performance_context(snapshot)

        # Neither the Intervals.icu FTP nor its eFTP is a current value or history.
        self.assertIsNone(performance["metrics"]["cycling_ftp_watts"]["value"])
        self.assertIsNone(performance["comparisons"]["cycling_ftp_watts_30d"])

    def test_mmp_model_is_neither_ftp_nor_a_current_eftp(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        snapshot = intervals_compaction.compact_snapshot(
            {
                "sportSettings": [
                    {
                        "types": ["Ride"],
                        "ftp": 300,
                        "eFTPSupported": True,
                        "mmp_model": {"ftp": 309},
                    }
                ],
            },
            [],
            [{"id": today, "restingHR": 50}],
            [],
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=runtime_clock.utc_now(),
        )

        metrics = _current_performance_context(snapshot)["metrics"]
        self.assertIsNone(metrics["cycling_ftp_watts"]["value"])
        # Intervals.icu eFTP is no longer read (#1727).
        self.assertNotIn("cycling_eftp_watts", metrics)


if __name__ == "__main__":
    unittest.main()
