"""End-to-end contracts for undoing all local changes of one Coach turn."""

from __future__ import annotations

import json
import unittest
import uuid
from unittest.mock import Mock

from server_test_support import ServerTestCase, server

from backend import change_history
from backend.coach.change_receipts import change_summary

_ROUTE = "/api/change-history/undo-turn"


class CoachTurnUndoTests(ServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        server.ATHLETE_DATA.profile().save({"name": "Ada", "weight_kg": "71"})

    def _coach_turn(self, *, track_library: bool = True) -> str:
        """Record a finished turn that changed the profile and the library."""
        turn_id = f"turn-{uuid.uuid4()}"
        with change_history.collect_changes() as profile_changes:
            server.ATHLETE_DATA.profile().save({"name": "Bea", "weight_kg": "72"})
        with change_history.collect_changes() as library_changes:
            server.PLANNING_DATA.workout_library().create_local_entry(
                {
                    "name": "Easy",
                    "sport": "Ride",
                    "duration_minutes": 30,
                    "description": "- 30m 60%",
                }
            )
        steps = [
            {
                "tool": "update_profile",
                "result": {"ok": True},
                "changes": profile_changes,
            },
            {
                "tool": "manage_training_templates",
                "result": {"ok": True},
                **({"changes": library_changes} if track_library else {}),
            },
        ]
        receipt = {"command_receipts": steps, "change_summary": change_summary(steps)}
        with server.database_manager().unit_of_work() as db:
            server.CHAT_REPOSITORY.add(
                db, "user", "Ändere Profil und Vorlage", client_turn_id=turn_id
            )
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, intent, target_system, "
                "status, receipt, created_at, updated_at) "
                "VALUES (?, ?, '{}', 'local', 'completed', ?, 'now', 'now')",
                (str(uuid.uuid4()), turn_id, json.dumps(receipt)),
            )
            server.CHAT_REPOSITORY.add(
                db, "assistant", "Erledigt.", client_turn_id=turn_id
            )
        return turn_id

    def _undo(self, turn_id: str) -> dict:
        handler = Mock()
        handler.read_json.return_value = {"client_turn_id": turn_id}
        handled = server.HTTP_API.history_undo_post_routes.handle(
            handler, _ROUTE, {"csrf_hash": "session-csrf-hash"}
        )
        self.assertTrue(handled)
        status, payload = handler.send_json.call_args.args
        self.assertEqual(status, 200)
        return payload

    def _messages(self, turn_id: str) -> list[dict]:
        with server.database_manager().reader() as db:
            return [
                message
                for message in server.CHAT_REPOSITORY.list(db)
                if message.get("client_turn_id") == turn_id
            ]

    def _library(self) -> list:
        return server.PLANNING_DATA.workout_library().list(include_archived=True)

    def test_turn_changes_show_on_the_answer_and_undo_together(self) -> None:
        turn_id = self._coach_turn()

        user, assistant = self._messages(turn_id)
        self.assertNotIn("coach_changes", user)
        self.assertEqual(
            assistant["coach_changes"],
            {
                "labels": ["Profil aktualisiert", "Trainingsvorlagen bearbeitet"],
                "undoable": True,
                "undone_at": None,
            },
        )

        result = self._undo(turn_id)

        self.assertEqual(result["status"], "undone")
        self.assertTrue(result["remote_untouched"])
        self.assertTrue(result["coach_changes"]["undone_at"])
        self.assertEqual(server.ATHLETE_DATA.profile().get()["name"], "Ada")
        self.assertFalse(self._library())
        self.assertEqual(
            self._messages(turn_id)[1]["coach_changes"], result["coach_changes"]
        )
        with self.assertRaises(server.AppError) as repeated:
            self._undo(turn_id)
        self.assertEqual(repeated.exception.status, 409)

    def test_a_record_changed_after_the_turn_aborts_the_whole_undo(self) -> None:
        turn_id = self._coach_turn()
        server.ATHLETE_DATA.profile().save({"name": "Cleo", "weight_kg": "72"})

        with self.assertRaises(server.AppError) as stale:
            self._undo(turn_id)

        self.assertEqual(stale.exception.status, 409)
        self.assertEqual(server.ATHLETE_DATA.profile().get()["name"], "Cleo")
        self.assertEqual(len(self._library()), 1)
        self.assertIsNone(self._messages(turn_id)[1]["coach_changes"]["undone_at"])
        undo_rows = [
            item
            for item in server.HISTORY.change_history_service().list()
            if item["action"] == "undo"
        ]
        self.assertEqual(undo_rows, [])

    def test_a_turn_with_untracked_writes_cannot_be_undone(self) -> None:
        turn_id = self._coach_turn(track_library=False)
        self.assertFalse(self._messages(turn_id)[1]["coach_changes"]["undoable"])

        with self.assertRaises(server.AppError) as refused:
            self._undo(turn_id)

        self.assertEqual(refused.exception.status, 409)
        self.assertEqual(server.ATHLETE_DATA.profile().get()["name"], "Bea")
        self.assertEqual(len(self._library()), 1)

    def test_unknown_and_invalid_turns_are_rejected(self) -> None:
        for turn_id, status in (("", 400), ("x" * 121, 400), ("turn-missing", 404)):
            with (
                self.subTest(turn_id=turn_id[:10]),
                self.assertRaises(server.AppError) as rejected,
            ):
                self._undo(turn_id)
            self.assertEqual(rejected.exception.status, status)

    def test_a_malformed_turn_receipt_never_breaks_the_chat_list(self) -> None:
        with server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, intent, target_system, "
                "status, receipt, created_at, updated_at) "
                "VALUES ('command-x', 'turn-x', '{}', 'local', 'completed', 'not json', 'now', 'now')"
            )
            server.CHAT_REPOSITORY.add(
                db, "assistant", "Erledigt.", client_turn_id="turn-x"
            )

        (assistant,) = self._messages("turn-x")

        self.assertNotIn("coach_changes", assistant)

    def test_undo_references_are_collected_only_inside_the_block(self) -> None:
        with change_history.collect_changes() as changes:
            server.ATHLETE_DATA.profile().save({"name": "Bea", "weight_kg": "72"})
        server.ATHLETE_DATA.profile().save({"name": "Cleo", "weight_kg": "72"})

        self.assertEqual(len(changes), 1)
        self.assertEqual(set(changes[0]), {"id", "entity_type", "action", "after_hash"})
        self.assertEqual(changes[0]["entity_type"], "profile")


if __name__ == "__main__":
    unittest.main()
