"""Deterministic Coach cases for the recovery comparison wording (#1426).

Each case builds synthetic observations, projects them as the Coach receives them
and checks structure and text: what the context says about coverage and limits.
Nothing here calls a model, so it shows the context and instruction text, not how
well a model answers (docs/coach-dialogue-evaluation.md).
"""

import json
import unittest
from datetime import date, timedelta
from typing import Any

from canonical_recovery_support import mapped_personal_recovery
from performance_claim_support import claim_wording_violations

from backend.coach.context import coach_performance_projection
from backend.coach.prompt import COACH_PROMPT

TODAY = date(2026, 10, 2)
NO_CLEARANCE = "Keine Diagnose, keine Trainingsfreigabe und keine Trainingsänderung"


def _wellness(nights: int, *, shift: int = 0, hrv: int = 42) -> list[dict[str, Any]]:
    return [
        {
            "id": (TODAY - timedelta(days=shift + index)).isoformat(),
            "hrv": hrv,
            "restingHR": 50,
        }
        for index in range(nights + 1)
    ]


def _coach_view(
    wellness: list[dict[str, Any]], garmin: dict[str, Any] | None = None
) -> dict[str, Any]:
    recovery = mapped_personal_recovery(wellness, garmin or {}, {}, TODAY)
    view = coach_performance_projection({"personal_recovery": recovery})
    return view["personal_recovery"]


def _baselines(view: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    return [item for item in view["baselines"] if item["metric"] == metric]


class RecoveryCoachCases(unittest.TestCase):
    def assert_coach_text_is_clean(self, view: dict[str, Any]) -> None:
        self.assertIn(NO_CLEARANCE, view["note"])
        self.assertEqual(
            [], claim_wording_violations(json.dumps(view, ensure_ascii=False))
        )

    def test_small_data_amount_gives_no_position(self):
        view = _coach_view(_wellness(9))
        for item in _baselines(view, "hrv") + _baselines(view, "resting_hr"):
            self.assertEqual("insufficient_data", item["status"])
            self.assertEqual(9, item["nights"])
            self.assertEqual(
                "Mindestens 14 frühere passende Nächte erforderlich.", item["reason"]
            )
            for key in ("position", "median", "lower", "upper"):
                self.assertNotIn(key, item)
        self.assert_coach_text_is_clean(view)

    def test_fresh_device_change_starts_a_separate_short_series(self):
        garmin = {
            "hrv": [
                {
                    "calendarDate": (TODAY - timedelta(days=day)).isoformat(),
                    "lastNightAvg": 55,
                }
                for day in range(3)
            ]
        }
        view = _coach_view(_wellness(30), garmin)
        series = {item["source_provider"]: item for item in _baselines(view, "hrv")}
        self.assertEqual({"intervals", "garmin"}, set(series))
        self.assertEqual("ok", series["intervals"]["status"])
        self.assertEqual(
            ("insufficient_data", 2),
            (series["garmin"]["status"], series["garmin"]["nights"]),
        )
        self.assertNotIn("position", series["garmin"])
        self.assert_coach_text_is_clean(view)

    def test_stale_values_keep_the_old_value_without_a_position(self):
        view = _coach_view(_wellness(30, shift=3))
        for item in _baselines(view, "hrv"):
            self.assertEqual("insufficient_data", item["status"])
            self.assertEqual("Messung veraltet.", item["reason"])
            self.assertEqual("2026-09-29", item["observed_at"])
            self.assertEqual(42.0, item["value"])
            self.assertNotIn("position", item)
        self.assert_coach_text_is_clean(view)

    def test_contradictory_heavy_checkin_beside_an_unremarkable_value(self):
        # A check-in reporting heavy legs is separate athlete context; the recovery
        # view stays a plain comparison and says an unremarkable value clears nothing.
        view = _coach_view(_wellness(30))
        (hrv,) = _baselines(view, "hrv")
        self.assertEqual(("ok", "within"), (hrv["status"], hrv["position"]))
        self.assert_coach_text_is_clean(view)
        self.assertIn("contradictory", COACH_PROMPT)
        self.assertIn("Never diagnose disease or injury.", COACH_PROMPT)


if __name__ == "__main__":
    unittest.main()
