from __future__ import annotations

import unittest
from typing import Any
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

    def test_stage_authorizes_operation_and_local_plan_scope_before_service_call(
        self,
    ) -> None:
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

    def test_missing_authorization_or_artifact_is_rejected_before_the_service_exists(
        self,
    ) -> None:
        stage, commit = "stage_training_plan", "commit_training_plan"
        denied = (403, "intent_scope_denied")
        classified = {"operation": commit, "artifact_id": "artifact-1"}
        # (tool, arguments, intent, (status, reason))
        cases: tuple[tuple[Any, ...], ...] = (
            (
                stage,
                {},
                {"operation": "other", "authorization_scope": ["local_plan"]},
                denied,
            ),
            (stage, {}, {"operation": stage, "authorization_scope": []}, denied),
            (commit, {}, {"operation": commit}, (400, "artifact_required")),
            (
                commit,
                {"artifact_id": "artifact-other"},
                {**classified, "authorization_scope": ["artifact:artifact-1"]},
                denied,
            ),
            (
                commit,
                {"artifact_id": "artifact-1"},
                {**classified, "authorization_scope": []},
                denied,
            ),
        )
        for tool, arguments, intent, expected in cases:
            with self.subTest(tool=tool, intent=intent):
                with self.assertRaises(AppError) as raised:
                    self.service.execute(
                        tool, arguments, intent, "conversation-1", "turn-1"
                    )

                self.assertEqual(
                    (raised.exception.status, raised.exception.reason), expected
                )
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

    def test_unknown_tool_name_returns_none_without_constructing_artifact_service(
        self,
    ) -> None:
        result = self.service.execute(
            "some_other_tool", {}, {}, "conversation-1", "turn-1"
        )

        self.assertIsNone(result)
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
