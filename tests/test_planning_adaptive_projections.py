from __future__ import annotations

import copy
import hashlib
import json
import unittest
from datetime import date

from backend.planning import adaptive


class AdaptiveProjectionTests(unittest.TestCase):
    def test_workout_is_hard_uses_name_and_description_terms_case_insensitively(self):
        self.assertTrue(adaptive.workout_is_hard({"name": "VO2 reps"}))
        self.assertTrue(adaptive.workout_is_hard({"description": "Threshold blocks"}))
        self.assertTrue(adaptive.workout_is_hard({"name": "Build to 115%"}))
        self.assertFalse(
            adaptive.workout_is_hard(
                {"name": "Easy conversational run", "description": "Z1 recovery"}
            )
        )

    def test_recovery_description_preserves_sport_specific_text_and_fallback(self):
        self.assertEqual(
            adaptive.adaptive_recovery_description("Run", 25),
            "- 25m Z1 HR Easy aerobic run at conversational effort",
        )
        self.assertEqual(
            adaptive.adaptive_recovery_description("OpenWaterSwim", 30),
            "- 30m Z1 Pace Easy relaxed swim with controlled breathing",
        )
        self.assertEqual(
            adaptive.adaptive_recovery_description("WeightTraining", 20),
            "- 20m Mobility and easy strength; stop if pain increases",
        )
        self.assertEqual(
            adaptive.adaptive_recovery_description("Other", 45),
            "- 45m Z1 HR Easy aerobic session at conversational effort",
        )

    def test_recovery_replacement_normalizes_sport_and_enforces_duration_bounds(self):
        original = {
            "sport": "OpenWaterSwim",
            "duration_minutes": 60,
            "description": "Hard set",
            "target": "PACE",
            "extra": {"keep": True},
        }
        snapshot = copy.deepcopy(original)

        replacement = adaptive.adaptive_recovery_replacement(
            original, "fatigue", available_minutes=8, max_minutes=25
        )

        self.assertEqual(replacement["duration_minutes"], 15)
        self.assertEqual(
            replacement["description"],
            "- 15m Z1 Pace Easy relaxed swim with controlled breathing",
        )
        self.assertEqual(replacement["target"], "AUTO")
        self.assertIn("fatigue", replacement["rationale"])
        self.assertEqual(replacement["extra"], original["extra"])
        self.assertEqual(original, snapshot)

        self.assertEqual(
            adaptive.adaptive_recovery_replacement(
                {"type": "cycling", "duration_minutes": 150}, "recovery"
            )["duration_minutes"],
            90,
        )
        self.assertEqual(
            adaptive.adaptive_recovery_replacement(
                {"type": "cycling", "duration_minutes": 60},
                "recovery",
                available_minutes=40,
                max_minutes=25,
            )["duration_minutes"],
            25,
        )
        self.assertEqual(
            adaptive.adaptive_recovery_replacement({}, "recovery")["duration_minutes"],
            30,
        )

    def test_private_calendar_context_bounds_and_preserves_provenance(self):
        events = [
            {
                "name": f"Event {index}" + "n" * 250,
                "event_date": "2026-09-20T14:30:00",
                "duration_minutes": str(index),
                "no_intensity": index == 11,
                "short_only": index == 10,
            }
            for index in range(12)
        ]
        draft = {"duration_minutes": 120, "nested": {"kept": True}}
        adjusted = {"duration_minutes": 60}
        before = copy.deepcopy((draft, events, adjusted))

        result = adaptive.private_calendar_adjustment_context(
            draft, events, adjusted, "r" * 1100
        )

        self.assertEqual(result["label"], "Aufgrund privater Termine angepasst")
        self.assertEqual(len(result["reason"]), 1000)
        self.assertEqual(len(result["events"]), 10)
        self.assertEqual(len(result["events"][0]["name"]), 200)
        self.assertEqual(result["events"][0]["event_date"], "2026-09-20")
        self.assertEqual(result["events"][0]["duration_minutes"], 0)
        self.assertEqual(result["original_duration_minutes"], 120)
        self.assertEqual(result["adjusted_duration_minutes"], 60)
        self.assertTrue(result["intensity_adjusted"])
        self.assertTrue(result["no_intensity_requested"])
        self.assertTrue(result["short_only_requested"])
        self.assertEqual((draft, events, adjusted), before)

        fallback = adaptive.private_calendar_adjustment_context({}, [], {}, "")
        self.assertEqual(
            fallback["reason"], "Private Termine erforderten eine Anpassung"
        )

    def test_quick_action_blockers_uses_three_day_inclusive_horizon_and_trigger_filter(
        self,
    ):
        today = date(2026, 9, 20)
        preview = {
            "status": "preview",
            "changes": [
                {"date": "2026-09-19", "blocking_triggers": ["illness"]},
                {
                    "date": "2026-09-20T00:00:00",
                    "blocking_triggers": ["weather", "unknown", "calendar"],
                },
                {"date": "2026-09-22", "blocking_triggers": ["injury"]},
                {"date": "2026-09-23", "blocking_triggers": ["illness"]},
                {"date": "bad-date", "blocking_triggers": ["calendar"]},
                {"date": "2026-09-21", "blocking_triggers": "illness"},
                {"date": "2026-09-21", "blocking_triggers": ["load"]},
                {"date": "2026-09-21", "blocking_triggers": ["illness"]},
            ],
        }
        before = copy.deepcopy(preview)

        blockers = adaptive.adaptive_quick_action_blockers(
            preview, today, label="L" * 250
        )

        self.assertEqual(
            blockers,
            [
                {
                    "date": "2026-09-20",
                    "name": "L" * 200,
                    "triggers": ["calendar", "weather"],
                },
                {
                    "date": "2026-09-22",
                    "name": "L" * 200,
                    "triggers": ["injury"],
                },
                {
                    "date": "2026-09-21",
                    "name": "L" * 200,
                    "triggers": ["illness"],
                },
            ],
        )
        self.assertEqual(preview, before)
        self.assertEqual(
            adaptive.adaptive_quick_action_blockers(
                {"status": "applied", "changes": preview["changes"]},
                today,
                label="Planned",
            ),
            [],
        )
        self.assertEqual(
            adaptive.adaptive_quick_action_blockers(None, today, label="Planned"),
            [],
        )

    def test_adaptive_fingerprint_hashes_exact_mutable_field_projection(self):
        workout = {
            "date": "2026-09-21",
            "name": "Tempo – test",
            "type": "Run",
            "duration_minutes": 45,
            "description": "- 45m Z2",
            "target": "HR",
            "rationale": "adjusted",
            "private_calendar_adjustment": {"reason": "private"},
            "id": "ignored-id",
            "extra": "ignored-extra",
        }
        before = copy.deepcopy(workout)
        fields = (
            "date",
            "name",
            "type",
            "duration_minutes",
            "description",
            "target",
            "rationale",
            "private_calendar_adjustment",
        )
        source = {key: workout.get(key) for key in fields}
        expected = hashlib.sha256(
            json.dumps(
                source, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(adaptive.adaptive_workout_fingerprint(workout), expected)
        self.assertEqual(
            adaptive.adaptive_workout_fingerprint({**workout, "extra": "changed"}),
            expected,
        )
        self.assertNotEqual(
            adaptive.adaptive_workout_fingerprint({**workout, "target": "AUTO"}),
            expected,
        )
        self.assertEqual(workout, before)

    def test_illness_forecast_truncates_text_and_uses_injected_days(self):
        today = date(2026, 12, 30)
        feedback = {"illness": "  " + "a" * 20 + "  "}
        before = copy.deepcopy(feedback)

        forecast = adaptive.illness_pause_forecast(
            feedback, today, illness_text_limit=5, default_days=4
        )

        self.assertEqual(forecast["start_date"], "2026-12-30")
        self.assertEqual(forecast["end_date"], "2027-01-02")
        self.assertEqual(forecast["recommended_pause_days"], 4)
        self.assertEqual(forecast["illness"], "aaaaa")
        self.assertIn("keine medizinische Diagnose", forecast["forecast"])
        self.assertIsNone(
            adaptive.illness_pause_forecast(
                {"illness": "  "}, today, illness_text_limit=20, default_days=3
            )
        )
        self.assertEqual(feedback, before)

    def test_illness_pause_replacement_archives_without_mutating_workout(self):
        workout = {"date": "2026-09-21", "rationale": "original", "nested": [1]}
        before = copy.deepcopy(workout)

        result = adaptive.illness_pause_replacement(workout, "flu")

        self.assertTrue(result["archived"])
        self.assertEqual(result["date"], workout["date"])
        self.assertIn("Krankheitspause: flu.", result["rationale"])
        self.assertEqual(workout, before)

    def test_illness_calendar_events_are_inclusive_and_use_injected_values(self):
        pause = {"start_date": "2026-02-28T12:00:00", "end_date": "2026-03-01"}
        before = copy.deepcopy(pause)
        illness = "  " + "x" * 12005 + "  "

        events = adaptive.illness_calendar_events(
            pause,
            illness,
            category="CUSTOM_SICK",
            external_prefix="synthetic-",
            midnight_suffix="T05:00:00Z",
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            [event["external_id"] for event in events],
            ["synthetic-2026-02-28", "synthetic-2026-03-01"],
        )
        self.assertEqual(events[0]["category"], "CUSTOM_SICK")
        self.assertEqual(events[0]["start_date_local"], "2026-02-28T05:00:00Z")
        self.assertEqual(events[1]["name"], "Krankheit")
        self.assertEqual(len(events[0]["description"]), 12000)
        self.assertEqual(events[0]["description"], "x" * 12000)
        self.assertEqual(pause, before)

        empty_illness = adaptive.illness_calendar_events(
            {"start_date": "2026-09-20", "end_date": "2026-09-20"},
            "",
            category="SICK",
            external_prefix="sick-",
            midnight_suffix="T00:00:00",
        )
        self.assertEqual(empty_illness[0]["description"], "Krankheit")


if __name__ == "__main__":
    unittest.main()
