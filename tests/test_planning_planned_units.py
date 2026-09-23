"""Regression tests for pure planned-unit projections."""

import copy
import hashlib
import json
import unittest
from datetime import date

from backend.errors import INVALID_PLANNING_ID_ERROR, AppError
from backend.planning.planned_units import (
    normalize_planned_unit,
    normalized_planned_workout_update,
    planned_unit_payload_hash,
    planned_workout_update_candidate,
    planned_workout_update_request,
    remote_planned_unit_existing_state,
    remote_planned_unit_payload,
)

LOCAL_ID = "e8267245-0d20-456f-9c9b-b4bf3fc3c233"
TODAY = date(2026, 9, 20)


class PlannedUnitPayloadHashTests(unittest.TestCase):
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
            "start_date_local": "2026-09-21T07:15:00+02:00" + "x" * 50,
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
        self.assertEqual(result["type"], "Ride")
        self.assertEqual(result["sport"], "Ride")
        self.assertEqual(result["date"], "2026-09-21")
        self.assertEqual(result["start_date_local"], workout["start_date_local"][:40])
        self.assertEqual(result["duration_minutes"], "45")
        self.assertEqual(result["moving_time"], 2700)
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
                    "Eine geplante Einheit benoetigt ihre Sportart.",
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
            "start_date_local": "2026-09-22T07:30:00+02:00",
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
            "icu_training_load": 9,
            "icu_intensity": 1.2,
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
        self.assertEqual(updated["moving_time"], 2400)
        self.assertEqual(updated["id"], LOCAL_ID)
        self.assertEqual(updated["external_id"], "row-external")
        self.assertEqual(updated["sync_status"], "local")
        self.assertEqual(updated["source"], "coach")
        self.assertEqual(updated["start_date_local"], current["start_date_local"])
        for key in (
            "plan_id",
            "plan_name",
            "rationale",
            "remote_event_id",
            "remote_event_external_id",
            "private_calendar_adjustment",
        ):
            self.assertEqual(updated[key], current[key])
        for key in ("workout_doc", "icu_training_load", "icu_intensity"):
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
            "moving_time": 2100,
        }
        candidate = planned_workout_update_candidate(
            strength, "update", {"duration_minutes": "35,5"}
        )
        result = normalized_planned_workout_update(
            candidate,
            strength,
            {},
            LOCAL_ID,
            "update",
            {"duration_minutes": "35,5"},
        )
        self.assertEqual(result["moving_time"], 2130)

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


class RemotePlannedUnitPayloadTests(unittest.TestCase):
    def test_remote_category_id_date_duration_and_identity_projection(self):
        event = {
            "id": " event-17 ",
            "external_id": " external-17 ",
            "category": "workout",
            "start_date_local": "2026-09-21T06:45:00+02:00",
            "type": "Run",
            "name": "Easy run",
            "description": "- 20m Z1",
            "moving_time": 1200,
            "target": "PACE",
            "pairedEventId": "paired-9",
        }
        before = copy.deepcopy(event)

        result = remote_planned_unit_payload(event, today=TODAY)

        self.assertIsNotNone(result)
        payload, remote_id, identity = result
        self.assertEqual(event, before)
        self.assertEqual(remote_id, "event-17")
        self.assertEqual(identity, "external-17")
        self.assertEqual(payload["external_id"], identity)
        self.assertEqual(payload["date"], "2026-09-21")
        self.assertEqual(payload["start_date_local"], event["start_date_local"])
        self.assertEqual(payload["sport"], "Run")
        self.assertEqual(payload["type"], "Run")
        self.assertEqual(payload["duration_minutes"], 20)
        self.assertEqual(payload["moving_time"], 1200)
        self.assertEqual(payload["paired_event_id"], "paired-9")
        self.assertEqual(payload["source"], "intervals")
        self.assertEqual(payload["origin"], "intervals")
        self.assertEqual(payload["sync_status"], "synced")

    def test_remote_defaults_and_fallback_identity_are_preserved(self):
        payload, remote_id, identity = remote_planned_unit_payload(
            {"id": "event-18", "date": "2026-09-20", "moving_time": "bad"},
            today=TODAY,
        )
        self.assertEqual(remote_id, "event-18")
        self.assertEqual(identity, "intervals-event-event-18")
        self.assertEqual(payload["date"], "2026-09-20")
        self.assertEqual(payload["start_date_local"], "2026-09-20T00:00:00")
        self.assertEqual(payload["sport"], "Ride")
        self.assertEqual(payload["name"], "Intervals.icu-Einheit")
        self.assertEqual(payload["duration_minutes"], 30)
        self.assertEqual(payload["remote_event_external_id"], "")

    def test_remote_duration_has_five_minute_floor(self):
        payload, _, _ = remote_planned_unit_payload(
            {"id": "event-short", "date": "2026-09-21", "moving_time": 30},
            today=TODAY,
        )
        self.assertEqual(payload["duration_minutes"], 5)

    def test_remote_import_filters_category_id_invalid_date_and_past_date_using_today(
        self,
    ):
        self.assertIsNone(
            remote_planned_unit_payload(
                {"id": "event", "category": "RIDE", "date": "2026-09-21"},
                today=TODAY,
            )
        )
        self.assertIsNone(
            remote_planned_unit_payload(
                {"id": "event", "date": "not-a-date"}, today=TODAY
            )
        )
        self.assertIsNone(
            remote_planned_unit_payload({"date": "2026-09-21"}, today=TODAY)
        )
        self.assertIsNone(
            remote_planned_unit_payload(
                {"id": "old", "date": "2026-09-19"}, today=TODAY
            )
        )

    def test_today_is_required_and_does_not_use_a_global_clock(self):
        with self.assertRaises(TypeError):
            remote_planned_unit_payload({"id": "event", "date": "2026-09-21"})
        self.assertIsNone(
            remote_planned_unit_payload(
                {"id": "event", "date": "2026-09-21"},
                today=date(2026, 9, 22),
            )
        )
        self.assertIsNotNone(
            remote_planned_unit_payload(
                {"id": "event", "date": "2026-09-21"},
                today=date(2026, 9, 20),
            )
        )


