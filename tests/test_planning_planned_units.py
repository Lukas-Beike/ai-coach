"""Regression tests for pure planned-unit projections."""

import copy
import hashlib
import json
import unittest
from datetime import date

from backend.errors import INVALID_PLANNING_ID_ERROR, AppError
from backend.planning import library
from backend.planning.planned_units import (
    normalize_planned_unit,
    normalized_planned_workout_update,
    plan_push_payload_hash,
    planned_unit_payload_hash,
    planned_workout_update_candidate,
    planned_workout_update_request,
    prepare_planned_workout_date,
)
from backend.planning.repository import parse_payload

LOCAL_ID = "e8267245-0d20-456f-9c9b-b4bf3fc3c233"
TODAY = date(2026, 9, 20)


_RIDE = {
    "date": "2026-09-22",
    "starts_at_local": "2026-09-22T07:30:00+02:00",
    "sport": "Ride",
    "name": "Before",
    "description": "- 40m Z1",
    "duration_minutes": 40,
    "target": "AUTO",
    "source": "coach",
    "plan_id": "plan-1",
    "plan_name": "Base",
    "rationale": "Keep easy",
    "remote_event_id": "remote-1",
    "private_calendar_adjustment": {"adjusted_duration_minutes": 40},
    "workout_doc": {"old": True},
    "planned_load": 9,
}
_LIFT = {
    "date": "2026-09-22",
    "sport": "WeightTraining",
    "name": "Lift",
    "description": "Strength session",
    "duration_minutes": 35,
    "planned_duration_s": 2100,
}
_TEMPLATE = {
    "name": "Alte Einheit",
    "type": "Cycling",
    "description": "- 30m Z2 Easy",
    "duration_minutes": 30,
    "planned_duration_s": 1800,
    "target": "AUTO",
    "source": "coach",
    "rationale": "Dauerlauf",
    "plan_id": "plan-1",
    "plan_name": "Basis",
    "private_calendar_adjustment": {"reason": "fixture"},
    "workout_doc": {"derived": True},
    "planned_load": 42,
}
_ZONE_TEXT = "- 5m Zone 2 HR\n- 25m Z2 Easy"
# (kind, current, action, values) -> (stored text, payload hash, push hash) prefixes,
# recorded on the code before #2107 merged the two update pipelines. Only the
# planned path canonicalises zones, so the library rejects the same text.
_UPDATE_GOLDEN = [
    (
        (
            "planned",
            _RIDE,
            "update",
            {"description": "- 5m Zone 2 HR\n- 35m Z1", "duration_minutes": "40"},
        ),
        ("f98d3558673643e4", "e88ec814a67a4c31", "4d67cc082cba45ef"),
    ),
    (
        ("planned", _RIDE, "update", {"name": "Renamed"}),
        ("4b6520149cfd791a", "60f7405582458d73", "7b5979822848af05"),
    ),
    (
        (
            "planned",
            _RIDE,
            "update",
            {"sport": "Run", "description": "- 30m Z2", "duration_minutes": 30},
        ),
        ("2b979684fb282964", "d2ba7e29acfbb366", "98b60a9168f84b94"),
    ),
    (
        ("planned", _LIFT, "update", {"duration_minutes": "40"}),
        ("036821cf4584728e", "cf4f34e2aba784f8", "c17d206ac4d8e88f"),
    ),
    (
        ("planned", _RIDE, "archive", {}),
        ("1b522fdd33dafba4", "58581589690bbc62", "9011571ee73a79bb"),
    ),
    (
        ("planned", {**_LIFT, "local_deleted": True, "archived": True}, "restore", {}),
        ("9f6cf92243910bee", "7c06aa624c24845c", "9cebf4b0325372cf"),
    ),
    (
        (
            "library",
            _TEMPLATE,
            "update",
            {"name": "Neu", "description": "- 35m Z2 Steady", "duration_minutes": 35},
        ),
        ("4124287d901ed9df", "e6c5994cb2b48796", "3463a9b4ef9699e3"),
    ),
    (
        ("library", _TEMPLATE, "update", {"name": "Only name"}),
        ("03278e6686e4a618", "4df7039e42f3af65", "61ee25c6f553e048"),
    ),
    (("library", _TEMPLATE, "update", {"description": _ZONE_TEXT}), 400),
    (
        (
            "library",
            {"type": "Strength", "name": "Strength", "planned_duration_s": 600},
            "update",
            {"duration_minutes": "15,5"},
        ),
        ("91b1ebc2a9b6e22c", "ff1fb20989234c15", "de2a6e26d2de9dd2"),
    ),
    (
        ("library", _TEMPLATE, "archive", {}),
        ("730c0aec98c7077e", "38bf4ebeb2429160", "448d21e5f807056f"),
    ),
    (
        ("library", {**_TEMPLATE, "archived": True}, "restore", {}),
        ("585411ff3a9c661a", "79bb07335585ea79", "99fec198351b7f77"),
    ),
]


