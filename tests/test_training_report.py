"""Training report coverage and historical zone contracts."""

import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock, patch

from support import GOLDEN_FIRST, dispatch_route, golden_history, payload_digest

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.http_api.analysis import AnalysisRoutes
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.report_service import (
    TrainingDerivedReadService,
    TrainingProfileSelectionService,
    TrainingRecordsService,
    TrainingReportReadService,
    TrainingSeasonReadService,
)
from backend.performance.season_inputs import SeasonSource
from backend.performance.tag_impact import tag_impact
from backend.performance.training_report import training_report
from backend.planning.season_preparation import season_preparation


class _EmptyReader:
    """Observation and activity-row reader over an empty store."""

    def observations(self, db, kind, *, start, end):
        return []

    def activity_summaries(self, db, *, start=None, end=None, limit=None):
        return ()


class _FakeUnitOfWork:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


class _FakeDatabaseManager:
    def unit_of_work(self):
        return _FakeUnitOfWork()

    read_snapshot = unit_of_work
    reader = unit_of_work


class _Rows:
    """Activity summary reader over fixed summaries."""

    def __init__(self, rows):
        self._rows = tuple(rows)

    def activity_summaries(self, db, *, start=None, end=None, limit=None):
        return self._rows


class _Coverage:
    """Provider coverage with one Intervals.icu activity fetch time."""

    def __init__(self, fetched_at):
        self._fetched_at = fetched_at

    def coverage(self, db):
        return (
            ProviderCoverage(
                provider=ProviderId.GARMIN,
                retrieved_at=self._fetched_at,
                activity_count=0,
                observation_count=0,
                issue_counts={},
                first_observed_on=None,
                last_observed_on=None,
                activities_retrieved_at=self._fetched_at,
            ),
        )


def _canonical(rows=(), fetched_at=None):
    return CanonicalPerformanceSource(
        database_manager=_FakeDatabaseManager,
        observation_reader=_EmptyReader,
        activity_summaries=lambda: _Rows(rows),
        coverage=None if fetched_at is None else lambda: _Coverage(fetched_at),
    )


def _empty_season_source():
    return SeasonSource(
        database_manager=_FakeDatabaseManager,
        observation_reader=_EmptyReader,
        activity_summaries=_EmptyReader,
    )


def _summary(key, local, *, sport="ride", **values):
    """A summary as the activity summary reader returns it."""
    if "T" not in local:
        local += "T00:00:00"
    return {"id": key, "started_at_local": local, "sport": sport, **values}


