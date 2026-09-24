from __future__ import annotations

import unittest
from unittest.mock import Mock, call

from backend.http_api.coach_actions_post import CoachActionsPostRoutes


class CoachActionsPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.confirmation_service = Mock()
        self.execution_service = Mock()
        self.confirmation_factory = Mock(return_value=self.confirmation_service)
        self.execution_factory = Mock(return_value=self.execution_service)
        self.handler = Mock()
        self.session = {"csrf_hash": "synthetic-session-hash"}
        self.routes = CoachActionsPostRoutes(
            self.confirmation_factory, self.execution_factory
        )

    def test_confirm_maps_proposal_id_and_session_hash(self) -> None:
        result = {"status": "confirmed"}
        self.handler.read_json.return_value = {"proposal_id": "synthetic-proposal-id"}
        self.confirmation_service.confirm.return_value = result

        handled = self.routes.handle(
            self.handler, "/api/coach/actions/confirm", self.session
        )

        self.assertTrue(handled)
        self.handler.read_json.assert_called_once_with()
        self.confirmation_factory.assert_called_once_with()
        self.execution_factory.assert_not_called()
        self.confirmation_service.confirm.assert_called_once_with(
            "synthetic-proposal-id", "synthetic-session-hash"
        )
        self.handler.send_json.assert_called_once_with(200, result)

    def test_execute_maps_token_session_hash_and_payload_hash(self) -> None:
        result = {"status": "executed"}
        self.handler.read_json.return_value = {
            "action_token": "synthetic-action-token",
            "payload_hash": "synthetic-payload-hash",
        }
        self.execution_service.execute.return_value = result

        handled = self.routes.handle(
            self.handler, "/api/coach/actions/execute", self.session
        )

        self.assertTrue(handled)
        self.handler.read_json.assert_called_once_with()
        self.confirmation_factory.assert_not_called()
        self.execution_factory.assert_called_once_with()
        self.execution_service.execute.assert_called_once_with(
            "synthetic-action-token",
            "synthetic-session-hash",
            "synthetic-payload-hash",
        )
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        handled = self.routes.handle(self.handler, "/api/coach/other", self.session)

        self.assertFalse(handled)
        self.handler.read_json.assert_not_called()
        self.confirmation_factory.assert_not_called()
        self.execution_factory.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_service_errors_propagate_without_response(self) -> None:
        error = RuntimeError("synthetic confirmation failure")
        self.handler.read_json.return_value = {"proposal_id": "synthetic-proposal-id"}
        self.confirmation_service.confirm.side_effect = error

        with self.assertRaises(RuntimeError) as caught:
            self.routes.handle(
                self.handler, "/api/coach/actions/confirm", self.session
            )

        self.assertIs(caught.exception, error)
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_not_called()

    def test_execute_error_propagates_without_response_after_expected_arguments(self) -> None:
        error = RuntimeError("synthetic execution failure")
        self.handler.read_json.return_value = {
            "action_token": "synthetic-action-token",
            "payload_hash": "synthetic-payload-hash",
        }
        self.execution_service.execute.side_effect = error

        with self.assertRaises(RuntimeError) as caught:
            self.routes.handle(
                self.handler, "/api/coach/actions/execute", self.session
            )

        self.assertIs(caught.exception, error)
        self.handler.read_json.assert_called_once_with()
        self.execution_factory.assert_called_once_with()
        self.execution_service.execute.assert_called_once_with(
            "synthetic-action-token",
            "synthetic-session-hash",
            "synthetic-payload-hash",
        )
        self.handler.send_json.assert_not_called()

    def test_factories_are_resolved_for_each_request(self) -> None:
        first_confirmation, second_confirmation = Mock(), Mock()
        first_execution, second_execution = Mock(), Mock()
        self.confirmation_factory.side_effect = [first_confirmation, second_confirmation]
        self.execution_factory.side_effect = [first_execution, second_execution]
        self.handler.read_json.side_effect = [
            {"proposal_id": "first-proposal"},
            {"proposal_id": "second-proposal"},
            {"action_token": "first-token", "payload_hash": "first-hash"},
            {"action_token": "second-token", "payload_hash": "second-hash"},
        ]

        self.routes.handle(self.handler, "/api/coach/actions/confirm", self.session)
        self.routes.handle(self.handler, "/api/coach/actions/confirm", self.session)
        self.routes.handle(self.handler, "/api/coach/actions/execute", self.session)
        self.routes.handle(self.handler, "/api/coach/actions/execute", self.session)

        self.confirmation_factory.assert_has_calls([call(), call()])
        self.execution_factory.assert_has_calls([call(), call()])
        first_confirmation.confirm.assert_called_once_with(
            "first-proposal", "synthetic-session-hash"
        )
        second_confirmation.confirm.assert_called_once_with(
            "second-proposal", "synthetic-session-hash"
        )
        first_execution.execute.assert_called_once_with(
            "first-token", "synthetic-session-hash", "first-hash"
        )
        second_execution.execute.assert_called_once_with(
            "second-token", "synthetic-session-hash", "second-hash"
        )
        self.assertEqual(self.handler.read_json.call_count, 4)


if __name__ == "__main__":
    unittest.main()
