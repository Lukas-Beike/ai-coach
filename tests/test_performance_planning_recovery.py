import unittest
from datetime import date
from typing import Any

from backend.performance.planning_recovery import planning_recovery_view

WINDOW = (date(2026, 9, 1), date(2026, 9, 7))


class _NoObservations:
    def observations(self, db: Any, kind: Any, **kwargs: Any) -> tuple[()]:
        return ()


def _battery_view(history: Any, morning: Any) -> dict[str, dict[str, Any]]:
    return planning_recovery_view(
        _NoObservations(),
        None,
        start=WINDOW[0],
        end=WINDOW[1],
        morning_battery_history=history,
        morning_body_battery=morning,
    )


class PlanningRecoveryBodyBatteryTests(unittest.TestCase):
    def test_invalid_battery_dates_and_values_are_ignored(self):
        result = _battery_view(
            {"not-a-date": 80, "2026-09-07": "not-a-number"},
            {"status": "ready", "sleep_date": "bad", "morning": {"value": 70}},
        )

        self.assertEqual(result, {})

    def test_saved_and_current_morning_body_battery(self):
        result = _battery_view(
            {"2026-09-05": 74, "2026-09-06T00:00:00Z": "75", "bad": 99},
            {
                "status": "ready",
                "sleep_date": "2026-09-06",
                "morning": {"value": 78},
            },
        )

        self.assertEqual(result["2026-09-05"]["body_battery"], 74)
        self.assertEqual(result["2026-09-06"]["body_battery"], 78)
        self.assertEqual(
            result["2026-09-06"]["sources"]["body_battery"], "Garmin Connect"
        )


if __name__ == "__main__":
    unittest.main()
