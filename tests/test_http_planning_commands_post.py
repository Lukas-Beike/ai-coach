"""Focused unit tests for the authenticated planning command POST route."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.planning_commands_post import PlanningCommandsPostRoutes


class PlanningCommandsPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.command_service = Mock()
        self.command_service.execute.return_value = {"status": "completed"}
        self.provision_service = Mock()
        self.provision_service.ensure.return_value = "conversation-123"
        self.routes = PlanningCommandsPostRoutes(
            lambda: self.command_service,
            lambda: self.provision_service,
        )
        self.handler = SimpleNamespace(
            read_json=Mock(return_value={"client_turn_id": "turn-1", "action": "test"}),
            send_json=Mock(),
        )
        self.session = {"csrf_hash": "session-csrf-hash"}

    def test_success_dispatches_payload_conversation_and_csrf_hash(self) -> None:
        handled = self.routes.handle(self.handler, "/api/planning/commands", self.session)
        self.assertTrue(handled)
        self.handler.read_json.assert_called_once_with()
        self.provision_service.ensure.assert_called_once_with()
        self.command_service.execute.assert_called_once_with(
            {"client_turn_id": "turn-1", "action": "test"},
            conversation_id="conversation-123",
            session_csrf_hash="session-csrf-hash",
        )
        self.handler.send_json.assert_called_once_with(200, {"status": "completed"})

    def test_wrong_path_returns_false_without_side_effects(self) -> None:
        handled = self.routes.handle(self.handler, "/api/other", self.session)
        self.assertFalse(handled)
        self.handler.read_json.assert_not_called()
        self.provision_service.ensure.assert_not_called()
        self.command_service.execute.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_preserves_app_error_for_outer_handler(self) -> None:
        error = AppError(400, "Invalid command", reason="command_invalid")
        self.command_service.execute.side_effect = error
        with self.assertRaises(AppError) as raised:
            self.routes.handle(self.handler, "/api/planning/commands", self.session)
        self.assertIs(raised.exception, error)
        self.handler.send_json.assert_not_called()