def _stored_update(kind, current, action, values):
    row = {"external_id": "ext"}
    if kind == "planned":
        candidate = planned_workout_update_candidate(current, action, values)
        payload = normalized_planned_workout_update(
            candidate, current, row, LOCAL_ID, action, values
        )
    else:
        payload = library.updated_workout_library_entry(
            current, row, LOCAL_ID, action, values
        )
    text = json.dumps(payload, ensure_ascii=False)
    return (
        hashlib.sha256(text.encode()).hexdigest()[:16],
        planned_unit_payload_hash(payload)[:16],
        plan_push_payload_hash(text)[:16],
    )


class PlannedUnitPayloadHashTests(unittest.TestCase):
    def test_parse_payload_returns_only_readable_objects(self):
        for raw, expected in (
            (
                '{"date": "2026-09-22", "name": "Ride"}',
                {"date": "2026-09-22", "name": "Ride"},
            ),
            ("", {}),
            (None, {}),
            ("not json", None),
            ("[1, 2]", None),
            ('"text"', None),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(parse_payload(raw), expected)

    def test_hash_is_stable_and_ignores_only_projection_state_fields(self):
        payload = {
            "name": "Änderung",
            "id": "first",
            "sync_status": "local",
            "sync_conflict": {"type": "remote_changed"},
            "origin": "coach",
            "local_marked": True,
        }
        expected = hashlib.sha256('{"name":"Änderung"}'.encode()).hexdigest()
        self.assertEqual(planned_unit_payload_hash(payload), expected)
        self.assertEqual(
            planned_unit_payload_hash({"b": 2, "a": 1}),
            planned_unit_payload_hash({"a": 1, "b": 2}),
        )
        self.assertNotEqual(
            planned_unit_payload_hash({"name": "same", "source": "a"}),
            planned_unit_payload_hash({"name": "same", "source": "b"}),
        )

    def test_non_object_hashes_as_empty_object(self):
        self.assertEqual(planned_unit_payload_hash(None), planned_unit_payload_hash({}))


class NormalizePlannedUnitTests(unittest.TestCase):
    def test_normalizes_identity_sport_date_metadata_and_duration_without_mutation(
        self,
    ):
        workout = {
            "sport": "cycling",
            "date": "2026-09-21Tnot-a-date",
            "starts_at_local": "2026-09-21T07:15:00+02:00" + "x" * 50,
            "duration_minutes": "45",
            "name": "Easy ride",
            "origin": "o" * 50,
            "source": "s" * 50,
            "status": "x" * 90,
            "remote_event_id": "r" * 130,
            "remote_event_external_id": "e" * 210,
            "sync_conflict": {"type": "remote_changed"},
            "ignored": "not projected",
        }
        before = copy.deepcopy(workout)

        result = normalize_planned_unit(
            workout,
            local_id=LOCAL_ID,
            external_id="intervals-17",
            sync_status="synced",
        )

        self.assertEqual(workout, before)
        self.assertEqual(result["id"], LOCAL_ID)
        self.assertEqual(result["external_id"], "intervals-17")
        self.assertEqual(result["sync_status"], "synced")
        self.assertNotIn("type", result)
        self.assertEqual((result["sport"], result["environment"]), ("ride", "unknown"))
        self.assertEqual(result["date"], "2026-09-21")
        self.assertEqual(result["starts_at_local"], workout["starts_at_local"][:40])
        self.assertEqual(result["duration_minutes"], "45")
        self.assertEqual(result["planned_duration_s"], 2700)
        self.assertEqual(result["origin"], "o" * 40)
        self.assertEqual(result["source"], "s" * 40)
        self.assertEqual(result["status"], "x" * 80)
        self.assertEqual(result["remote_event_id"], "r" * 120)
        self.assertEqual(result["remote_event_external_id"], "e" * 200)
        self.assertEqual(result["sync_conflict"], workout["sync_conflict"])
        self.assertNotIn("ignored", result)

    def test_requires_a_nonempty_string_sport(self):
        for workout in ({}, {"sport": " "}, {"sport": 7}, None):
            with self.subTest(workout=workout):
                with self.assertRaises(AppError) as raised:
                    normalize_planned_unit(workout)
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(
                    raised.exception.message,
                    "Eine geplante Einheit benötigt ihre Sportart.",
                )
                self.assertEqual(raised.exception.reason, "invalid_workout")

    def test_library_validation_rejects_invalid_local_uuid(self):
        with self.assertRaises(AppError) as raised:
            normalize_planned_unit({"sport": "Run"}, local_id="not-a-uuid")
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(
            raised.exception.message,
            "Bibliothekseinheit ohne gültige lokale UUID.",
        )


class PlannedWorkoutUpdateTests(unittest.TestCase):
    def test_request_normalizes_uuid_and_action_without_mutating_values(self):
        values = {"action": "  UPDATE  ", "name": "New"}
        before = copy.deepcopy(values)
        self.assertEqual(
            planned_workout_update_request(LOCAL_ID.upper(), values),
            (LOCAL_ID, values, "update"),
        )
        self.assertEqual(values, before)

    def test_request_rejects_invalid_uuid_and_non_object_values(self):
        with self.assertRaises(AppError) as bad_id:
            planned_workout_update_request("invalid", {})
        self.assertEqual(bad_id.exception.status, 400)
        self.assertEqual(bad_id.exception.message, INVALID_PLANNING_ID_ERROR)
        with self.assertRaises(AppError) as bad_values:
            planned_workout_update_request(LOCAL_ID, [])
        self.assertEqual(bad_values.exception.status, 400)
        self.assertEqual(
            bad_values.exception.message,
            "Die lokale Planung muss als Objekt gesendet werden.",
        )

    def test_candidate_supports_update_archive_and_restore(self):
        current = {
            "date": "2026-09-22",
            "name": "Before",
            "sport": "Ride",
            "target": "AUTO",
            "archived": True,
            "local_deleted": True,
            "untouched": {"nested": True},
        }
        before = copy.deepcopy(current)
        update_values = {
            "date": "2026-09-23",
            "name": "After",
            "description": "- 30m Z2",
            "duration_minutes": 30,
            "target": "POWER",
            "sport": "Run",
            "ignored": "value",
        }

        updated = planned_workout_update_candidate(current, "update", update_values)
        archived = planned_workout_update_candidate(current, "archive", {})
        restored = planned_workout_update_candidate(current, "restore", {})

        self.assertEqual(current, before)
        self.assertEqual(updated["date"], "2026-09-23")
        self.assertEqual(updated["name"], "After")
        self.assertEqual(updated["sport"], "Run")
        self.assertNotIn("ignored", updated)
        self.assertTrue(archived["archived"])
        self.assertTrue(restored["archived"] is False)
        self.assertFalse(restored["local_deleted"])
        self.assertEqual(restored["untouched"], current["untouched"])

    def test_candidate_moves_existing_start_time_and_accepts_a_new_valid_time(self):
        current = {
            "date": "2026-09-22",
            "starts_at_local": "2026-09-22T07:30:00+02:00",
        }
        moved = planned_workout_update_candidate(
            current, "update", {"date": "2026-09-23"}
        )
        self.assertTrue(prepare_planned_workout_date(moved, current, today=TODAY))
        retimed = planned_workout_update_candidate(
            current,
            "update",
            {
                "date": "2026-09-23",
                "starts_at_local": "2026-09-23T08:15:00+02:00",
            },
        )
        self.assertTrue(prepare_planned_workout_date(retimed, current, today=TODAY))

        self.assertEqual(moved["starts_at_local"], "2026-09-23T07:30:00+02:00")
        self.assertEqual(retimed["starts_at_local"], "2026-09-23T08:15:00+02:00")
        with self.assertRaises(AppError) as raised:
            planned_workout_update_candidate(
                current,
                "update",
                {
                    "date": "2026-09-23",
                    "starts_at_local": "2026-09-22T08:15:00+02:00",
                },
            )
        self.assertEqual(raised.exception.reason, "invalid_workout_start_date")

    def test_candidate_rejects_unknown_action(self):
        with self.assertRaises(AppError) as raised:
            planned_workout_update_candidate({}, "delete", {})
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(
            raised.exception.message, "Unbekannte Aktion für lokale Planung."
        )

    def test_normalized_update_canonicalizes_description_and_derives_moving_time(self):
        current = {
            "date": "2026-09-22",
            "starts_at_local": "2026-09-22T07:30:00+02:00",
            "sport": "Ride",
            "name": "Before",
            "description": "- 40m Z1",
            "duration_minutes": 40,
            "target": "AUTO",
            "source": "coach",
            "plan_id": "plan-1",
            "plan_name": "Base",
            "rationale": "Keep easy",
            "remote_event_id": "remote-1",
            "remote_event_external_id": "ext-1",
            "private_calendar_adjustment": {"adjusted_duration_minutes": 40},
            "workout_doc": {"old": True},
            "planned_load": 9,
            "planned_intensity": 1.2,
        }
        values = {
            "action": "update",
            "description": "- 5m Zone 2 HR\n- 35m Z1",
            "duration_minutes": "40",
            "target": "AUTO",
        }
        candidate = planned_workout_update_candidate(current, "update", values)
        row = {"external_id": "row-external"}
        before = copy.deepcopy((candidate, current, row, values))

        updated = normalized_planned_workout_update(
            candidate, current, row, LOCAL_ID, "update", values
        )

        self.assertEqual((candidate, current, row, values), before)
        self.assertEqual(updated["description"], "- 5m Z2 HR\n- 35m Z1")
        self.assertEqual(updated["planned_duration_s"], 2400)
        self.assertEqual(updated["id"], LOCAL_ID)
        self.assertEqual(updated["external_id"], "row-external")
        self.assertEqual(updated["sync_status"], "local")
        self.assertEqual(updated["source"], "coach")
        self.assertEqual(updated["starts_at_local"], current["starts_at_local"])
        for key in (
            "plan_id",
            "plan_name",
            "rationale",
            "remote_event_id",
            "remote_event_external_id",
            "private_calendar_adjustment",
        ):
            self.assertEqual(updated[key], current[key])
        for key in ("workout_doc", "planned_load", "planned_intensity"):
            self.assertNotIn(key, updated)

    def test_normalized_update_validates_endurance_content_and_handles_non_endurance_duration(
        self,
    ):
        current = {
            "date": "2026-09-22",
            "sport": "Run",
            "name": "Run",
            "description": "- 30m Z1",
            "duration_minutes": 30,
        }
        bad = planned_workout_update_candidate(
            current,
            "update",
            {"description": "Easy running", "duration_minutes": 30},
        )
        with self.assertRaises(AppError):
            normalized_planned_workout_update(
                bad,
                current,
                {},
                LOCAL_ID,
                "update",
                {"description": "Easy running", "duration_minutes": 30},
            )

        strength = {
            "date": "2026-09-22",
            "sport": "WeightTraining",
            "name": "Lift",
            "description": "Strength session",
            "duration_minutes": 35,
            "planned_duration_s": 2100,
        }
        candidate = planned_workout_update_candidate(
            strength, "update", {"duration_minutes": "40"}
        )
        result = normalized_planned_workout_update(
            candidate,
            strength,
            {},
            LOCAL_ID,
            "update",
            {"duration_minutes": "40"},
        )
        self.assertEqual(result["planned_duration_s"], 2400)
        with self.assertRaises(AppError) as raised:
            planned_workout_update_candidate(
                strength, "update", {"duration_minutes": "35,5"}
            )
        self.assertEqual(raised.exception.status, 400)

    def test_update_pipelines_store_the_golden_payloads_and_hashes(self):
        for case, expected in _UPDATE_GOLDEN:
            with self.subTest(kind=case[0], action=case[2], values=case[3]):
                if isinstance(expected, int):
                    with self.assertRaises(AppError) as raised:
                        _stored_update(*case)
                    self.assertEqual(raised.exception.status, expected)
                else:
                    self.assertEqual(_stored_update(*case), expected)

    def test_restore_candidate_clears_local_deleted_but_current_metadata_is_preserved(
        self,
    ):
        current = {
            "date": "2026-09-22",
            "sport": "Run",
            "name": "Run",
            "local_deleted": True,
        }
        candidate = planned_workout_update_candidate(current, "restore", {})
        self.assertFalse(candidate["local_deleted"])
        result = normalized_planned_workout_update(
            candidate, current, {}, LOCAL_ID, "restore", {"action": "restore"}
        )
        self.assertTrue(result["archived"] is False)
        self.assertTrue(result["local_deleted"])


if __name__ == "__main__":
    unittest.main()
