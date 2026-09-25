from __future__ import annotations

import threading
import unittest
from unittest.mock import Mock

from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.errors import AppError


class CoachToolDispatchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owners = {name: Mock() for name in (
            "read", "profile", "athlete", "artifact", "changes", "templates",
            "library", "sync", "actions",
        )}
        self.factories = {
            name: Mock(return_value=self.owners[name])
            for name in ("read", "profile", "athlete", "library", "sync")
        }
        for name in ("read", "athlete", "artifact", "changes", "sync", "actions"):
            self.owners[name].execute.return_value = None
        self.service = CoachToolDispatchService(
            self.factories["read"],
            self.factories["profile"],
            self.factories["athlete"],
            self.owners["artifact"],
            self.owners["changes"],
            self.owners["templates"],
            self.factories["library"],
            self.factories["sync"],
            self.owners["actions"],
        )
        self.intent = {"operation": "synthetic"}
        self.job_ids: list[str] = []

    def execute(self, name: str, arguments: dict | None = None, **kwargs: object) -> dict:
        return self.service.execute(
            name,
            arguments or {},
            intent=self.intent,
            conversation_id="conversation-1",
            client_turn_id="turn-1",
            session_csrf_hash="csrf-1",
            sync_job_ids=self.job_ids,
            **kwargs,
        )

    def test_read_result_precedes_mutating_owners(self) -> None:
        self.owners["read"].execute.return_value = {"ok": True, "profile": {}}

        self.assertEqual(self.execute("read_profile"), {"ok": True, "profile": {}})
        self.owners["read"].execute.assert_called_once_with("read_profile", {})
        for name in self.factories.keys() - {"read"}:
            self.factories[name].assert_not_called()

    def test_profile_and_athlete_effects_route_to_concrete_owners(self) -> None:
        self.owners["profile"].apply.return_value = {"ok": True}
        self.owners["athlete"].execute.return_value = {"ok": True, "saved": 1}

        self.assertEqual(self.execute("update_profile", {"changes": []}), {"ok": True})
        self.owners["profile"].apply.assert_called_once_with({"changes": []}, self.intent)
        self.assertEqual(self.execute("save_checkin", {"payload": {}}), {"ok": True, "saved": 1})
        self.owners["athlete"].execute.assert_any_call("save_checkin", {"payload": {}}, self.intent)

    def test_artifact_routes_conversation_and_turn_identity(self) -> None:
        self.owners["artifact"].execute.return_value = {"ok": True, "artifact_id": "a-1"}

        self.assertEqual(self.execute("stage_training_plan", {"payload": {}})["artifact_id"], "a-1")
        self.owners["artifact"].execute.assert_called_once_with(
            "stage_training_plan", {"payload": {}}, self.intent, "conversation-1", "turn-1"
        )

    def test_planning_change_routes_intent(self) -> None:
        self.owners["changes"].execute.return_value = {"ok": True, "updated": 1}

        self.assertEqual(self.execute("apply_training_changes", {"changes": []})["updated"], 1)
        self.owners["changes"].execute.assert_called_once_with(
            "apply_training_changes", {"changes": []}, self.intent
        )

    def test_template_and_library_plan_routes(self) -> None:
        self.owners["templates"].execute.return_value = {"ok": True, "saved": 2}
        self.owners["library"].execute.return_value = {"ok": True, "planned": 1}

        self.assertEqual(self.execute("manage_training_templates", {"templates": []})["saved"], 2)
        self.owners["templates"].execute.assert_called_once_with({"templates": []}, self.intent)
        self.assertEqual(self.execute("apply_workout_library_plan", {"entries": []})["planned"], 1)
        self.owners["library"].execute.assert_called_once_with({"entries": []}, self.intent)

    def test_sync_receives_same_job_list_and_cancellation_event(self) -> None:
        event = threading.Event()
        self.owners["sync"].execute.return_value = {"ok": True, "status": "queued"}

        self.assertEqual(
            self.execute("start_provider_refresh", {"days": 1}, cancel_event=event)["status"],
            "queued",
        )
        self.owners["sync"].execute.assert_called_once_with(
            "start_provider_refresh", {"days": 1}, intent=self.intent,
            sync_job_ids=self.job_ids, cancel_event=event,
        )

    def test_planning_action_receives_session_binding(self) -> None:
        self.owners["actions"].execute.return_value = {"ok": True, "proposed_action": {}}

        self.assertIn("proposed_action", self.execute("undo_training_change", {"change_id": "c-1"}))
        self.owners["actions"].execute.assert_called_once_with(
            "undo_training_change", {"change_id": "c-1"}, self.intent, "turn-1", "csrf-1"
        )

    def test_unknown_name_has_stable_client_error_without_mutation(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.execute("not_a_tool")

        self.assertEqual((raised.exception.status, raised.exception.reason), (400, "unknown_coach_tool"))
        for name in self.factories.keys() - {"read", "athlete"}:
            self.factories[name].assert_not_called()
        for name in ("artifact", "changes", "templates"):
            self.owners[name].execute.assert_not_called()
        self.owners["actions"].execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
