"""Focused regression tests for local workout-library projections."""

import copy
import unittest
import uuid

from backend.errors import AppError
from backend.planning import library

LOCAL_ID = "01234567-89ab-cdef-0123-456789abcdef"
EXPECTED_LIBRARY_FIELDS = {
    "name",
    "description",
    "type",
    "moving_time",
    "duration_minutes",
    "distance",
    "target",
    "workout_doc",
    "icu_training_load",
    "icu_intensity",
    "indoor",
    "tags",
    "folder_id",
    "date",
    "rationale",
    "plan_id",
    "plan_name",
    "source",
    "private_calendar_adjustment",
    "archived",
    "local_marked",
    "local_deleted",
    "remote_event_id",
    "remote_event_external_id",
    "category",
    "paired_event_id",
}


class LibraryWorkoutNormalizationTests(unittest.TestCase):
    def test_rejects_non_objects_and_invalid_local_uuids(self):
        with self.assertRaises(AppError) as invalid_object:
            library.normalize_library_workout([{"name": "Run"}])
        self.assertEqual(invalid_object.exception.status, 400)
        self.assertEqual(
            invalid_object.exception.message,
            "Jede Bibliothekseinheit muss ein Objekt sein.",
        )

        with self.assertRaises(AppError) as invalid_uuid:
            library.normalize_library_workout({"name": "Run"}, local_id="not-a-uuid")
        self.assertEqual(invalid_uuid.exception.status, 400)
        self.assertEqual(
            invalid_uuid.exception.message,
            "Bibliothekseinheit ohne gültige lokale UUID.",
        )

    def test_generates_valid_uuid_without_relying_on_its_value(self):
        normalized = library.normalize_library_workout({"name": "Run"})
        parsed_id = uuid.UUID(normalized["id"])
        self.assertEqual(parsed_id.version, 4)
        self.assertIsNone(normalized["external_id"])

    def test_local_and_external_identity_rules(self):
        local = library.normalize_library_workout({"id": LOCAL_ID}, sync_status="local")
        self.assertEqual(local["id"], LOCAL_ID)
        self.assertIsNone(local["external_id"])
        self.assertEqual(local["sync_status"], "local")

        uppercase_local = library.normalize_library_workout({"id": LOCAL_ID.upper()})
        self.assertEqual(uppercase_local["id"], LOCAL_ID)
        self.assertIsNone(uppercase_local["external_id"])

        remote = library.normalize_library_workout(
            {"id": "remote-17"}, local_id=LOCAL_ID
        )
        self.assertEqual(remote["id"], LOCAL_ID)
        self.assertEqual(remote["external_id"], "remote-17")

        mapped = library.normalize_library_workout(
            {"id": "remote-17", "external_id": "stale-map"},
            local_id=LOCAL_ID,
            external_id="authoritative-map",
        )
        self.assertEqual(mapped["external_id"], "authoritative-map")

        stored_mapping = library.normalize_library_workout(
            {"id": LOCAL_ID, "external_id": "remote-17"}
        )
        self.assertEqual(stored_mapping["id"], LOCAL_ID)
        self.assertEqual(stored_mapping["external_id"], "remote-17")

    def test_projection_whitelist_truncation_sport_and_duration(self):
        workout = {
            "name": "n" * 250,
            "description": "d" * 13000,
            "type": "Running",
            "moving_time": 3601,
            "date": "2026-09-20-extra",
            "rationale": "r" * 2100,
            "plan_name": "p" * 250,
            "source": "s" * 60,
            "tags": ["endurance"],
            "archived": 1,
            "local_marked": "yes",
            "local_deleted": 0,
            "private_token": "must not escape",
        }
        original = copy.deepcopy(workout)

        normalized = library.normalize_library_workout(workout, local_id=LOCAL_ID)

        self.assertEqual(workout, original)
        self.assertEqual(normalized["id"], LOCAL_ID)
        self.assertEqual(normalized["type"], "Run")
        self.assertEqual(normalized["duration_minutes"], 60)
        self.assertEqual(len(normalized["name"]), 200)
        self.assertEqual(len(normalized["description"]), 12000)
        self.assertEqual(normalized["date"], "2026-09-20")
        self.assertEqual(len(normalized["rationale"]), 2000)
        self.assertEqual(len(normalized["plan_name"]), 200)
        self.assertEqual(len(normalized["source"]), 40)
        self.assertTrue(normalized["archived"])
        self.assertTrue(normalized["local_marked"])
        self.assertFalse(normalized["local_deleted"])
        self.assertNotIn("private_token", normalized)
        self.assertEqual(library.LIBRARY_WORKOUT_FIELDS, EXPECTED_LIBRARY_FIELDS)
        self.assertEqual(
            set(normalized),
            (EXPECTED_LIBRARY_FIELDS & workout.keys())
            | {
                "id",
                "external_id",
                "sync_status",
                "duration_minutes",
                "archived",
                "local_marked",
                "local_deleted",
            },
        )

    def test_duration_derivation_and_fallback(self):
        short = library.normalize_library_workout(
            {"moving_time": 120}, local_id=LOCAL_ID
        )
        self.assertEqual(short["duration_minutes"], 5)

        explicit = library.normalize_library_workout(
            {"duration_minutes": 45, "moving_time": 3600}, local_id=LOCAL_ID
        )
        self.assertEqual(explicit["duration_minutes"], 45)

        invalid = library.normalize_library_workout(
            {"moving_time": "unknown"}, local_id=LOCAL_ID
        )
        self.assertNotIn("duration_minutes", invalid)

        self.assertEqual(
            library.library_workout_duration_minutes(
                {"duration_minutes": -1, "moving_time": 600}
            ),
            10,
        )
        self.assertIsNone(library.library_workout_duration_minutes({"moving_time": -1}))


