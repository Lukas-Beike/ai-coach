from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.coach.plan_artifact_tools import CoachPlanArtifactToolService
from backend.errors import AppError


class CoachPlanArtifactToolServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.artifacts = Mock()
        self.artifacts.stage.return_value = {"ok": True, "status": "draft"}
        self.artifacts.commit.return_value = {"ok": True, "status": "committed"}
        self.factory = Mock(return_value=self.artifacts)
        self.service = CoachPlanArtifactToolService(self.factory)

    def test_stage_authorizes_operation_and_local_plan_scope_before_service_call(self) -> None:
        result = self.service.execute(
            "stage_training_plan",
            {"payload": {"workouts": []}},
            {"operation": "stage_training_plan", "authorization_scope": ["local_plan"]},
            "conversation-1",
            "turn-1",
        )

        self.assertEqual(result, {"ok": True, "status": "draft"})
        self.factory.assert_called_once_with()
        self.artifacts.stage.assert_called_once_with(
            {"payload": {"workouts": []}}, "conversation-1", "turn-1"
        )

    def test_stage_rejects_missing_authorization_without_constructing_artifact_service(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "stage_training_plan", {}, {"operation": "other", "authorization_scope": ["local_plan"]},
                "conversation-1", "turn-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factory.assert_not_called()

    def test_stage_rejects_missing_local_plan_scope_without_constructing_artifact_service(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "stage_training_plan", {}, {"operation": "stage_training_plan", "authorization_scope": []},
                "conversation-1", "turn-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factory.assert_not_called()

    def test_commit_requires_classified_artifact_id(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "commit_training_plan", {}, {"operation": "commit_training_plan"},
                "conversation-1", "turn-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (400, "artifact_required"))
        self.factory.assert_not_called()

    def test_commit_rejects_argument_id_mismatch(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "commit_training_plan",
                {"artifact_id": "artifact-other"},
                {
                    "operation": "commit_training_plan",
                    "artifact_id": "artifact-1",
                    "authorization_scope": ["artifact:artifact-1"],
                },
                "conversation-1",
                "turn-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factory.assert_not_called()

    def test_commit_requires_artifact_scope(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "commit_training_plan",
                {"artifact_id": "artifact-1"},
                {"operation": "commit_training_plan", "artifact_id": "artifact-1", "authorization_scope": []},
                "conversation-1",
                "turn-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factory.assert_not_called()

    def test_commit_passes_matching_id_explicit_flag_and_conversation(self) -> None:
        result = self.service.execute(
            "commit_training_plan",
            {"artifact_id": "artifact-1"},
            {
                "operation": "commit_training_plan",
                "artifact_id": "artifact-1",
                "authorization_scope": ["artifact:artifact-1"],
                "_artifact_explicit": True,
            },
            "conversation-1",
            "turn-1",
        )

        self.assertEqual(result, {"ok": True, "status": "committed"})
        self.factory.assert_called_once_with()
        self.artifacts.commit.assert_called_once_with(
            "artifact-1", "conversation-1", explicit_artifact=True
        )

    def test_unknown_tool_name_returns_none_without_constructing_artifact_service(self) -> None:
        result = self.service.execute("some_other_tool", {}, {}, "conversation-1", "turn-1")

        self.assertIsNone(result)
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
