import unittest
from copy import deepcopy
from datetime import date

from backend.errors import AppError
from backend.performance.season_preparation import load_scenarios, season_preparation


class SeasonPreparationTests(unittest.TestCase):
    today = date(2026, 10, 2)

    def test_preparation_is_observed_and_does_not_follow_calendar_phase(self):
        event = {
            "id": "race",
            "event_date": "2026-10-10",
            "sport": "Running",
            "priority": "A",
            "name": "Synthetic race",
        }
        result = season_preparation({}, [event], self.today)["events"][0]
        self.assertEqual("taper", result["phase"])
        self.assertEqual("insufficient_data", result["preparation"]["status"])
        snapshot = {
            "recent_activities": [
                {
                    "id": "run",
                    "type": "Run",
                    "start_date_local": "2026-10-01T10:00:00",
                    "moving_time": 3600,
                }
            ]
        }
        result = season_preparation(snapshot, [event], self.today)["events"][0]
        self.assertEqual("observations", result["preparation"]["status"])
        self.assertEqual(
            "run", result["preparation"]["long_sessions"][0]["activity_id"]
        )

    def test_scenarios_are_deterministic_nonmutating_and_taper_changes_load(self):
        snapshot = {"recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}]}
        plan = {
            "training_calendar": [
                {
                    "id": "local",
                    "start_date_local": "2026-10-03",
                    "icu_training_load": 100,
                }
            ]
        }
        values = {"end": "2026-10-04", "load_scale": 0.8, "taper_days": 2}
        original = deepcopy((snapshot, plan, values))
        result = load_scenarios(snapshot, plan, self.today, values)
        self.assertEqual(result, load_scenarios(snapshot, plan, self.today, values))
        self.assertEqual(original, (snapshot, plan, values))
        self.assertEqual(100, result["curves"][0]["points"][1]["load"])
        self.assertEqual(40, result["curves"][1]["points"][1]["load"])
        changed = load_scenarios(
            snapshot, {"training_calendar": []}, self.today, values
        )
        self.assertNotEqual(result["input_sha256"], changed["input_sha256"])

    def test_missing_basis_or_planned_load_is_not_zero_filled(self):
        values = {"end": "2026-10-04"}
        self.assertEqual(
            "insufficient_data", load_scenarios({}, {}, self.today, values)["status"]
        )
        snapshot = {"recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}]}
        self.assertEqual(
            "insufficient_data",
            load_scenarios(
                snapshot,
                {"training_calendar": [{"date": "2026-10-03"}]},
                self.today,
                values,
            )["status"],
        )
        for invalid in (
            {"end": "2027-10-02"},
            {"end": "2026-10-04", "load_scale": "nan"},
        ):
            with self.assertRaises(AppError):
                load_scenarios(snapshot, {}, self.today, invalid)

    def test_completed_today_load_is_fixed_and_not_double_counted_or_scaled(self):
        activity = {
            "id": "done",
            "start_date_local": "2026-10-02T08:00:00",
            "icu_training_load": 60,
        }
        snapshot = {
            "recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}],
            "recent_activities": [activity],
        }
        plan = {
            "training_calendar": [
                {
                    "date": "2026-10-02",
                    "icu_training_load": 50,
                    "compliance": {"actual_activity": activity},
                }
            ]
        }
        values = {"end": "2026-10-03", "load_scale": 0.5, "taper_days": 2}
        result = load_scenarios(snapshot, plan, self.today, values)
        self.assertEqual(
            [curve["points"][0]["load"] for curve in result["curves"]], [60, 60]
        )
        changed = load_scenarios(
            {**snapshot, "recent_activities": [{**activity, "icu_training_load": 70}]},
            plan,
            self.today,
            values,
        )
        self.assertNotEqual(result["input_sha256"], changed["input_sha256"])

    def test_race_context_requires_confirmed_units_and_reports_known_dimensions(self):
        event = {
            "id": "race",
            "event_date": "2027-04-10",
            "sport": "Run",
            "priority": "B",
            "distance": "21.0975 km",
            "target": "01:45:00",
            "name": "Half",
        }
        activity = {
            "id": "run",
            "type": "Run",
            "start_date_local": "2026-10-01T07:00:00",
            "moving_time": 7200,
            "distance": 18000,
        }
        analyses = [
            {
                "activity_id": "run",
                "aerobic": {"status": "ok"},
                "power_profile": {"status": "insufficient_data"},
                "interval_quality": {"status": "ok"},
            }
        ]
        result = season_preparation(
            {"recent_activities": [activity]},
            [event],
            self.today,
            observations=analyses,
        )["events"][0]["preparation"]
        self.assertEqual(21097.5, result["target_context"]["distance_meters"])
        self.assertTrue(result["target_context"]["target_confirmed"])
        self.assertEqual(1, result["weekly_observed_volume"]["weeks_with_sessions"])
        self.assertEqual(7200, result["long_session_evidence"]["duration_seconds"])
        self.assertEqual(
            {"aerobic": 1, "power_profile": 0, "interval_quality": 1},
            result["specificity_evidence"]["known_dimensions"],
        )

    def test_no_history_unknown_distance_and_target_remain_nullable(self):
        event = {
            "id": "race",
            "event_date": "2027-04-10",
            "sport": "Ride",
            "priority": "B",
            "distance": "Gran Fondo",
            "target": "",
            "name": "Event",
        }
        result = season_preparation({}, [event], self.today)["events"][0]["preparation"]
        self.assertEqual("insufficient_data", result["status"])
        self.assertIsNone(result["target_context"]["distance_meters"])
        self.assertFalse(result["target_context"]["distance_confirmed"])
        self.assertIsNone(result["target_context"]["target"])
        self.assertEqual(
            "insufficient_data", result["weekly_observed_volume"]["status"]
        )
        self.assertIsNone(result["weekly_observed_volume"]["distance_meters"])
        self.assertIsNone(result["long_session_evidence"]["duration_seconds"])
        self.assertEqual("insufficient_data", result["specificity_evidence"]["status"])

    def test_numeric_race_distance_needs_reliable_meter_scale(self):
        for distance, expected in (
            ("21.1", None),
            ("21097", 21097),
            ("21.1 km", 21100),
            ("half marathon", None),
        ):
            event = {
                "id": "race",
                "event_date": "2027-04-10",
                "sport": "Run",
                "priority": "B",
                "distance": distance,
                "name": "Event",
            }
            actual = season_preparation({}, [event], self.today)["events"][0][
                "preparation"
            ]["target_context"]["distance_meters"]
            self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
