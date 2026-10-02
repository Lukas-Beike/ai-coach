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
        activity = {"id": "done", "start_date_local": "2026-10-02T08:00:00", "icu_training_load": 60}
        snapshot = {"recent_wellness": [{"id": "2026-10-01", "ctl": 50, "atl": 60}], "recent_activities": [activity]}
        plan = {"training_calendar": [{"date": "2026-10-02", "icu_training_load": 50, "compliance": {"actual_activity": activity}}]}
        values = {"end": "2026-10-03", "load_scale": 0.5, "taper_days": 2}
        result = load_scenarios(snapshot, plan, self.today, values)
        self.assertEqual([curve["points"][0]["load"] for curve in result["curves"]], [60, 60])
        changed = load_scenarios({**snapshot, "recent_activities": [{**activity, "icu_training_load": 70}]}, plan, self.today, values)
        self.assertNotEqual(result["input_sha256"], changed["input_sha256"])


if __name__ == "__main__":
    unittest.main()
