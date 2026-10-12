"""Planning-side export model: sport translation, export builder, and validation edges."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from backend.canonical.planned_workout import PlannedWorkoutExport
from backend.canonical.vocabulary import Environment, Sport
from backend.errors import AppError
from backend.planning.sport import planned_sport_environment
from backend.planning.workout_export import (
    WORKOUT_TARGET_TYPES,
    build_planned_workout_export,
)
from backend.planning.workout_validation import validate_workout_description

TODAY = date(2026, 9, 20)


def workout(**overrides):
    return {
        "date": TODAY.isoformat(),
        "sport": "WeightTraining",
        "name": "Strength",
        "description": "Oberkoerperkraft: 3x8 Wiederholungen",
        "duration_minutes": 35,
        "target": "AUTO",
        **overrides,
    }


class PlannedSportEnvironmentTests(unittest.TestCase):
    def test_known_intervals_types_map_to_canonical_sport_and_environment(self):
        self.assertEqual(
            planned_sport_environment("VirtualRide"), (Sport.RIDE, Environment.VIRTUAL)
        )
        self.assertEqual(
            planned_sport_environment("TrailRun"), (Sport.RUN, Environment.OUTDOOR)
        )
        self.assertEqual(
            planned_sport_environment("WeightTraining"),
            (Sport.STRENGTH, Environment.UNKNOWN),
        )

    def test_missing_sport_defaults_to_ride_like_the_provider_payload(self):
        self.assertEqual(
            planned_sport_environment(None), (Sport.RIDE, Environment.UNKNOWN)
        )

    def test_unknown_sport_falls_back_to_other(self):
        self.assertEqual(
            planned_sport_environment("Curling"), (Sport.OTHER, Environment.UNKNOWN)
        )


class BuildPlannedWorkoutExportTests(unittest.TestCase):
    def assert_app_error(self, call, message):
        with self.assertRaises(AppError) as caught:
            call()
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(str(caught.exception), message)

    def test_builds_export_fields_from_a_strength_unit(self):
        export = build_planned_workout_export(workout(), today=TODAY)

        self.assertEqual(
            export,
            PlannedWorkoutExport(
                start_date_local="2026-09-20T00:00:00",
                sport=Sport.STRENGTH,
                environment=Environment.UNKNOWN,
                sport_token="WeightTraining",
                name="Strength",
                description="Oberkoerperkraft: 3x8 Wiederholungen",
                duration_seconds=35 * 60,
                target="AUTO",
            ),
        )

    def test_explicit_start_time_is_kept_and_truncated_to_forty_characters(self):
        start = "2026-09-20T07:30:00+02:00" + "x" * 30
        export = build_planned_workout_export(
            workout(start_date_local=start), today=TODAY
        )
        self.assertEqual(export.start_date_local, start[:40])

    def test_structured_steps_drive_duration_and_known_target_is_kept(self):
        export = build_planned_workout_export(
            workout(
                sport="Ride",
                description="- 10m 60%",
                duration_minutes=10,
                target="POWER",
            ),
            today=TODAY,
        )
        self.assertEqual(export.duration_seconds, 600)
        self.assertEqual(export.target, "POWER")
        self.assertEqual(export.sport, Sport.RIDE)
        self.assertEqual(export.sport_token, "Ride")

    def test_unknown_target_falls_back_to_auto(self):
        export = build_planned_workout_export(workout(target="CADENCE"), today=TODAY)
        self.assertEqual(export.target, "AUTO")
        self.assertEqual(WORKOUT_TARGET_TYPES, {"AUTO", "POWER", "HR", "PACE"})

    def test_type_is_used_when_sport_is_absent_and_token_is_empty_without_either(self):
        export = build_planned_workout_export(
            workout(
                sport=None, type="Run", description="- 10m 60%", duration_minutes=10
            ),
            today=TODAY,
        )
        self.assertEqual(export.sport_token, "Run")
        self.assertEqual(export.sport, Sport.RUN)

        without_sport = build_planned_workout_export(
            workout(sport=None, description="- 10m 60%", duration_minutes=10),
            today=TODAY,
        )
        self.assertEqual(without_sport.sport_token, "")
        self.assertEqual(without_sport.sport, Sport.RIDE)

    def test_missing_name_and_description_use_defaults(self):
        export = build_planned_workout_export(
            workout(name=None, description=None), today=TODAY
        )
        self.assertEqual(export.name, "Coach workout")
        self.assertEqual(export.description, "")

    def test_missing_or_malformed_date_is_rejected(self):
        message = "Das Trainingsdatum muss das Format JJJJ-MM-TT haben."
        missing = workout()
        del missing["date"]
        self.assert_app_error(
            lambda: build_planned_workout_export(missing, today=TODAY), message
        )
        self.assert_app_error(
            lambda: build_planned_workout_export(
                workout(date="2026-13-01"), today=TODAY
            ),
            message,
        )

    def test_units_older_than_yesterday_are_not_exported(self):
        past = (TODAY - timedelta(days=2)).isoformat()
        self.assert_app_error(
            lambda: build_planned_workout_export(workout(date=past), today=TODAY),
            "Eine Einheit in der Vergangenheit wird nicht übertragen.",
        )
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        export = build_planned_workout_export(workout(date=yesterday), today=TODAY)
        self.assertEqual(export.start_date_local, f"{yesterday}T00:00:00")

    def test_duration_outside_five_to_six_hundred_minutes_is_rejected(self):
        message = "Die Trainingsdauer muss zwischen 5 und 600 Minuten liegen."
        for duration in (4, 601):
            with self.subTest(duration=duration), self.assertRaises(AppError) as caught:
                build_planned_workout_export(
                    workout(duration_minutes=duration), today=TODAY
                )
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(str(caught.exception), message)


class WorkoutValidationEdgeTests(unittest.TestCase):
    def test_bare_bullet_line_is_rejected_by_the_structured_step_parser(self):
        with self.assertRaises(AppError) as caught:
            validate_workout_description(
                workout(sport="Ride", description="-\n- 10m 60%", duration_minutes=10)
            )
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("Workout-Zeile 1", str(caught.exception))

    def test_non_finite_duration_is_not_checked_against_structured_steps(self):
        self.assertEqual(
            validate_workout_description(
                workout(sport="Ride", description="- 10m 60%", duration_minutes="nan")
            ),
            600,
        )


if __name__ == "__main__":
    unittest.main()
