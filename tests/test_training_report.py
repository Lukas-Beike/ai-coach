"""Training report coverage and historical zone contracts."""

import unittest
from datetime import date
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.analysis import AnalysisRoutes
from backend.performance.report_service import (
    TrainingDerivedReadService,
    TrainingProfileSelectionService,
    TrainingRecordsService,
    TrainingReportReadService,
    TrainingSeasonReadService,
)
from backend.performance.training_report import training_report


class TrainingReportTests(unittest.TestCase):
    def test_power_profile_windows_keep_sport_provenance_and_cache_gaps(self):
        records = [
            {
                "activity_id": "outdoor",
                "date": "2026-10-01",
                "sport": "Ride",
                "activity_type": "Ride",
                "source": "Intervals.icu",
                "device": "Wahoo ELEMNT",
                "power_profile": {
                    "status": "ok",
                    "duration_curve": [{"duration_seconds": 60, "watts": 240}],
                },
            },
            {
                "activity_id": "indoor",
                "date": "2026-10-01",
                "sport": "VirtualRide",
                "activity_type": "VirtualRide",
                "source": "Intervals.icu",
                "device": "Zwift",
                "power_profile": {
                    "status": "ok",
                    "duration_curve": [{"duration_seconds": 60, "watts": 300}],
                },
            },
            {
                "activity_id": "unknown",
                "date": "2026-10-01",
                "sport": "Ride",
                "activity_type": "Ride",
                "source": "Intervals.icu",
                "device": "Garmin",
                "power_profile": {"status": "insufficient_data", "duration_curve": []},
            },
        ]
        result = TrainingProfileSelectionService._profile_window(
            records, date(2026, 10, 2), 28
        )
        self.assertEqual(3, result["cache_coverage"]["records"])
        self.assertEqual(2, result["cache_coverage"]["usable_records"])
        self.assertEqual(1, result["cache_coverage"]["unknown_records"])
        power = [point for point in result["power"] if point["duration_seconds"] == 60]
        self.assertEqual(
            {"Ride": 240, "VirtualRide": 300},
            {point["sport"]: point["watts"] for point in power},
        )
        outdoor = next(point for point in power if point["sport"] == "Ride")
        indoor = next(point for point in power if point["sport"] == "VirtualRide")
        self.assertEqual("outdoor", outdoor["environment"])
        self.assertEqual("indoor", indoor["environment"])
        self.assertEqual("Wahoo ELEMNT", outdoor["device"])
        self.assertEqual("Zwift", indoor["device"])
        self.assertEqual("Intervals.icu", outdoor["source"])

    def test_running_speed_selects_fastest_effort_and_distance_selects_shortest(self):
        records = [
            {
                "activity_id": "steady",
                "date": "2026-10-01",
                "sport": "Run",
                "activity_type": "Run",
                "running_profile": {
                    "status": "ok",
                    "speed": [{"duration_seconds": 60, "speed_mps": 3.0}],
                    "distance": [{"distance_meters": 1000, "seconds": 330}],
                },
            },
            {
                "activity_id": "fast",
                "date": "2026-10-01",
                "sport": "Run",
                "activity_type": "Run",
                "running_profile": {
                    "status": "ok",
                    "speed": [{"duration_seconds": 60, "speed_mps": 4.0}],
                    "distance": [{"distance_meters": 1000, "seconds": 300}],
                },
            },
        ]
        result = TrainingProfileSelectionService._profile_window(
            records, date(2026, 10, 2), 28
        )
        self.assertEqual(
            4.0,
            next(
                point
                for point in result["running"]["speed"]
                if point["duration_seconds"] == 60
            )["speed_mps"],
        )
        self.assertEqual(
            300,
            next(
                point
                for point in result["running"]["distance"]
                if point["distance_meters"] == 1000
            )["seconds"],
        )

    def test_eight_week_load_totals_keep_missing_zero_duplicates_and_boundaries(self):
        old = {
            "id": "old",
            "type": "Ride",
            "start_date_local": "2026-08-10",
            "icu_training_load": 90,
        }
        result = self.report(
            [
                old,
                old,
                {
                    "id": "outside",
                    "start_date_local": "2026-08-09",
                    "icu_training_load": 100,
                },
                {
                    "id": "last-sunday",
                    "start_date_local": "2026-09-27",
                    "icu_training_load": 10,
                },
                {
                    "id": "monday",
                    "type": "Run",
                    "start_date": "2026-09-27T23:30:00Z",
                    "icu_training_load": 30,
                },
                {"id": "missing", "type": "Ride", "start_date_local": "2026-09-29"},
                {
                    "id": "zero",
                    "type": "Ride",
                    "start_date_local": "2026-09-30",
                    "icu_training_load": 0,
                },
                {
                    "id": "future",
                    "start_date_local": "2026-10-03",
                    "icu_training_load": 50,
                },
            ],
            timezone="Europe/Berlin",
        )
        weeks = result["weekly_load"]
        self.assertEqual(len(weeks), 8)
        self.assertEqual(weeks[0]["start"], "2026-08-10")
        self.assertEqual(weeks[0]["training_load"]["value"], 90)
        self.assertEqual(weeks[0]["training_load"]["total_sessions"], 1)
        self.assertIsNone(weeks[1]["training_load"]["value"])
        self.assertEqual(weeks[-2]["training_load"]["value"], 10)
        self.assertEqual(
            weeks[-1]["training_load"],
            {"value": 30, "measured_sessions": 2, "total_sessions": 3},
        )
        self.assertTrue(weeks[-1]["partial_period"])
        self.assertFalse(weeks[-2]["partial_period"])
        ride = self.report(
            [
                {
                    "id": "zero",
                    "type": "Ride",
                    "start_date_local": "2026-09-28",
                    "icu_training_load": 0,
                }
            ],
            sport="Ride",
        )
        self.assertEqual(ride["weekly_load"][-1]["training_load"]["value"], 0)

    def test_daily_chart_keeps_unknown_duration_future_and_timezone_boundaries(self):
        result = self.report(
            [
                {
                    "id": "one",
                    "name": "Easy run",
                    "type": "Run",
                    "start_date": "2026-09-27T23:30:00Z",
                    "moving_time": 1800,
                    "icu_training_load": 25,
                },
                {"id": "two", "type": "Ride", "start_date_local": "2026-09-28"},
                {
                    "id": "future",
                    "type": "Run",
                    "start_date_local": "2026-10-04",
                    "moving_time": 3600,
                },
            ],
            timezone="Europe/Berlin",
        )
        self.assertEqual(len(result["daily"]), 7)
        monday = result["daily"][0]
        self.assertEqual(monday["date"], "2026-09-28")
        self.assertEqual(monday["totals"]["sessions"], 2)
        self.assertEqual(monday["cumulative_training_load"]["value"], 25)
        self.assertEqual(monday["cumulative_training_load"]["measured_sessions"], 1)
        self.assertEqual(
            result["daily"][1]["cumulative_training_load"],
            monday["cumulative_training_load"],
        )
        self.assertIsNone(result["daily"][-1]["cumulative_training_load"]["value"])
        self.assertEqual(monday["activities"][0]["name"], "Easy run")
        self.assertEqual(monday["activities"][0]["training_load"], 25)
        self.assertIsNone(monday["activities"][1]["training_load"])
        self.assertEqual(result["daily"][-1]["activities"], [])
        self.assertEqual(monday["totals"]["moving_time"]["value"], 1800)
        self.assertEqual(monday["totals"]["moving_time"]["measured_sessions"], 1)
        self.assertIsNone(monday["sports"]["Ride"]["moving_time"]["value"])
        self.assertIsNone(result["daily"][1]["totals"]["moving_time"]["value"])
        self.assertTrue(result["daily"][-1]["future"])
        self.assertEqual(result["daily"][-1]["totals"]["sessions"], 0)

    def test_cumulative_week_load_is_flat_without_sessions_and_increases_by_contributions(
        self,
    ):
        result = self.report(
            [
                {
                    "id": "wed",
                    "type": "Run",
                    "start_date_local": "2026-09-30",
                    "icu_training_load": 30,
                },
                {
                    "id": "fri",
                    "type": "Ride",
                    "start_date_local": "2026-10-02",
                    "icu_training_load": 50,
                },
                {
                    "id": "prior",
                    "start_date_local": "2026-09-27",
                    "icu_training_load": 100,
                },
            ]
        )
        self.assertEqual(
            [day["cumulative_training_load"]["value"] for day in result["daily"]],
            [0, 0, 30, 30, 80, None, None],
        )
        self.assertEqual(result["weekly_load"][-1]["training_load"]["value"], 80)

    def test_feedback_follows_exact_current_activity_reference_and_preserves_zero_rpe(
        self,
    ):
        result = self.report(
            [{"id": "one", "type": "Run", "start_date_local": "2026-09-28"}],
            activity_feedback=[
                {
                    "activity_id": "one",
                    "notes": "Easy",
                    "session_rpe": 0,
                    "deviation_reason": "shortened",
                },
                {"activity_id": "outside", "notes": "Excluded"},
            ],
        )
        self.assertEqual(len(result["activity_feedback"]), 1)
        self.assertEqual(result["activity_feedback"][0]["session_rpe"], 0)
        self.assertEqual(
            result["activity_feedback"][0]["deviation_reason"], "shortened"
        )

    def report(self, rows, **kwargs):
        return training_report(
            {
                "synced_at": "2026-10-02T08:00:00Z",
                "raw_provider_data": {"activities": rows},
            },
            start=date(2026, 9, 28),
            days=7,
            today=date(2026, 10, 2),
            **kwargs,
        )

    def test_duplicate_ids_are_counted_once_and_missing_load_remains_unknown(self):
        row = {
            "id": "one",
            "start_date_local": "2026-09-28T08:00:00",
            "type": "Run",
            "moving_time": 1800,
        }
        result = self.report([row, row])
        self.assertEqual(1, result["totals"]["sessions"])
        self.assertIsNone(result["totals"]["icu_training_load"]["value"])
        self.assertEqual(0, result["totals"]["icu_training_load"]["measured_sessions"])
        self.assertTrue(result["partial_period"])

    def test_sensor_zones_stay_separate_and_strength_is_not_classified_as_endurance(
        self,
    ):
        rows = [
            {
                "id": "ride",
                "start_date_local": "2026-09-29",
                "type": "Ride",
                "moving_time": 3600,
                "icu_zone_times": [{"id": "Z2", "secs": 2400}],
                "icu_hr_zone_times": [{"id": "Z1", "secs": 1800}],
            },
            {
                "id": "strength",
                "start_date_local": "2026-09-29",
                "type": "WeightTraining",
                "moving_time": 1800,
                "icu_hr_zone_times": [{"id": "Z5", "secs": 1800}],
            },
        ]
        result = self.report(rows)
        self.assertEqual(
            ["power", "heart_rate"], [entry["sensor"] for entry in result["zones"]]
        )
        self.assertEqual(2400, result["zones"][0]["measured_seconds"])
        self.assertEqual(3600, result["zones"][0]["training_seconds"])

    def test_timezone_boundary_and_future_records_are_handled_without_provider_reads(
        self,
    ):
        rows = [
            {
                "id": "boundary",
                "start_date": "2026-09-27T23:30:00Z",
                "start_date_local": "2026-09-27T23:30:00",
                "type": "Run",
            },
            {"id": "future", "start_date_local": "2026-10-03", "type": "Run"},
        ]
        result = self.report(rows, timezone="Europe/Berlin")
        self.assertEqual(1, result["totals"]["sessions"])
        self.assertEqual("2026-09-28", result["key_sessions"][0]["date"])
        self.assertEqual(0, result["previous"]["totals"]["sessions"])

    def test_sport_filter_and_plan_execution_use_the_same_period(self):
        result = self.report(
            [
                {
                    "id": "r",
                    "start_date_local": "2026-09-28",
                    "type": "Run",
                    "icu_training_load": 0,
                },
                {
                    "id": "b",
                    "start_date_local": "2026-09-28",
                    "type": "Ride",
                    "icu_training_load": 100,
                },
            ],
            sport="Run",
            plan={
                "training_calendar": [
                    {
                        "date": "2026-09-28",
                        "type": "Run",
                        "icu_training_load": 20,
                        "compliance": {"actual_activity": {"id": "r"}},
                    }
                ]
            },
        )
        self.assertEqual(0, result["totals"]["icu_training_load"]["value"])
        self.assertEqual(1, result["planning"]["completed"])
        self.assertEqual(20, result["planning"]["load"]["value"])

    def test_records_service_reads_equipment_and_rejects_invalid_record_kinds(self):
        service = TrainingRecordsService(
            database_manager=Mock(),
            read_snapshot=dict,
            read_equipment=lambda: {"items": [{"id": "gear"}]},
            read_record=None,
        )
        self.assertEqual(
            {"equipment": {"items": [{"id": "gear"}]}}, service.training_records()
        )
        with self.assertRaises(AppError):
            service.training_records({"record_type": "other", "record_id": "gear"})

    def test_profile_selection_uses_today_and_keeps_future_activities_out(self):
        service = TrainingProfileSelectionService(lambda: date(2026, 10, 2))
        result = service.power_profiles(
            [
                {
                    "activity_id": "today",
                    "date": "2026-10-02",
                    "observed_at": "2026-10-02T00:00:00Z",
                    "sport": "Ride",
                    "power_profile": {
                        "status": "ok",
                        "points": [{"duration_seconds": 60, "watts": 200}],
                        "duration_curve": [{"duration_seconds": 60, "watts": 200}],
                    },
                },
                {
                    "activity_id": "future",
                    "date": "2026-10-03",
                    "sport": "Ride",
                    "power_profile": {
                        "status": "ok",
                        "points": [{"duration_seconds": 60, "watts": 300}],
                        "duration_curve": [{"duration_seconds": 60, "watts": 300}],
                    },
                },
            ]
        )
        self.assertEqual("today", result["best"][0]["activity_id"])

    def test_report_read_service_validates_period_and_preserves_timezone(self):
        service = TrainingReportReadService(
            read_snapshot=lambda: {"recent_activities": []},
            read_plan=dict,
            read_checkins=list,
            read_feedback=list,
            today=lambda: date(2026, 10, 2),
        )
        result = service.read({}, "Europe/Berlin")
        self.assertEqual("Europe/Berlin", result["timezone"])
        with self.assertRaises(AppError):
            service.read({"days": 3660})

    def test_derived_and_season_reads_keep_missing_data_fallbacks(self):
        derived = TrainingDerivedReadService(
            read_snapshot=dict,
            read_checkins=list,
            read_recovery=dict,
            read_performance=dict,
            today=lambda: date(2026, 10, 2),
        )
        self.assertEqual({"status": "insufficient_data"}, derived.body_history())
        self.assertEqual({"status": "insufficient_data"}, derived.sleep_regularity())
        season = TrainingSeasonReadService(
            read_snapshot=dict,
            read_competitions=list,
            read_observations=list,
            today=lambda: date(2026, 10, 2),
        )
        self.assertIsInstance(season.season("Europe/Berlin"), dict)

    def test_removed_analysis_routes_are_unmatched(self):
        auth = Mock()
        reports = Mock()
        route = AnalysisRoutes(lambda: auth, reports)
        handler = Mock()
        for path in (
            "/api/analysis/report",
            "/api/analysis/reports",
            "/api/analysis/impact",
            "/api/analysis/comparisons",
        ):
            with self.subTest(path=path):
                self.assertFalse(route.handle(handler, path))
        self.assertFalse(route.handle_post(handler, "/api/analysis/reports"))
        auth.require_auth.assert_not_called()
        reports.assert_not_called()
        handler.send_json.assert_not_called()

    def test_get_authentication_precedes_analysis_reads(self):
        auth = Mock()
        auth.require_auth.side_effect = AppError(401, "Synthetic denied")
        reports = Mock()
        route = AnalysisRoutes(lambda: auth, reports)
        for path in (
            "/api/analysis/endurance",
            "/api/analysis/power-profiles",
            "/api/analysis/season",
            "/api/analysis/training-records",
        ):
            with self.subTest(path=path), self.assertRaises(AppError):
                route.handle(Mock(), path)
        reports.assert_not_called()