class RemotePlannedUnitExistingStateTests(unittest.TestCase):
    def test_dirty_conflict_preserve_unchanged_and_update_matrix(self):
        incoming_hash = planned_unit_payload_hash({"name": "remote"})
        changed_hash = planned_unit_payload_hash({"name": "different"})
        cases = (
            (
                {
                    "sync_dirty": 1,
                    "sync_state": "synced",
                    "baseline_hash": changed_hash,
                },
                "conflict",
            ),
            (
                {
                    "sync_dirty": 1,
                    "sync_state": "synced",
                    "baseline_hash": incoming_hash,
                },
                "preserve",
            ),
            (
                {
                    "sync_dirty": 0,
                    "sync_state": "conflict",
                    "baseline_hash": incoming_hash,
                },
                "preserve",
            ),
            (
                {
                    "sync_dirty": 0,
                    "sync_state": "synced",
                    "baseline_hash": incoming_hash,
                },
                "unchanged",
            ),
            (
                {
                    "sync_dirty": 0,
                    "sync_state": "synced",
                    "baseline_hash": changed_hash,
                },
                "update",
            ),
            (
                {
                    "sync_dirty": 0,
                    "sync_state": "sync_error",
                    "baseline_hash": changed_hash,
                },
                "conflict",
            ),
        )
        for row_fields, expected_state in cases:
            with self.subTest(row=row_fields):
                current_row = {
                    "payload": json.dumps({"name": "local"}),
                    **row_fields,
                }
                current, state = remote_planned_unit_existing_state(
                    current_row, incoming_hash
                )
                self.assertEqual(state, expected_state)
                self.assertEqual(current, {"name": "local"})

    def test_existing_state_falls_back_to_current_hash_and_handles_corrupt_json(self):
        payload = {"name": "remote"}
        incoming_hash = planned_unit_payload_hash(payload)
        current, state = remote_planned_unit_existing_state(
            {"payload": json.dumps(payload), "sync_state": "synced"}, incoming_hash
        )
        self.assertEqual((current, state), (payload, "unchanged"))

        current, state = remote_planned_unit_existing_state(
            {"payload": "invalid json", "sync_state": "synced"}, incoming_hash
        )
        self.assertEqual(current, {})
        self.assertEqual(state, "update")

    def test_existing_state_never_mutates_row_payload(self):
        row = {
            "payload": json.dumps({"name": "local", "nested": {"keep": True}}),
            "sync_dirty": 0,
            "sync_state": "synced",
        }
        before = copy.deepcopy(row)
        current, _ = remote_planned_unit_existing_state(row, "new-hash")
        current["nested"]["keep"] = False
        self.assertEqual(row, before)


if __name__ == "__main__":
    unittest.main()
