import unittest
from copy import deepcopy
from datetime import date

from backend.errors import AppError
from backend.planning.season_preparation import (
    PLANNED_LOAD_ESTIMATE_SOURCE,
    load_scenarios,
    season_preparation,
)


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

    def test_past_competition_window_is_anchored_at_event_date(self):
        event = {
            "id": "past",
            "event_date": "2026-09-01",
            "sport": "Run",
            "priority": "A",
            "name": "Past race",
        }
        snapshot = {
            "recent_activities": [
                {
                    "id": "before",
                    "type": "Run",
                    "start_date_local": "2026-06-14T09:00:00",
                    "moving_time": 1800,
                },
                {
                    "id": "first-week",
                    "type": "Run",
                    "start_date_local": "2026-06-15T09:00:00",
                    "moving_time": 1800,
                },
                {
                    "id": "sunday",
                    "type": "Run",
                    "start_date_local": "2026-08-30T09:00:00",
                    "moving_time": 1800,
                },
                {
                    "id": "after",
                    "type": "Run",
                    "start_date_local": "2026-09-02T09:00:00",
                    "moving_time": 1800,
                },
            ]
        }
        preparation = season_preparation(snapshot, [event], self.today)["events"][0][
            "preparation"
        ]
        self.assertEqual("2026-06-15", preparation["window_start"])
        self.assertEqual("2026-09-01", preparation["window_end"])
        self.assertEqual(2, preparation["sessions_84_days"])
        weeks = preparation["weeks"]
        self.assertEqual(12, len(weeks))
        for week in weeks:
            start, end = (
                date.fromisoformat(week["start"]),
                date.fromisoformat(week["end"]),
            )
            self.assertEqual(0, start.weekday())
            self.assertEqual(6, end.weekday())
        self.assertEqual("2026-06-15", weeks[0]["start"])
        self.assertEqual("2026-08-31", weeks[-1]["start"])
        self.assertEqual(12, preparation["weekly_observed_volume"]["weeks_total"])

    def test_future_competition_evidence_covers_the_weeks_up_to_today(self):
        event = {
            "id": "future",
            "event_date": "2026-12-20",
            "sport": "Run",
            "priority": "A",
            "name": "Future race",
        }
        snapshot = {
            "recent_activities": [
                {
                    "id": "run",
                    "type": "Run",
                    "start_date_local": "2026-10-01T09:00:00",
                    "moving_time": 1800,
                },
            ]
        }
        preparation = season_preparation(snapshot, [event], self.today)["events"][0][
            "preparation"
        ]
        self.assertEqual("2026-07-13", preparation["window_start"])
        self.assertEqual("2026-10-02", preparation["window_end"])
        self.assertEqual(1, preparation["sessions_84_days"])
        self.assertEqual(12, len(preparation["weeks"]))
        self.assertEqual("2026-09-28", preparation["weeks"][-1]["start"])
        self.assertEqual(1, preparation["weeks_with_recorded_training"])

    def test_far_future_competition_keeps_current_evidence(self):
        event = {
            "id": "far",
            "event_date": "2027-04-10",
            "sport": "Run",
            "priority": "B",
            "name": "Far race",
        }
        snapshot = {
            "recent_activities": [
                {
                    "id": "run",
                    "type": "Run",
                    "start_date_local": "2026-10-01T09:00:00",
                    "moving_time": 1800,
                },
            ]
        }
        preparation = season_preparation(snapshot, [event], self.today)["events"][0][
            "preparation"
        ]
        self.assertEqual("2026-07-13", preparation["window_start"])
        self.assertEqual("2026-10-02", preparation["window_end"])
        self.assertEqual(1, preparation["sessions_84_days"])
        self.assertEqual("observations", preparation["status"])

    def test_planned_load_is_estimated_from_duration_and_intensity(self):
        plan = {
            "training_calendar": [
                {
                    "id": "tempo",
                    "name": "Tempo",
                    "start_date_local": "2026-10-03T08:00:00",
                    "moving_time": 3600,
                    "icu_intensity": 0.85,
                }
            ]
        }
        snapshot = {"recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}]}
        result = load_scenarios(snapshot, plan, self.today, {"end": "2026-10-04"})
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["planned_load_estimated"])
        self.assertEqual(
            [
                {
                    "date": "2026-10-03",
                    "name": "Tempo",
                    "load": 72.25,
                    "source": PLANNED_LOAD_ESTIMATE_SOURCE,
                }
            ],
            result["estimated_planned_units"],
        )
        self.assertEqual(72.25, result["curves"][0]["points"][1]["load"])

    def test_planned_intensity_in_percent_is_read_as_intensity_factor(self):
        plan = {
            "training_calendar": [
                {
                    "start_date_local": "2026-10-03T08:00:00",
                    "moving_time": 3600,
                    "icu_intensity": 85,
                }
            ]
        }
        snapshot = {"recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}]}
        result = load_scenarios(snapshot, plan, self.today, {"end": "2026-10-04"})
        self.assertEqual(72.25, result["estimated_planned_units"][0]["load"])

    def test_recorded_planned_load_wins_over_estimate(self):
        plan = {
            "training_calendar": [
                {
                    "start_date_local": "2026-10-03T08:00:00",
                    "moving_time": 3600,
                    "icu_intensity": 0.85,
                    "icu_training_load": 50,
                }
            ]
        }
        snapshot = {"recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}]}
        result = load_scenarios(snapshot, plan, self.today, {"end": "2026-10-04"})
        self.assertFalse(result["planned_load_estimated"])
        self.assertEqual([], result["estimated_planned_units"])
        self.assertEqual(50, result["curves"][0]["points"][1]["load"])

    def test_units_without_any_load_are_listed_by_name_and_date(self):
        plan = {
            "training_calendar": [
                {"date": "2026-10-03", "name": "Intervals"},
                {
                    "date": "2026-10-04",
                    "name": "Bad intensity",
                    "moving_time": 3600,
                    "icu_intensity": 250,
                },
                {
                    "date": "2026-10-04",
                    "name": "Estimable",
                    "moving_time": 1800,
                    "icu_intensity": 0.7,
                },
            ]
        }
        snapshot = {"recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}]}
        result = load_scenarios(snapshot, plan, self.today, {"end": "2026-10-04"})
        self.assertEqual("insufficient_data", result["status"])
        self.assertEqual(
            [
                {"date": "2026-10-03", "name": "Intervals"},
                {"date": "2026-10-04", "name": "Bad intensity"},
            ],
            result["units_without_load"],
        )
        self.assertEqual(
            ["Estimable"], [unit["name"] for unit in result["estimated_planned_units"]]
        )

    def test_load_scale_accepts_german_decimal_comma(self):
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
        result = load_scenarios(
            snapshot, plan, self.today, {"end": "2026-10-04", "load_scale": "0,85"}
        )
        self.assertEqual("ok", result["status"])
        self.assertEqual(0.85, result["alternative"]["load_scale"])
        self.assertEqual(85, result["curves"][1]["points"][1]["load"])
        for invalid in ("0,4", "1,6", "nan", "abc"):
            with self.assertRaises(AppError):
                load_scenarios(
                    snapshot,
                    plan,
                    self.today,
                    {"end": "2026-10-04", "load_scale": invalid},
                )


if __name__ == "__main__":
    unittest.main()
