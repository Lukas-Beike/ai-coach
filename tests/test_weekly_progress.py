"""Weekly per-sport progress projection and its Coach tool contract."""

import unittest
from datetime import date
from unittest.mock import Mock

import server
from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.errors import AppError
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.report_service import TrainingReportReadService
from backend.planning.season_preparation import load_scenarios
from tests.test_training_report import (
    _empty_season_source,
    _FakeDatabaseManager,
    _Rows,
    _summary,
)


class _EmptyReader:
    def observations(self, db, kind, *, start=None, end=None):
        return []

    def power_curve(self, db):
        raise AssertionError("the power curve is not read")

    def activity_summaries(self, db, *, start=None, end=None, limit=None):
        return ()


def _zones(*seconds):
    return [{"id": f"Z{n}", "secs": secs} for n, secs in enumerate(seconds, 1)]


class WeeklyProgressTests(unittest.TestCase):
    TODAY = date(2026, 10, 2)  # Friday; the week of 2026-09-28 is running

    def _service(self, rows=(), plan=None, records=()):
        return TrainingReportReadService(
            read_synced_at=lambda _db: None,
            read_plan=lambda: plan,
            read_checkins=list,
            read_feedback=list,
            today=lambda: self.TODAY,
            load_scenarios=load_scenarios,
            season_source=_empty_season_source(),
            canonical=CanonicalPerformanceSource(
                database_manager=_FakeDatabaseManager,
                observation_reader=_EmptyReader,
                activity_summaries=lambda: _Rows(rows),
            ),
            curve_records=lambda: list(records),
        )

    def _progress(self, values=None, **options):
        rows = options.pop("rows", ())
        return self._service(rows, **options).progress(values or {"days": 28}, "UTC")

    def test_weekly_aggregation_per_sport_and_intensity_mapping(self):
        rows = [
            _summary(
                "r1",
                "2026-09-22T08:00:00",
                sport="ride",
                moving_duration_s=3600,
                training_load=50,
                sources={"training_load": "Intervals.icu"},
                power_zone_times=_zones(600, 600, 600, 600, 600, 300, 300),
            ),
            _summary(
                "u1",
                "2026-09-23T08:00:00",
                sport="run",
                moving_duration_s=1800,
                heart_rate_zone_times=_zones(100, 100, 100, 100, 100),
            ),
            _summary("s1", "2026-09-24", sport="strength", moving_duration_s=900),
        ]
        result = self._progress(rows=rows)
        week = next(w for w in result["week_list"] if w["week_start"] == "2026-09-21")
        self.assertEqual("recorded", week["status"])
        self.assertEqual(3, week["sports"]["all"]["sessions"])
        ride = week["sports"]["ride"]
        self.assertEqual(
            {"low": 1200, "moderate": 1200, "high": 1200},
            ride["intensity_3zone"]["seconds"],
        )
        self.assertEqual(50, ride["training_load"]["value"])
        self.assertEqual("Intervals.icu", ride["training_load"]["source"])
        run = week["sports"]["run"]["intensity_3zone"]
        self.assertEqual({"low": 200, "moderate": 100, "high": 200}, run["seconds"])
        self.assertEqual(["heart_rate"], run["sensors"])
        strength = week["sports"]["strength"]
        self.assertEqual(1, strength["sessions"])
        self.assertIsNone(strength["intensity_3zone"]["seconds"])
        self.assertEqual(0, week["sports"]["run"]["session_rpe_load"]["rated_sessions"])

    def test_incomplete_and_empty_weeks_are_unknown_not_rest(self):
        rows = [_summary("a", "2026-09-29T08:00:00", moving_duration_s=600)]
        weeks = {w["week_start"]: w for w in self._progress(rows=rows)["week_list"]}
        self.assertEqual("incomplete_current_week", weeks["2026-09-28"]["status"])
        self.assertEqual("no_records_unknown", weeks["2026-09-21"]["status"])
        self.assertNotIn("sports", weeks["2026-09-21"])

    def test_sport_filter_limits_buckets(self):
        rows = [
            _summary("a", "2026-09-29", sport="ride", moving_duration_s=600),
            _summary("b", "2026-09-29", sport="run", moving_duration_s=600),
        ]
        result = self._progress({"days": 7, "sport": "run"}, rows=rows)
        sports = result["week_list"][0]["sports"]
        self.assertEqual(["run"], list(sports))
        self.assertEqual(1, sports["run"]["sessions"])

    def test_plan_compliance_per_week(self):
        plan = {
            "training_calendar": [
                {
                    "starts_at_local": "2026-09-29T07:00:00",
                    "sport": "run",
                    "compliance": {"actual_activity": {"id": "x"}},
                },
                {
                    "starts_at_local": "2026-09-30T07:00:00",
                    "sport": "run",
                    "compliance": {"status": "missed"},
                },
            ]
        }
        rows = [_summary("a", "2026-09-29", sport="run", moving_duration_s=600)]
        result = self._progress({"days": 7}, rows=rows, plan=plan)
        self.assertEqual(
            {"available": True, "planned": 2, "completed": 1, "missed": 1},
            result["week_list"][0]["sports"]["run"]["plan"],
        )

    def test_mean_max_change_between_halves_for_ride_and_run(self):
        def ride(day, watts):
            return {
                "date": day,
                "sport": "ride",
                "power_profile": {
                    "status": "ok",
                    "source": "Test provider streams",
                    "duration_curve": [{"duration_seconds": 300, "watts": watts}],
                },
            }

        def run(day, speed):
            return {
                "date": day,
                "sport": "run",
                "running_profile": {
                    "status": "ok",
                    "source": "Test provider streams",
                    "speed": [{"duration_seconds": 300, "speed_mps": speed}],
                },
            }

        records = [
            ride("2026-09-09", 250),
            ride("2026-09-30", 270),
            run("2026-09-10", 3.5),
            run("2026-09-29", 3.75),
        ]
        result = self._progress({"days": 28}, records=records)["mean_max_power"]
        five = {
            sport: next(
                d for d in result[sport]["durations"] if d["duration_seconds"] == 300
            )
            for sport in ("ride", "run")
        }
        self.assertEqual(20, five["ride"]["change_watts"])
        self.assertEqual(0.25, five["run"]["change_speed_mps"])
        self.assertEqual("Test provider streams", result["ride"]["source"])
        self.assertEqual(1, result["run"]["periods"]["later"]["usable_records"])

    def test_accepted_windows_and_rejected_values(self):
        for days in (7, 28, 42, 84):
            self.assertEqual(days // 7, self._progress({"days": days})["weeks"])
        for values in ({"days": 14}, {"days": 3660}, {"sport": "ride; drop"}):
            with self.subTest(values=values), self.assertRaises(AppError):
                self._progress(values)

    def test_report_section_keeps_its_windows(self):
        with self.assertRaises(AppError):
            self._service().read({"days": 42})


class ProgressToolTests(unittest.TestCase):
    def test_long_windows_belong_to_the_progress_section(self):
        report = Mock()
        report.progress.return_value = {"weeks": 12}
        reports = Mock(report=report)
        reports.timezone.return_value = "UTC"
        service = CoachActivityReadToolService(
            Mock(), Mock(), Mock(), date.today, reports
        )
        result = service.execute("get_training_report", {"days": 84})
        self.assertEqual({"weeks": 12}, result["progress"])
        self.assertEqual(["progress"], result["projection"]["requested_sections"])
        report.read.assert_not_called()
        for arguments in (
            {"days": 42, "sections": ["report"]},
            {"days": 84, "sections": ["progress", "report"]},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(AppError):
                service.execute("get_training_report", arguments)

    def test_tool_schema_offers_long_windows_and_progress(self):
        tool = next(
            tool
            for tool in server.COACH_DIALOGUE_TOOLS
            if tool["name"] == "get_training_report"
        )
        properties = tool["parameters"]["properties"]
        self.assertEqual([7, 28, 42, 84], properties["days"]["enum"])
        self.assertIn("progress", properties["sections"]["items"]["enum"])


if __name__ == "__main__":
    unittest.main()
