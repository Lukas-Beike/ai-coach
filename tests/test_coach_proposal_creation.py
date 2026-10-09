"""Tests for session-owned Coach action proposal creation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.proposal_models import (
    COACH_ACTION_TTL_SECONDS,
    coach_action_hash,
)
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition.food_database import FoodDatabaseService


class CoachProposalCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "coach-proposals.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.sync_state_repository = Mock()

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def _service(self, **overrides: object) -> CoachProposalCreationService:
        options = {
            "now": lambda: 100.0,
            "utc_now": lambda: "2026-09-23T10:11:12+00:00",
            "uuid_factory": lambda: UUID("abc12345-6789-4abc-8def-0123456789ab"),
        }
        options.update(overrides)
        return CoachProposalCreationService(
            self.database_manager,
            self.sync_state_repository,
            **options,
        )

    def _undo(self) -> dict[str, object]:
        return {
            "action_type": "undo_change",
            "target_system": "local",
            "object_ids": ["change-1"],
            "diff": [{"type": "restore", "label": "Änderung"}],
            "payload": {"change_id": "change-1", "secret": "private"},
        }

    @staticmethod
    def _duplicate_snapshot(synced_at: str) -> dict[str, object]:
        return {
            "synced_at": synced_at,
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "wahoo-1",
                        "source": "Wahoo",
                        "type": "Ride",
                        "start_date_local": "2026-08-29T07:00:00",
                        "moving_time": 7200,
                        "distance": 60000,
                    },
                    {
                        "activityId": "garmin-1",
                        "source": "Garmin",
                        "type": "Ride",
                        "start_date_local": "2026-08-29T07:05:00",
                        "moving_time": 7160,
                        "distance": 59800,
                    },
                ]
            },
        }

    @staticmethod
    def _delete_duplicate(synced_at: str) -> dict[str, object]:
        return {
            "action_type": "delete_duplicate_intervals_activity",
            "target_system": "intervals",
            "object_ids": {
                "keep_activity_id": "wahoo-1",
                "delete_activity_id": "garmin-1",
            },
            "diff": [{"type": "delete", "id": "garmin-1", "name": "Garmin"}],
            "payload": {
                "canonical_id": "wahoo-1",
                "duplicate_id": "garmin-1",
                "snapshot_synced_at": synced_at,
            },
        }

    def _rows(self) -> list[dict[str, object]]:
        with self.database_manager.reader() as db:
            return db.execute("SELECT * FROM coach_action_proposals").fetchall()

    def test_undo_creation_persists_session_ttl_hash_and_safe_view(self) -> None:
        payload = self._undo()["payload"]
        result = self._service().create(self._undo(), "session-csrf-hash")

        self.assertEqual(COACH_ACTION_TTL_SECONDS, 600)
        self.assertEqual(result["status"], "preview")
        self.assertEqual(
            result["proposed_action"],
            {
                "id": "abc12345-6789-4abc-8def-0123456789ab",
                "action_type": "undo_change",
                "target_system": "local",
                "object_ids": ["change-1"],
                "diff": [{"type": "restore", "label": "Änderung"}],
                "payload_hash": coach_action_hash(payload),
                "expires_at": 100 + COACH_ACTION_TTL_SECONDS,
                "status": "preview",
            },
        )
        self.assertNotIn("payload", result["proposed_action"])
        row = self._rows()[0]
        self.assertEqual(row["session_csrf_hash"], "session-csrf-hash")
        expected_hash = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(row["payload_hash"], expected_hash)
        self.assertEqual(row["payload"], '{"change_id":"change-1","secret":"private"}')
        self.assertEqual(row["diff"], '[{"type":"restore","label":"Änderung"}]')
        self.assertEqual(row["created_at"], "2026-09-23T10:11:12+00:00")
        self.assertNotIn("private", repr(result))
        self.sync_state_repository.latest_snapshot.assert_not_called()

    def test_local_nutrition_write_requires_bound_request_and_shows_safe_values(self) -> None:
        service = self._service()
        intent = {
            "operation": "save_nutrition_template", "target_system": "local",
            "authorization_scope": ["local_nutrition"],
            "request": {"source_message_ids": [7]},
        }
        args = {"payload": {"name": "Recovery bowl", "description": "Oats and yogurt", "kcal": 420}}
        result = service.create_local_write(
            "save_nutrition_template", args, intent, conversation_id="conversation-1",
            client_turn_id="turn-1", session_csrf_hash="session-1",
        )
        action = result["proposed_action"]
        self.assertEqual(action["action_type"], "local_coach_write")
        self.assertEqual(action["diff"][0]["name"], "Recovery bowl")
        self.assertEqual(action["diff"][0]["kcal"], "420")
        self.assertNotIn("payload", action)
        with self.assertRaises(AppError):
            service.create_local_write(
                "save_nutrition_template", args,
                {**intent, "request": {"source_message_ids": []}},
                conversation_id="conversation-1", client_turn_id="turn-1",
                session_csrf_hash="session-1",
            )
        self.assertEqual(len(self._rows()), 1)

    def test_local_nutrition_update_preview_shows_retained_macros(self) -> None:
        nutrition = Mock()
        nutrition.list_templates.return_value = [{
            "id": "template-1", "name": "Recovery bowl", "description": "Oats",
            "kcal": 420, "carbs_g": 64, "protein_g": 22, "fat_g": 8,
        }]
        nutrition._prepare_values.side_effect = lambda values: {
            **values, "nutrition_basis": {"kind": "manual"}
        }
        intent = {
            "operation": "save_nutrition_template", "target_system": "local",
            "authorization_scope": ["local_nutrition"],
            "request": {"source_message_ids": [7]},
        }
        result = self._service(nutrition_service=lambda: nutrition).create_local_write(
            "save_nutrition_template",
            {"payload": {"id": "template-1", "name": "Recovery bowl", "description": "Oats with berries", "kcal": 450}},
            intent, conversation_id="conversation-1", client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )
        self.assertEqual(
            result["proposed_action"]["diff"][0],
            {"name": "Recovery bowl", "description": "Oats with berries", "kcal": "450", "carbs": "64", "protein": "22", "fat": "8"},
        )

    def test_template_update_preview_drops_stale_database_provenance(self) -> None:
        nutrition = Mock()
        nutrition.list_templates.return_value = [{
            "id": "template-1", "name": "Oats", "description": "Oats",
            "kcal": 174, "carbs_g": 30, "protein_g": 6, "fat_g": 3,
            "source": "coach", "nutrition_basis": {
                "kind": "database", "ingredients": [{
                    "source": "BLS", "name": "Oats", "amount": 50,
                    "unit": "g", "basis_unit": "g",
                }],
            },
        }]
        nutrition._prepare_values.side_effect = lambda values: {
            **values, "nutrition_basis": {"kind": "estimate"}
        }
        intent = {
            "operation": "save_nutrition_template", "target_system": "local",
            "authorization_scope": ["local_nutrition"],
            "request": {"source_message_ids": [7]},
        }
        result = self._service(nutrition_service=lambda: nutrition).create_local_write(
            "save_nutrition_template",
            {"payload": {
                "id": "template-1", "name": "Oats", "description": "Oats",
                "kcal": 200,
            }}, intent, conversation_id="conversation-1", client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )
        diff = result["proposed_action"]["diff"][0]
        self.assertEqual(diff["kcal"], "200")
        self.assertNotIn("source", diff)

    def test_database_preview_uses_server_values_and_freezes_the_calculation(self) -> None:
        nutrition = Mock()
        nutrition.food_database = FoodDatabaseService()
        args = {"payload": {"name": "Oats", "description": "50 g oats", "kcal": 999,
                            "food_ingredients": [{"food_id": "bls:C133000", "amount": 50, "unit": "g"}]}}
        intent = {"operation": "save_nutrition_template", "target_system": "local", "authorization_scope": ["local_nutrition"], "request": {"source_message_ids": [7]}}
        result = self._service(nutrition_service=lambda: nutrition).create_local_write(
            "save_nutrition_template", args, intent, conversation_id="conversation-1",
            client_turn_id="turn-1", session_csrf_hash="session-1",
        )
        diff = result["proposed_action"]["diff"][0]
        self.assertEqual(diff["kcal"], "174")
        self.assertIn("Max Rubner-Institut", diff["source"])
        self.assertIn("50 g (Basis 100 g)", diff["source"])
        stored = json.loads(self._rows()[0]["payload"])
        self.assertEqual(stored["arguments"]["_food_calculation"]["kcal"], 174)

    def test_composite_preview_freezes_complete_totals_and_provenance(self) -> None:
        nutrition = Mock()
        components = [{"kind": "estimate", "name": "Synthetic topping", "amount": 1,
                       "unit": "portion", "kcal": 25, "carbs_g": 4,
                       "protein_g": 1, "fat_g": 0.5}]
        calculation = {"kcal": 25, "carbs_g": 4, "protein_g": 1, "fat_g": 0.5,
                       "nutrition_basis": {"kind": "composite", "version": 1,
                           "components": [{"kind": "estimate", "name": "Synthetic topping",
                               "amount": 1, "unit": "portion", "kcal": 25,
                               "carbs_g": 4, "protein_g": 1, "fat_g": 0.5,
                               "nutrition_basis": {"kind": "estimate"}}]}}
        nutrition.calculate_components.return_value = calculation
        arguments = {"payload": {"name": "Synthetic bowl", "description": "Mixed recipe",
                                  "components": components}}
        intent = {"operation": "save_nutrition_template", "target_system": "local",
                  "authorization_scope": ["local_nutrition"], "request": {"source_message_ids": [7]}}
        result = self._service(nutrition_service=lambda: nutrition).create_local_write(
            "save_nutrition_template", arguments, intent,
            conversation_id="conversation-1", client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )
        self.assertEqual(result["proposed_action"]["diff"][0]["kcal"], "25")
        self.assertIn("estimate: Synthetic topping", result["proposed_action"]["diff"][0]["source"])
        stored = json.loads(self._rows()[0]["payload"])
        self.assertEqual(stored["arguments"]["_food_calculation"], calculation)
        nutrition.calculate_components.assert_called_once_with(components)

    def test_competition_remote_write_binds_dirty_rows_and_tombstones_to_approval(self) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competitions (id, name, event_date, sport, priority, distance, target, "
                "course_profile, notes, created_at, updated_at) "
                "VALUES ('race-1', 'Race', '2026-10-01', 'Run', 'A', '', '', '', '', 'now', 'now')"
            )
            db.execute(
                "INSERT INTO competition_sync_tombstones (id, intervals_event_id, external_id, created_at) "
                "VALUES ('deleted-1', 'remote-1', NULL, 'now')"
            )
        intent = {
            "operation": "sync_competitions",
            "intent": "remote_sync",
            "target_system": "intervals",
            "authorization_scope": ["local_competitions", "intervals_sync"],
            "request": {"remote_write": True, "source_message_ids": [7]},
        }

        result = self._service().create_remote_write(
            "sync_competitions",
            {"reason": "approved request"},
            intent,
            conversation_id="conversation-1",
            client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )

        payload = json.loads(self._rows()[0]["payload"])
        manifest = payload["arguments"]["_approval_manifest"]
        self.assertEqual(
            {(item["type"], item["id"]) for item in manifest},
            {("competition", "race-1"), ("tombstone", "deleted-1")},
        )
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest))
        self.assertEqual(
            result["proposed_action"]["diff"],
            [
                {"name": "Race", "date": "2026-10-01", "sport": "Run", "id": "race-1"},
                {"name": "Remote-Wettkampfeintrag löschen", "date": "Freigegebene Löschmarkierung", "id": "remote-1"},
            ],
        )

    def test_plan_approval_shows_each_concrete_workout(self) -> None:
        raw_payload = json.dumps(
            {"name": "Tempo ride", "date": "2026-10-02", "sport": "Ride"}
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) "
                "VALUES ('unit-1', 'unit-1', ?, 'now', 'now')",
                (raw_payload,),
            )
        intent = {
            "operation": "start_intervals_plan_sync", "intent": "remote_sync",
            "target_system": "intervals", "authorization_scope": ["intervals_sync"],
            "request": {"remote_write": True, "source_message_ids": [7], "sync_scope": "selected"},
        }
        result = self._service().create_remote_write(
            "start_intervals_plan_sync",
            {"entries": [{"library_workout_id": "unit-1", "expected_payload_hash": hashlib.sha256(raw_payload.encode()).hexdigest()}]},
            intent, conversation_id="conversation-1", client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )
        self.assertEqual(
            result["proposed_action"]["diff"],
            [{"name": "Tempo ride", "date": "2026-10-02", "sport": "Ride", "id": "unit-1"}],
        )

    def test_all_pending_plan_approval_freezes_and_displays_pending_entries(self) -> None:
        raw_payload = json.dumps(
            {"name": "Recovery run", "date": "2026-10-03", "sport": "Run"}
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) "
                "VALUES ('unit-2', 'unit-2', ?, 'now', 'now')",
                (raw_payload,),
            )
        intent = {
            "operation": "start_intervals_plan_sync", "intent": "remote_sync",
            "target_system": "intervals", "authorization_scope": ["intervals_sync"],
            "request": {"remote_write": True, "source_message_ids": [8], "sync_scope": "all_pending"},
            "_sync_all_pending": True,
        }
        result = self._service().create_remote_write(
            "start_intervals_plan_sync", {}, intent,
            conversation_id="conversation-1", client_turn_id="turn-2",
            session_csrf_hash="session-2",
        )
        payload = json.loads(self._rows()[0]["payload"])
        self.assertEqual(payload["arguments"]["entries"], [
            {"library_workout_id": "unit-2", "expected_payload_hash": hashlib.sha256(raw_payload.encode()).hexdigest()},
        ])
        self.assertEqual(result["proposed_action"]["diff"], [
            {"name": "Recovery run", "date": "2026-10-03", "sport": "Run", "id": "unit-2"},
        ])

    def test_nutrition_remote_write_freezes_dates_revisions_and_aggregates(self) -> None:
        nutrition = Mock()
        manifest = [{
            "date": "2026-09-24", "revision": 4, "total_kcal": 2200,
            "total_carbs_g": 250.0, "total_protein_g": 130.0, "total_fat_g": 65.0,
            "entry_count": 3, "sha256": "a" * 64,
        }]
        nutrition.approval_manifest.return_value = manifest
        intent = {
            "operation": "sync_nutrition", "intent": "remote_sync",
            "target_system": "intervals",
            "authorization_scope": ["local_nutrition", "intervals_sync"],
            "request": {"remote_write": True, "source_message_ids": [7]},
        }
        self._service(nutrition_service=lambda: nutrition).create_remote_write(
            "sync_nutrition", {"pending_limit": 3}, intent,
            conversation_id="conversation-1", client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )
        payload = json.loads(self._rows()[0]["payload"])
        self.assertEqual(payload["arguments"]["_approval_manifest"], manifest)
        self.assertEqual(payload["arguments"], {
            "pending_limit": 3, "_approval_manifest": manifest,
        })
        self.assertEqual(nutrition.approval_manifest.call_args.kwargs, {"pending_limit": 3})

    def test_distinct_session_keys_own_distinct_proposals(self) -> None:
        self._service().create(self._undo(), "session-a")
        other_id = UUID("def12345-6789-4abc-8def-0123456789ab")
        self._service(uuid_factory=lambda: other_id).create(self._undo(), "session-b")

        self.assertEqual(
            {row["session_csrf_hash"] for row in self._rows()}, {"session-a", "session-b"}
        )

    def test_duplicate_delete_validates_against_fresh_snapshot_before_persisting(self) -> None:
        current_time = "2026-08-29T10:00:00+00:00"
        self.sync_state_repository.latest_snapshot.return_value = self._duplicate_snapshot(
            current_time
        )
        result = self._service().create(self._delete_duplicate(current_time), "session")

        self.assertEqual(
            result["proposed_action"]["action_type"],
            "delete_duplicate_intervals_activity",
        )
        self.assertEqual(len(self._rows()), 1)
        self.sync_state_repository.latest_snapshot.assert_called_once_with()

    def test_stale_duplicate_snapshot_rejects_before_id_clock_or_insert(self) -> None:
        self.sync_state_repository.latest_snapshot.return_value = self._duplicate_snapshot(
            "2026-08-29T10:01:00+00:00"
        )
        uuid_factory = Mock(return_value=UUID("abc12345-6789-4abc-8def-0123456789ab"))
        now = Mock(return_value=100.0)
        utc_now = Mock(return_value="now")

        with self.assertRaises(AppError) as error:
            self._service(uuid_factory=uuid_factory, now=now, utc_now=utc_now).create(
                self._delete_duplicate("2026-08-29T10:00:00+00:00"), "session"
            )

        self.assertEqual(error.exception.status, 409)
        uuid_factory.assert_not_called()
        now.assert_not_called()
        utc_now.assert_not_called()
        self.assertEqual(self._rows(), [])

    def test_invalid_inputs_reject_before_snapshot_or_insert(self) -> None:
        invalid_values = [
            None,
            {},
            {**self._undo(), "diff": []},
            {**self._undo(), "target_system": "intervals"},
        ]
        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(AppError):
                self._service().create(values, "session")

        self.sync_state_repository.latest_snapshot.assert_not_called()
        self.assertEqual(self._rows(), [])

    def test_database_failure_rolls_back_insert(self) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER reject_proposal BEFORE INSERT ON coach_action_proposals "
                "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self._service().create(self._undo(), "session")

        self.assertEqual(self._rows(), [])


if __name__ == "__main__":
    unittest.main()
