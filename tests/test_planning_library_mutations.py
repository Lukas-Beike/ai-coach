"""Direct tests for pure local workout-library mutation logic."""

import copy
import unittest

from backend.errors import AppError
from backend.planning import library

LOCAL_ID = "01234567-89ab-cdef-0123-456789abcdef"


class WorkoutLibraryMutationTests(unittest.TestCase):
    def test_entry_id_canonicalizes_uuid_and_preserves_error_contract(self):
        self.assertEqual(library.workout_library_entry_id(LOCAL_ID.upper()), LOCAL_ID)

        with self.assertRaises(AppError) as raised:
            library.workout_library_entry_id("not-a-uuid")
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, "Ungültige Bibliothekseinheiten-ID.")

    def test_candidate_archive_restore_and_update_are_copying_whitelisted_values(self):
        current = {"name": "Vorher", "archived": False, "private": "kept"}
        values = {
            "action": "update",
            "name": "Nachher",
            "description": "- 20m Z2",
            "duration_minutes": 20,
            "target": "POWER",
            "type": "",
            "sport": "Run",
            "private": "ignored",
        }
        original_current = copy.deepcopy(current)
        original_values = copy.deepcopy(values)

        archived = library.workout_library_update_candidate(current, "archive", values)
        restored = library.workout_library_update_candidate(archived, "restore", values)
        updated = library.workout_library_update_candidate(current, "update", values)

        self.assertEqual(archived, {**current, "archived": True})
        self.assertEqual(restored, {**current, "archived": False})
        self.assertEqual(
            updated,
            {
                **current,
                "name": "Nachher",
                "description": "- 20m Z2",
                "duration_minutes": 20,
                "target": "POWER",
                "type": "Run",
            },
        )
        self.assertIsNot(archived, current)
        self.assertIsNot(restored, archived)
        self.assertIsNot(updated, current)
        self.assertEqual(current, original_current)
        self.assertEqual(values, original_values)

    def test_unknown_action_keeps_error_contract(self):
        with self.assertRaises(AppError) as raised:
            library.workout_library_update_candidate({}, "delete", {})
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(
            raised.exception.message,
            "Unbekannte Aktion für die Bibliothekseinheit.",
        )

    def test_updated_entry_normalizes_identity_preserves_metadata_and_reconciles_content(
        self,
    ):
        current = {
            "name": "Alte Einheit",
            "type": "Cycling",
            "description": "- 30m Z2 Easy",
            "duration_minutes": 30,
            "moving_time": 1800,
            "target": "AUTO",
            "source": "coach",
            "rationale": "Dauerlauf",
            "plan_id": "plan-1",
            "plan_name": "Basis",
            "private_calendar_adjustment": {"reason": "fixture"},
            "workout_doc": {"derived": True},
            "icu_training_load": 42,
            "icu_intensity": 0.8,
        }
        row = {"external_id": "remote-7"}
        values = {
            "name": "Neue Einheit",
            "description": "- 35m Z2 Steady",
            "duration_minutes": 35,
            "private_calendar_adjustment": {"reason": "ignored"},
        }
        original = copy.deepcopy((current, row, values))

        updated = library.updated_workout_library_entry(
            current, row, LOCAL_ID.upper(), "update", values
        )

        self.assertEqual(updated["id"], LOCAL_ID)
        self.assertEqual(updated["external_id"], "remote-7")
        self.assertEqual(updated["sync_status"], "local")
        self.assertEqual(updated["type"], "Ride")
        self.assertEqual(updated["name"], "Neue Einheit")
        self.assertEqual(updated["duration_minutes"], 35)
        self.assertEqual(updated["moving_time"], 2100)
        self.assertEqual(updated["source"], "coach")
        self.assertEqual(updated["rationale"], "Dauerlauf")
        self.assertEqual(updated["plan_id"], "plan-1")
        self.assertEqual(updated["plan_name"], "Basis")
        self.assertEqual(updated["private_calendar_adjustment"], {"reason": "fixture"})
        for key in ("workout_doc", "icu_training_load", "icu_intensity"):
            self.assertNotIn(key, updated)
        self.assertEqual((current, row, values), original)

    def test_derived_fields_are_retained_when_only_name_changes(self):
        current = {
            "name": "Old",
            "type": "Ride",
            "description": "- 20m Z2 Easy",
            "duration_minutes": 20,
            "workout_doc": {"derived": True},
            "icu_training_load": 12,
            "icu_intensity": 0.7,
        }

        updated = library.updated_workout_library_entry(
            current, {}, LOCAL_ID, "update", {"name": "New"}
        )

        self.assertEqual(updated["workout_doc"], {"derived": True})
        self.assertEqual(updated["icu_training_load"], 12)
        self.assertEqual(updated["icu_intensity"], 0.7)

    def test_moving_time_uses_validated_description_seconds_or_minutes(self):
        seconds_from_description = library.updated_workout_library_entry(
            {"type": "Ride", "name": "Ride"},
            {},
            LOCAL_ID,
            "update",
            {"description": "- 12m Z2 Easy"},
        )
        minutes_from_duration = library.updated_workout_library_entry(
            {"type": "Strength", "name": "Strength", "moving_time": 600},
            {},
            LOCAL_ID,
            "update",
            {"duration_minutes": "15,5"},
        )

        self.assertEqual(seconds_from_description["moving_time"], 720)
        self.assertNotIn("duration_minutes", seconds_from_description)
        self.assertEqual(minutes_from_duration["duration_minutes"], "15,5")
        self.assertEqual(minutes_from_duration["moving_time"], 930)

    def test_invalid_duration_does_not_replace_existing_moving_time(self):
        updated = library.updated_workout_library_entry(
            {
                "type": "Strength",
                "name": "Strength",
                "duration_minutes": 10,
                "moving_time": 600,
            },
            {},
            LOCAL_ID,
            "update",
            {"duration_minutes": "unknown"},
        )
        self.assertEqual(updated["duration_minutes"], "unknown")
        self.assertEqual(updated["moving_time"], 600)

    def test_invalid_workout_description_preserves_validation_error(self):
        with self.assertRaises(AppError) as raised:
            library.updated_workout_library_entry(
                {"type": "Ride", "name": "Ride"},
                {},
                LOCAL_ID,
                "update",
                {"description": "- 20m Z2 with 10m Z1"},
            )
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(
            raised.exception.message,
            "Workout-Text in Zeile 1 ist mehrdeutig: Ein Trainingsschritt darf nur eine Distanz oder Dauer enthalten; zusammengesetzte Zeiten wie '- 1h30m Z2' sind erlaubt. Optionale Gesamtstrecken als eigenen Absatz ohne '- ' schreiben.",
        )

    def test_archive_restore_normalize_and_preserve_metadata_without_mutating(self):
        current = {
            "type": "Run",
            "name": "Lauf",
            "source": "coach",
            "rationale": "locker",
            "private_calendar_adjustment": {"reason": "fixture"},
            "archived": False,
        }
        before = copy.deepcopy(current)

        archived = library.updated_workout_library_entry(
            current, {"external_id": "remote-9"}, LOCAL_ID, "archive", {}
        )
        restored = library.updated_workout_library_entry(
            archived, {"external_id": "remote-9"}, LOCAL_ID, "restore", {}
        )

        self.assertTrue(archived["archived"])
        self.assertFalse(restored["archived"])
        self.assertEqual(archived["external_id"], "remote-9")
        self.assertEqual(archived["sync_status"], "local")
        self.assertEqual(archived["source"], "coach")
        self.assertEqual(archived["rationale"], "locker")
        self.assertEqual(current, before)


if __name__ == "__main__":
    unittest.main()
