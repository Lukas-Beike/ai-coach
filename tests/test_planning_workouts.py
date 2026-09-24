"""Direct tests for local workout normalization and provider readback checks."""

import unittest
from datetime import date, timedelta

from backend.errors import AppError
from backend.planning.workouts import (
    intervals_workout_sport,
    normalize_workout,
    validate_intervals_workout_result,
    validate_workout_description,
    workout_event_payload,
)

TODAY = date(2026, 9, 20)


def workout(description="- 30m 85%", **overrides):
    return {
        "date": (TODAY + timedelta(days=1)).isoformat(),
        "sport": "Ride",
        "name": "Synthetic workout",
        "description": description,
        "duration_minutes": 30,
        "target": "AUTO",
        **overrides,
    }


def valid_readback(sport="Ride"):
    return {
        "type": sport,
        "moving_time": 1800,
        "icu_training_load": 35,
        "workout_doc": {
            "duration": 1800,
            "steps": [{"duration": 1800, "power": {"units": "%ftp", "value": 85}}],
        },
    }


class PlanningWorkoutTests(unittest.TestCase):
    def assert_app_error(self, operation, *, status=None, reason=None, message=None):
        with self.assertRaises(AppError) as raised:
            operation()
        error = raised.exception
        if status is not None:
            self.assertEqual(error.status, status)
        if reason is not None:
            self.assertEqual(error.reason, reason)
        if message is not None:
            self.assertEqual(str(error), message)
        return error

    def test_sport_normalization_handles_aliases_case_and_unknown_values(self):
        self.assertEqual(intervals_workout_sport("  Rad-Indoor "), "VirtualRide")
        self.assertEqual(intervals_workout_sport("trailrun"), "TrailRun")
        self.assertEqual(intervals_workout_sport("  jog  "), "Run")
        self.assertEqual(intervals_workout_sport("new activity"), "Other")
        self.assertEqual(intervals_workout_sport(None), "Ride")

    def test_ambiguous_steps_keep_german_message_and_reason(self):
        self.assert_app_error(
            lambda: validate_workout_description(workout("- locker 10m Z1 HR")),
            status=400,
            reason="ambiguous_workout_step",
            message=(
                "Workout-Text in Zeile 1 ist mehrdeutig: Trainingsschritte mit '- ' muessen direkt mit Dauer oder Distanz beginnen "
                "(z.B. '- 6km Z1 HR'). Hinweise, Bedingungen und optionale Gesamtstrecken als eigenen Absatz ohne '- ' schreiben; "
                "sonst zaehlt Intervals.icu sie als weitere Schritte."
            ),
        )
        self.assert_app_error(
            lambda: validate_workout_description(workout("- 10m Z1 HR plus 2km Z2 HR")),
            reason="ambiguous_workout_step",
        )

    def test_endurance_parser_preserves_missing_step_and_target_reasons(self):
        self.assert_app_error(
            lambda: validate_workout_description(workout("Easy endurance ride")),
            reason="missing_workout_steps",
            message="Ausdauer-Einheit ohne auswertbare Trainingsschritte.",
        )
        self.assert_app_error(
            lambda: validate_workout_description(workout("- 30m locker")),
            reason="missing_workout_target",
            message="Workout-Zeile 1: Auswertbares Intensitaetsziel fehlt.",
        )

    def test_composite_time_and_thirty_second_tolerance(self):
        description = "- 1h30m Z2\n- 30s Z1"
        self.assertEqual(
            validate_workout_description(workout(description, duration_minutes=90)),
            5430,
        )
        self.assertEqual(
            validate_workout_description(workout("- 90m30s Z2", duration_minutes=90)),
            5430,
        )
        self.assert_app_error(
            lambda: validate_workout_description(
                workout("- 90m31s Z2", duration_minutes=90)
            ),
            status=400,
            reason="workout_duration_mismatch",
        )

    def test_distance_steps_allow_estimated_total_but_preserve_timed_subtotal(self):
        run = workout(
            "- 10m Z1 HR\n- 1km Z2 HR", sport="Run", target="HR", duration_minutes=30
        )
        self.assertIsNone(validate_workout_description(run))
        payload = workout_event_payload("run-1", run, today=TODAY)
        self.assertEqual(payload["moving_time"], 1800)
        self.assertEqual(payload["external_id"], "intervals-coach-run-1")
        self.assert_app_error(
            lambda: validate_workout_description({**run, "duration_minutes": 5}),
            reason="workout_duration_mismatch",
        )

    def test_event_date_boundary_and_duration_limits(self):
        yesterday = workout(
            date=(TODAY - timedelta(days=1)).isoformat(),
            sport="Yoga",
            description="Free text",
        )
        self.assertEqual(
            workout_event_payload("yesterday", yesterday, today=TODAY)["type"], "Yoga"
        )
        self.assert_app_error(
            lambda: workout_event_payload(
                "old",
                {**yesterday, "date": (TODAY - timedelta(days=2)).isoformat()},
                today=TODAY,
            ),
            status=400,
            message="Eine Einheit in der Vergangenheit wird nicht übertragen.",
        )
        self.assert_app_error(
            lambda: workout_event_payload(
                "bad-date", {**yesterday, "date": "20.09.2026"}, today=TODAY
            ),
            status=400,
            message="Das Trainingsdatum muss das Format JJJJ-MM-TT haben.",
        )
        for duration in (4, 601):
            with self.subTest(duration=duration):
                self.assert_app_error(
                    lambda duration=duration: workout_event_payload(
                        "bad-duration",
                        {**yesterday, "duration_minutes": duration},
                        today=TODAY,
                    ),
                    status=400,
                    message="Die Trainingsdauer muss zwischen 5 und 600 Minuten liegen.",
                )
        self.assertEqual(
            workout_event_payload(
                "limits", {**yesterday, "duration_minutes": 600}, today=TODAY
            )["moving_time"],
            36000,
        )

    def test_normalize_canonicalizes_endurance_zones_and_keeps_non_endurance_prose(
        self,
    ):
        normalized = normalize_workout(
            workout(
                "  - 30m Zone 2 HR  ",
                date=" 2026-09-21 ",
                sport="running",
                name="  Easy run  ",
                duration_minutes="30",
                target="unsupported",
                rationale="  Recovery  ",
            ),
            today=TODAY,
        )
        self.assertEqual(normalized["sport"], "Run")
        self.assertEqual(normalized["description"], "- 30m Z2 HR")
        self.assertEqual(normalized["date"], "2026-09-21")
        self.assertEqual(normalized["target"], "AUTO")
        self.assertEqual(normalized["name"], "Easy run")
        self.assertEqual(normalized["rationale"], "Recovery")

        prose = normalize_workout(
            workout("Zone 2 movement and balance", sport="Yoga", duration_minutes=35),
            today=TODAY,
        )
        self.assertEqual(prose["description"], "Zone 2 movement and balance")

    def test_normalize_validates_object_text_and_duration(self):
        self.assert_app_error(
            lambda: normalize_workout([], today=TODAY),
            status=400,
            message="Jede geplante Einheit muss ein Objekt sein.",
        )
        self.assert_app_error(
            lambda: normalize_workout(workout(" "), today=TODAY),
            status=400,
            message="Jede geplante Einheit benötigt Workout-Text.",
        )
        self.assert_app_error(
            lambda: normalize_workout(workout(rationale=" "), today=TODAY),
            status=400,
            message="Jede geplante Einheit benötigt eine Begründung.",
        )
        self.assert_app_error(
            lambda: normalize_workout(workout(duration_minutes="30.5"), today=TODAY),
            status=400,
            message="Die Trainingsdauer muss eine ganze Zahl sein.",
        )

    def test_normalize_and_payload_keep_existing_text_limits_and_unknown_sport(self):
        normalized = normalize_workout(
            workout(
                "x" * 12001,
                sport="unlisted activity",
                name="n" * 201,
                rationale="r" * 2001,
                duration_minutes=30,
            ),
            today=TODAY,
        )
        self.assertEqual(normalized["sport"], "Other")
        self.assertEqual(len(normalized["name"]), 200)
        self.assertEqual(len(normalized["description"]), 12000)
        self.assertEqual(len(normalized["rationale"]), 2000)
        payload = workout_event_payload("limits", normalized, today=TODAY)
        self.assertEqual(payload["type"], "Other")
        self.assertEqual(len(payload["description"]), 12000)

    def test_remote_sport_and_readback_are_checked_without_provider_calls(self):
        local = workout()
        validate_intervals_workout_result(local, valid_readback())
        self.assert_app_error(
            lambda: validate_intervals_workout_result(local, {"type": "Run"}),
            status=502,
            reason="intervals_workout_sport_mismatch",
            message="Intervals.icu hat die Sportart nicht korrekt bestaetigt.",
        )
        invalid = valid_readback()
        invalid["workout_doc"]["steps"][0]["duration"] = 1200
        self.assert_app_error(
            lambda: validate_intervals_workout_result(local, invalid),
            status=502,
            reason="intervals_workout_verification_failed",
            message="Intervals.icu hat die Einheit nicht korrekt bestaetigt.",
        )
        strength = workout("Technik und Beweglichkeit", sport="WeightTraining")
        validate_intervals_workout_result(strength, {"type": "WeightTraining"})


if __name__ == "__main__":
    unittest.main()