class TrainingReportTests(unittest.TestCase):
    def test_power_profile_windows_keep_sport_provenance_and_cache_gaps(self):
        records = [
            {
                "activity_id": "outdoor",
                "date": "2026-10-01",
                "sport": "ride",
                "environment": "outdoor",
                "activity_type": "ride",
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
                "sport": "ride",
                "environment": "indoor",
                "activity_type": "ride",
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
                "sport": "ride",
                "environment": "outdoor",
                "activity_type": "ride",
                "source": "Intervals.icu",
                "device": "Garmin",
                "power_profile": {"status": "insufficient_data", "duration_curve": []},
            },
            {
                "activity_id": "run-without-streams",
                "date": "2026-10-01",
                "sport": "run",
                "environment": "outdoor",
                "activity_type": "run",
                "source": "Garmin Connect",
                "device": "Garmin",
                "running_profile": {"status": "insufficient_data"},
            },
        ]
        result = TrainingProfileSelectionService._profile_window(
            records, date(2026, 10, 2), 28
        )
        self.assertEqual(4, result["cache_coverage"]["records"])
        self.assertEqual(2, result["cache_coverage"]["usable_records"])
        self.assertEqual(2, result["cache_coverage"]["unknown_records"])
        # The power coverage counts rides only; the run cannot hold a power best.
        self.assertEqual(3, result["cache_coverage"]["power_records"])
        self.assertEqual(1, result["cache_coverage"]["power_unknown_records"])
        power = [point for point in result["power"] if point["duration_seconds"] == 60]
        self.assertEqual(
            {"outdoor": 240, "indoor": 300},
            {point["environment"]: point["watts"] for point in power},
        )
        self.assertEqual({"ride"}, {point["sport"] for point in power})
        outdoor = next(point for point in power if point["environment"] == "outdoor")
        indoor = next(point for point in power if point["environment"] == "indoor")
        self.assertEqual("Wahoo ELEMNT", outdoor["device"])
        self.assertEqual("Zwift", indoor["device"])
        self.assertEqual("Intervals.icu", outdoor["source"])

    def test_running_speed_selects_fastest_effort_and_distance_selects_shortest(self):
        records = [
            {
                "activity_id": "steady",
                "date": "2026-10-01",
                "sport": "run",
                "activity_type": "run",
                "running_profile": {
                    "status": "ok",
                    "speed": [{"duration_seconds": 60, "speed_mps": 3.0}],
                    "distance": [{"distance_meters": 1000, "seconds": 330}],
                },
            },
            {
                "activity_id": "fast",
                "date": "2026-10-01",
                "sport": "run",
                "activity_type": "run",
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

    def test_eight_week_load_totals_keep_missing_zero_and_boundaries(self):
        result = self.report(
            [
                _summary("old", "2026-08-10", training_load=90),
                _summary("outside", "2026-08-09", training_load=100),
                _summary("last-sunday", "2026-09-27", training_load=10),
                _summary(
                    "monday",
                    "2026-09-27T23:30:00",
                    sport="run",
                    started_at="2026-09-27T23:30:00+00:00",
                    training_load=30,
                ),
                _summary("missing", "2026-09-29"),
                _summary("zero", "2026-09-30", training_load=0),
                _summary("future", "2026-10-03", training_load=50),
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
            [_summary("zero", "2026-09-28", training_load=0)], sport="ride"
        )
        self.assertEqual(ride["weekly_load"][-1]["training_load"]["value"], 0)

    def test_daily_chart_keeps_unknown_duration_future_and_timezone_boundaries(self):
        result = self.report(
            [
                _summary(
                    "one",
                    "2026-09-27T23:30:00",
                    name="Easy run",
                    sport="run",
                    started_at="2026-09-27T23:30:00+00:00",
                    moving_duration_s=1800,
                    training_load=25,
                ),
                _summary("two", "2026-09-28"),
                _summary("future", "2026-10-04", sport="run", moving_duration_s=3600),
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
        self.assertEqual(monday["totals"]["moving_duration_s"]["value"], 1800)
        self.assertEqual(monday["totals"]["moving_duration_s"]["measured_sessions"], 1)
        self.assertIsNone(monday["sports"]["ride"]["moving_duration_s"]["value"])
        self.assertIsNone(result["daily"][1]["totals"]["moving_duration_s"]["value"])
        self.assertTrue(result["daily"][-1]["future"])
        self.assertEqual(result["daily"][-1]["totals"]["sessions"], 0)

    def test_cumulative_week_load_is_flat_without_sessions_and_increases_by_contributions(
        self,
    ):
        result = self.report(
            [
                _summary("wed", "2026-09-30", sport="run", training_load=30),
                _summary("fri", "2026-10-02", training_load=50),
                _summary("prior", "2026-09-27", training_load=100),
            ]
        )
        self.assertEqual(
            [day["cumulative_training_load"]["value"] for day in result["daily"]],
            [0, 0, 30, 30, 80, None, None],
        )
        self.assertEqual(result["weekly_load"][-1]["training_load"]["value"], 80)

    def test_feedback_follows_the_stored_activity_key_and_preserves_zero_rpe(
        self,
    ):
        result = self.report(
            [
                _summary(
                    "act_1",
                    "2026-09-28",
                    sport="run",
                    record_ids={"intervals": "i-one"},
                ),
                _summary("act_2", "2026-09-28"),
            ],
            activity_feedback=[
                {
                    "activity_id": "act_1",
                    "notes": "Easy",
                    "session_rpe": 0,
                    "deviation_reason": "shortened",
                },
                {"activity_id": "act_2", "notes": "Session id key"},
                {"activity_id": "i-one", "notes": "Not the stored key"},
                {"activity_id": "outside", "notes": "Excluded"},
            ],
        )
        self.assertEqual(
            [("act_1", "Easy"), ("act_2", "Session id key")],
            [
                (item["activity_id"], item["notes"])
                for item in result["activity_feedback"]
            ],
        )
        self.assertEqual(result["activity_feedback"][0]["session_rpe"], 0)
        self.assertEqual(
            result["activity_feedback"][0]["deviation_reason"], "shortened"
        )

    def report(self, rows, **kwargs):
        return training_report(
            start=date(2026, 9, 28),
            days=7,
            today=date(2026, 10, 2),
            activity_summaries=rows,
            **kwargs,
        )

    def test_missing_load_remains_unknown(self):
        row = _summary(
            "one", "2026-09-28T08:00:00", sport="run", moving_duration_s=1800
        )
        result = self.report([row])
        self.assertEqual(1, result["totals"]["sessions"])
        self.assertIsNone(result["totals"]["training_load"]["value"])
        self.assertEqual(0, result["totals"]["training_load"]["measured_sessions"])
        self.assertNotIn("excluded_duplicates", result)
        self.assertTrue(result["partial_period"])

    def test_sensor_zones_stay_separate_and_strength_is_not_classified_as_endurance(
        self,
    ):
        rows = [
            _summary(
                "ride",
                "2026-09-29",
                moving_duration_s=3600,
                power_zone_times=[{"id": "Z2", "secs": 2400}],
                heart_rate_zone_times=[{"id": "Z1", "secs": 1800}],
            ),
            _summary(
                "strength",
                "2026-09-29",
                sport="strength",
                moving_duration_s=1800,
                heart_rate_zone_times=[{"id": "Z5", "secs": 1800}],
            ),
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
            _summary(
                "boundary",
                "2026-09-27T23:30:00",
                sport="run",
                started_at="2026-09-27T23:30:00+00:00",
            ),
            _summary("future", "2026-10-03", sport="run"),
        ]
        result = self.report(rows, timezone="Europe/Berlin")
        self.assertEqual(1, result["totals"]["sessions"])
        self.assertEqual("2026-09-28", result["key_sessions"][0]["date"])
        self.assertEqual(0, result["previous"]["totals"]["sessions"])

    def test_sport_filter_and_plan_execution_use_the_same_period(self):
        result = self.report(
            [
                _summary("r", "2026-09-28", sport="run", training_load=0),
                _summary("b", "2026-09-28", training_load=100),
            ],
            sport="run",
            plan={
                "training_calendar": [
                    {
                        "date": "2026-09-28",
                        "sport": "run",
                        "planned_load": 20,
                        "compliance": {"actual_activity": {"id": "r"}},
                    },
                    {"date": "2026-09-28", "sport": "ride", "planned_load": 40},
                ]
            },
        )
        self.assertEqual(0, result["totals"]["training_load"]["value"])
        self.assertEqual(["run"], list(result["sports"]))
        self.assertEqual(1, result["planning"]["sessions"])
        self.assertEqual(1, result["planning"]["completed"])
        self.assertEqual(20, result["planning"]["load"]["value"])

    def test_records_service_reads_equipment_and_rejects_invalid_record_kinds(self):
        service = TrainingRecordsService(
            database_manager=Mock(),
            read_equipment=lambda: {"items": [{"id": "gear"}]},
            read_record=None,
            canonical=_canonical(),
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
                    "sport": "ride",
                    "environment": "outdoor",
                    "power_profile": {
                        "status": "ok",
                        "points": [{"duration_seconds": 60, "watts": 200}],
                        "duration_curve": [{"duration_seconds": 60, "watts": 200}],
                    },
                },
                {
                    "activity_id": "future",
                    "date": "2026-10-03",
                    "sport": "ride",
                    "environment": "outdoor",
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
            read_plan=dict,
            read_checkins=list,
            read_feedback=lambda keys: [],
            today=lambda: date(2026, 10, 2),
            canonical=_canonical(),
        )
        result = service.read({}, "Europe/Berlin")
        self.assertEqual("Europe/Berlin", result["timezone"])
        with self.assertRaises(AppError):
            service.read({"days": 3660})

    def test_derived_and_season_reads_keep_missing_data_fallbacks(self):
        derived = TrainingDerivedReadService(
            read_checkins=list,
            read_recovery=dict,
            read_performance=dict,
            today=lambda: date(2026, 10, 2),
            canonical=_canonical(),
        )
        self.assertEqual({"status": "insufficient_data"}, derived.body_history())
        self.assertEqual(
            {"status": "insufficient_data"}, derived.sleep_timing_variability()
        )
        season = TrainingSeasonReadService(
            read_competitions=list,
            read_observations=list,
            today=lambda: date(2026, 10, 2),
            season_preparation=season_preparation,
            season_source=_empty_season_source(),
        )
        self.assertIsInstance(season.season("Europe/Berlin"), dict)

    def _report_service(self, canonical, snapshot_rows=()):
        # Canonical reads (#1416): the report reads no snapshot; the rows only
        # document what a stored snapshot would still hold.
        del snapshot_rows
        return TrainingReportReadService(
            read_plan=dict,
            read_checkins=list,
            read_feedback=lambda keys: [],
            today=lambda: date(2026, 10, 2),
            canonical=canonical,
        )

    def test_report_reads_canonical_rows_and_coverage_time_not_the_snapshot(self):
        ride = _summary(
            "canonical",
            "2026-09-30T08:00:00",
            moving_duration_s=3600,
            distance_m=30000,
        )
        fetched = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
        service = self._report_service(
            _canonical([ride], fetched), snapshot_rows=[{**ride, "id": "stale"}] * 3
        )

        result = service.read({"start": "2026-09-28", "days": 7})

        self.assertEqual(1, result["totals"]["sessions"])
        self.assertEqual(fetched.isoformat(), result["observed_at"])

    def test_report_sport_filter_takes_canonical_sports(self):
        service = self._report_service(_canonical())
        service.read({"start": "2026-09-28", "days": 7, "sport": "nordic_ski"})
        # A previous Intervals.icu token resolves to its canonical sport.
        service.read({"start": "2026-09-28", "days": 7, "sport": "Ride"})
        for invalid in ("ride; drop", "x" * 41):
            with self.subTest(sport=invalid), self.assertRaises(AppError):
                service.read({"start": "2026-09-28", "days": 7, "sport": invalid})

    def test_observations_join_stored_analyses_by_live_session(self):
        current = _summary(
            "act_1",
            "2026-09-30T08:00:00",
            name="Ride",
            moving_duration_s=3600,
            avg_temp_c=12.5,
            recorded_by="wahoo",
            environment="virtual",
            record_ids={"intervals": "i-1", "wahoo": "w-1"},
        )
        garmin_only = _summary("act_3", "2026-09-30T10:00:00")
        stored = [
            {
                "session_id": key,
                "source": "Wahoo",
                "observed_at": "2026-10-01T00:00:00Z",
            }
            for key in ("act_1", "act_gone", "act_3")
        ]
        canonical = CanonicalPerformanceSource(
            database_manager=_FakeDatabaseManager,
            observation_reader=_EmptyReader,
            activity_summaries=lambda: _Rows([current, garmin_only]),
        )
        service = TrainingRecordsService(
            database_manager=Mock(),
            read_equipment=dict,
            read_record=None,
            canonical=canonical,
        )
        with patch(
            "backend.performance.report_service.analysis_summaries",
            return_value=stored,
        ):
            records = service.observations()

        # Garmin-only sessions take part; a gone session is skipped.
        self.assertEqual(["act_1", "act_3"], [row["activity_id"] for row in records])
        record = records[0]
        self.assertEqual("Wahoo", record["source"])
        self.assertNotIn("session_id", record)
        self.assertEqual(
            ("2026-09-30", "ride", "indoor", 3600.0, 12.5, "wahoo"),
            (
                record["date"],
                record["sport"],
                record["environment"],
                record["duration"],
                record["average_temp"],
                record["device"],
            ),
        )

    def test_tag_impact_sums_day_loads_of_every_session_and_keeps_unknown(self):
        checkins = [
            {"checkin_date": f"2026-08-{day:02d}", "tag_answers": {"travel": True}}
            for day in range(1, 11)
        ]
        history = [
            {"date": f"2026-08-{day:02d}", "value": float(day)} for day in range(2, 12)
        ]
        summaries = [
            _summary("a", "2026-08-01T08:00:00", training_load=40),
            _summary("b", "2026-08-01T18:00:00", training_load=20),
            _summary("c", "2026-08-02T08:00:00"),
        ]
        result = tag_impact(
            checkins,
            {
                "baselines": [
                    {
                        "metric": "sleep",
                        "source": "Intervals.icu",
                        "measurement": "duration",
                        "unit": "hours",
                        "history": history,
                    }
                ]
            },
            date(2026, 9, 1),
            activity_summaries=summaries,
        )
        report = next(row for row in result["reports"] if row["tag"] == "travel")
        loads = {
            row["date"]: row["load"] for row in report["groups"]["with"]["evidence"]
        }
        self.assertEqual(60, loads["2026-08-01"])
        self.assertIsNone(loads["2026-08-02"])

    def test_report_without_stored_coverage_has_no_observed_time(self):
        service = self._report_service(_canonical(), snapshot_rows=[{"id": "x"}])

        result = service.read({"start": "2026-09-28", "days": 7})

        self.assertEqual(0, result["totals"]["sessions"])
        self.assertIsNone(result["observed_at"])

    def test_report_services_require_a_canonical_source(self):
        with self.assertRaises(TypeError):
            TrainingDerivedReadService(  # type: ignore[call-arg]
                read_checkins=list,
                read_recovery=dict,
                read_performance=dict,
                today=lambda: date(2026, 10, 2),
            )
        source = CanonicalPerformanceSource(
            database_manager=_FakeDatabaseManager, observation_reader=_EmptyReader
        )
        with self.assertRaises(RuntimeError):
            self._report_service(source).read({"start": "2026-09-28", "days": 7})

    def test_removed_analysis_routes_are_unmatched(self):
        reports = Mock()
        route = AnalysisRoutes(reports)
        handler = Mock()
        for path in (
            "/api/analysis/report",
            "/api/analysis/reports",
            "/api/analysis/impact",
            "/api/analysis/comparisons",
            "/api/analysis/endurance",
            "/api/analysis/season",
        ):
            with self.subTest(path=path):
                self.assertFalse(dispatch_route(route, handler, path))
        for path in ("/api/analysis/reports", "/api/analysis/scenarios"):
            with self.subTest(path=path):
                self.assertFalse(dispatch_route(route, handler, path, method="POST"))
        reports.assert_not_called()
        handler.send_json.assert_not_called()

    def test_analysis_refresh_delegates_selected_area(self):
        refresh = Mock()
        refresh.refresh.return_value = {"area": "recovery", "status": "partial"}
        handler = Mock()
        handler.read_json.return_value = {"area": "recovery"}
        route = AnalysisRoutes(Mock(), lambda: refresh)

        self.assertTrue(
            dispatch_route(route, handler, "/api/analysis/refresh", method="POST")
        )

        refresh.refresh.assert_called_once_with("recovery", days=None)
        handler.send_json.assert_called_once_with(200, refresh.refresh.return_value)

    def test_analysis_refresh_rejects_unknown_area(self):
        from backend.errors import AppError

        handler = Mock()
        handler.read_json.return_value = {"area": "everything"}
        route = AnalysisRoutes(Mock(), Mock())

        with self.assertRaises(AppError) as raised:
            dispatch_route(route, handler, "/api/analysis/refresh", method="POST")

        self.assertEqual(400, raised.exception.status)

    def test_golden_load_curves_of_the_all_sport_report(self):
        sessions, feedback, loads = golden_history()
        arguments = {
            "start": GOLDEN_FIRST + timedelta(days=102),
            "days": 28,
            "today": GOLDEN_FIRST + timedelta(days=129),
            "timezone": "UTC",
            "activity_summaries": sessions,
            "observed_at": "2026-05-05T07:00:00+00:00",
            "session_feedback": feedback,
            "computed_at": "2026-05-10T08:00:00+00:00",
            "local_load_days": loads,
        }
        result = training_report(**arguments)
        curves = {
            name: result[name]
            for name in ("smoothed_session_load", "local_fitness_fatigue")
        }
        self.assertEqual(
            payload_digest(curves),
            "891572b34763ff85fe6c6841c656a9f93a2c832694282586908bcb807d96c3b5",
        )
        ride = training_report(**arguments, sport="ride")
        self.assertIsNone(ride["smoothed_session_load"])
        self.assertIsNone(ride["local_fitness_fatigue"])
