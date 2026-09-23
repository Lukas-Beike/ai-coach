import ast
import json
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from backend.planning.daily_context_service import DailyPlanningContextService


class FakeDatabaseManager:
    def __init__(self):
        self.unit_of_work_calls = 0
        self.active_connection = None

    @contextmanager
    def unit_of_work(self):
        self.unit_of_work_calls += 1
        if self.active_connection is not None:
            yield self.active_connection
            return
        self.active_connection = object()
        try:
            yield self.active_connection
        finally:
            self.active_connection = None


class FakeKeyValueRepository:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def get(self, db, key):
        self.calls.append((db, key))
        return self.values.get(key)


class FakeCheckinService:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def list(self, limit):
        self.calls.append(limit)
        return self.rows


class FakeCalendarReader:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def list_events(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.rows


class FakeMorningBodyBatteryService:
    def __init__(self, record=None):
        self.record = record
        self.calls = []

    def current(self, snapshot):
        self.calls.append(snapshot)
        return self.record


class FakeActivityFeedbackService:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def list(self, limit):
        self.calls.append(limit)
        return self.rows


class DailyPlanningContextServiceTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 20)
        self.today_calls = 0
        self.database_manager = FakeDatabaseManager()
        self.key_values = FakeKeyValueRepository({})
        self.checkins = FakeCheckinService()
        self.calendar = FakeCalendarReader()
        self.morning_battery = FakeMorningBodyBatteryService()
        self.feedback = FakeActivityFeedbackService()
        self.service = DailyPlanningContextService(
            self.database_manager,
            self.key_values,
            self.checkins,
            self.calendar,
            self.morning_battery,
            self.feedback,
            self._today,
            35,
        )

    def _today(self):
        self.today_calls += 1
        return self.today

    def test_valid_overrides_skip_checkin_and_calendar_reads(self):
        result = self.service.build(
            snapshot={"recent_wellness": []},
            planned=[{"id": "planned", "start_date_local": "2026-09-20"}],
            weather={"days": [{"date": "2026-09-20", "condition": "rain"}]},
            checkins=[{"checkin_date": "2026-09-20", "motivation": 8}],
            calendar_events=[
                {
                    "id": "appointment",
                    "event_date": "2026-09-20",
                    "start_local": "2026-09-20T12:00:00",
                    "end_local": "2026-09-20T13:00:00",
                }
            ],
        )

        self.assertEqual(self.checkins.calls, [])
        self.assertEqual(self.calendar.calls, [])
        self.assertEqual(result[0]["planned"][0]["id"], "planned")
        self.assertEqual(result[0]["checkin"]["motivation"], 8)
        self.assertEqual(result[0]["weather"]["condition"], "rain")
        self.assertEqual(result[0]["appointments"][0]["id"], "appointment")

    def test_invalid_overrides_use_empty_inputs_and_default_reads(self):
        self.checkins.rows = [{"checkin_date": "2026-09-20", "stress": 2}]
        self.calendar.rows = []
        result = self.service.build(
            snapshot=[],
            planned={},
            weather={"days": {}},
            checkins={},
            calendar_events={},
        )

        self.assertEqual(result[0]["checkin"]["stress"], 2)
        self.assertNotIn("planned", result[0])
        self.assertNotIn("weather", result[0])
        self.assertEqual(self.checkins.calls, [30])
        self.assertEqual(self.calendar.calls, [((), {"training_relevant_only": True})])

    def test_default_reads_are_bounded_and_read_only(self):
        with self.database_manager.unit_of_work() as outer_db:
            self.service.build()

        self.assertEqual(self.database_manager.unit_of_work_calls, 2)
        self.assertEqual(
            [key for _db, key in self.key_values.calls],
            ["garmin_snapshot", "morning_body_battery_history"],
        )
        self.assertIs(self.key_values.calls[0][0], self.key_values.calls[1][0])
        self.assertIs(self.key_values.calls[0][0], outer_db)
        self.assertEqual(self.checkins.calls, [30])
        self.assertEqual(self.calendar.calls, [((), {"training_relevant_only": True})])
        self.assertEqual(self.feedback.calls, [500])
        self.assertEqual(self.today_calls, 1)
        self.assertEqual(self.morning_battery.calls, [{}])

    def test_corrupt_and_non_object_garmin_values_fail_soft(self):
        for stored_value in ("{broken", "[]", None):
            with self.subTest(stored_value=stored_value):
                self.key_values.values["garmin_snapshot"] = stored_value
                self.morning_battery.calls.clear()
                result = self.service.build()
                self.assertEqual(self.morning_battery.calls, [{}])
                self.assertEqual(result, [])

    def test_corrupt_history_is_empty_and_does_not_break_garmin_projection(self):
        self.key_values.values.update(
            {
                "garmin_snapshot": json.dumps(
                    {"daily_stats": [{"date": "2026-09-20", "steps": 12000}]}
                ),
                "morning_body_battery_history": "not-json",
            }
        )

        result = self.service.build()

        self.assertEqual(result[0]["health"]["steps"], 12000)
        self.assertNotIn("recovery", result[0])

    def test_merges_recovery_health_weather_feedback_and_checkin(self):
        self.key_values.values.update(
            {
                "garmin_snapshot": json.dumps(
                    {
                        "sleep": [
                            {
                                "calendarDate": "2026-09-20",
                                "sleepTimeSeconds": 28_800,
                                "sleepScore": 90,
                            }
                        ],
                        "daily_stats": [{"date": "2026-09-20", "totalSteps": 9000}],
                    }
                ),
                "morning_body_battery_history": json.dumps({"2026-09-19": 64}),
            }
        )
        self.morning_battery.record = {
            "status": "ready",
            "sleep_date": "2026-09-20",
            "morning": {"value": 76},
        }
        self.feedback.rows = [
            {
                "activity_id": "activity-1",
                "activity_date": "2026-09-20",
                "notes": "felt good",
            }
        ]
        result = self.service.build(
            snapshot={
                "recent_wellness": [
                    {
                        "id": "2026-09-20",
                        "ctl": 80,
                        "atl": 60,
                        "tsb": 20,
                    }
                ]
            },
            planned=[{"id": "unit-1", "start_date_local": "2026-09-20"}],
            weather={"days": [{"date": "2026-09-20", "temperature_max": 17}]},
            checkins=[{"checkin_date": "2026-09-20", "motivation": 9}],
            calendar_events=[],
        )

        today = next(day for day in result if day["date"] == "2026-09-20")
        self.assertEqual(today["recovery"]["sleep_hours"], 8.0)
        self.assertEqual(today["recovery"]["ctl"], 80)
        self.assertEqual(today["recovery"]["body_battery"], 76)
        self.assertEqual(today["health"]["steps"], 9000)
        self.assertEqual(today["weather"]["temperature_max"], 17)
        self.assertEqual(today["activity_feedback"][0]["activity_id"], "activity-1")
        self.assertEqual(today["checkin"]["motivation"], 9)
        yesterday = next(day for day in result if day["date"] == "2026-09-19")
        self.assertEqual(yesterday["recovery"]["body_battery"], 64)

    def test_today_is_sampled_once_and_calendar_window_is_forwarded(self):
        service = DailyPlanningContextService(
            self.database_manager,
            self.key_values,
            self.checkins,
            self.calendar,
            self.morning_battery,
            self.feedback,
            self._today,
            1,
        )
        result = service.build(
            calendar_events=[
                {
                    "id": "multi-day",
                    "event_date": "2026-09-18",
                    "start_local": "2026-09-18T12:00:00",
                    "end_local": "2026-09-23T00:00:00",
                }
            ]
        )

        self.assertEqual(self.today_calls, 1)
        self.assertEqual(
            [day["date"] for day in result],
            ["2026-09-19", "2026-09-20", "2026-09-21"],
        )

    def test_module_has_explicit_dependencies_and_no_server_or_callback_bundle(self):
        source_path = (
            Path(__file__).parents[1]
            / "backend"
            / "planning"
            / "daily_context_service.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertNotIn("server", {name.partition(".")[0] for name in imports})
        self.assertIn("backend.planning.context", imports)
        self.assertIn("backend.performance.daily_health", imports)
        self.assertIn("backend.performance.planning_recovery", imports)
        self.assertIn("backend.weather.history", imports)

        service = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "DailyPlanningContextService"
        )
        constructor = next(
            node
            for node in service.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        parameters = [argument.arg for argument in constructor.args.args]
        self.assertEqual(
            parameters,
            [
                "self",
                "database_manager",
                "key_value_repository",
                "checkin_service",
                "external_calendar_reader",
                "morning_body_battery_service",
                "activity_feedback_service",
                "today",
                "calendar_window_days",
            ],
        )
        self.assertFalse(
            {"callbacks", "dependencies", "readers"}.intersection(parameters)
        )


if __name__ == "__main__":
    unittest.main()