class LibraryWorkoutMatchingTests(unittest.TestCase):
    def setUp(self):
        self.workout = {
            "sport": "Ride",
            "name": "Easy endurance ride",
            "description": "- 60m Z1 HR Easy endurance ride",
            "duration_minutes": 60,
        }
        self.exact = {
            "type": "Ride",
            "name": "Easy endurance ride",
            "description": "- 60m Z1 HR Easy endurance ride",
            "duration_minutes": 60,
        }
        self.near = {
            **self.exact,
            "description": "- 60m Z1 HR Easy endurance ride steady",
        }

    def test_sport_and_text_normalization(self):
        self.assertEqual(library.workout_library_type("Cycling"), "Ride")
        self.assertEqual(library.workout_library_type("Ride"), "Ride")
        self.assertEqual(library.normalized_workout_text("  Z2 / 85% "), "z2 85%")

    def test_exact_and_conservative_near_matches(self):
        original = copy.deepcopy((self.workout, self.exact, self.near))
        self.assertIs(
            library.find_similar_library_workout(self.workout, [self.exact]), self.exact
        )
        self.assertIs(
            library.find_similar_library_workout(self.workout, [self.near]), self.near
        )
        self.assertIs(
            library.find_similar_library_workout(self.workout, [self.near, self.exact]),
            self.exact,
        )
        self.assertEqual((self.workout, self.exact, self.near), original)

    def test_no_match_for_unrelated_or_invalid_candidates(self):
        unrelated = {
            **self.exact,
            "name": "Maximal intervals",
            "description": "- 60m Z4 HR maximal intervals",
        }
        wrong_sport = {**self.exact, "type": "Run"}
        invalid_structure = {**self.exact, "description": "- 60m easy endurance ride"}
        self.assertIsNone(
            library.find_similar_library_workout(
                self.workout, [None, unrelated, wrong_sport, invalid_structure]
            )
        )
        self.assertIsNone(
            library.find_similar_library_workout(
                {**self.workout, "duration_minutes": "invalid"}, [self.exact]
            )
        )

    def test_duration_tolerance_and_exact_remote_match(self):
        self.assertTrue(library.compatible_workout_duration(60, None))
        self.assertTrue(library.compatible_workout_duration(60, 72))
        self.assertFalse(library.compatible_workout_duration(60, 72.01))
        self.assertTrue(
            library.library_workout_matches(
                self.exact, {**self.exact, "duration_minutes": 61}
            )
        )
        self.assertFalse(
            library.library_workout_matches(
                self.exact, {**self.exact, "duration_minutes": 62}
            )
        )

    def test_library_is_a_required_explicit_dependency(self):
        with self.assertRaises(TypeError):
            library.find_similar_library_workout(self.workout)


if __name__ == "__main__":
    unittest.main()
