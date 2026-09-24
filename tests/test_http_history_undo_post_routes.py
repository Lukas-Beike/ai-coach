from __future__ import annotations

import unittest
from unittest.mock import Mock, call

from backend.http_api.history_undo_post import HistoryUndoPostRoutes


class HistoryUndoPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.undo = Mock()
        self.proposal = Mock()
        self.undo_factory = Mock(return_value=self.undo)
        self.proposal_factory = Mock(return_value=self.proposal)
        self.handler = Mock()
        self.session = {"csrf_hash": "synthetic-session-hash"}
        self.routes = HistoryUndoPostRoutes(self.undo_factory, self.proposal_factory)

    def test_preview_creates_session_bound_proposal_and_projects_response(self) -> None:
        request = {"change_id": "synthetic-change-id"}
        preview = {
            "status": "preview",
            "undo_target_hash": "synthetic-target-hash",
            "proposal": {"action_type": "undo_change", "payload": {"change_id": "synthetic-change-id"}},
        }
        proposed_action = {"id": "synthetic-proposal-id", "status": "preview"}
        self.handler.read_json.return_value = request
        self.undo.preview.return_value = preview
        self.proposal.create.return_value = {"proposed_action": proposed_action}

        handled = self.routes.handle(
            self.handler, "/api/change-history/undo/preview", self.session
        )

        self.assertTrue(handled)
        self.undo_factory.assert_called_once_with()
        self.undo.preview.assert_called_once_with("synthetic-change-id")
        self.proposal_factory.assert_called_once_with()
        self.proposal.create.assert_called_once_with(
            {"action_type": "undo_change", "payload": {"change_id": "synthetic-change-id"}},
            "synthetic-session-hash",
        )
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(
            200,
            {
                "status": "preview",
                "undo_target_hash": "synthetic-target-hash",
                "proposed_action": proposed_action,
            },
        )

    def test_apply_passes_whole_payload_and_sends_result(self) -> None:
        payload = {"change_id": "synthetic-change-id", "expected_current_hash": "synthetic-hash"}
        result = {"status": "undone", "remote_untouched": True}
        self.handler.read_json.return_value = payload
        self.undo.apply.return_value = result

        handled = self.routes.handle(self.handler, "/api/change-history/undo", self.session)

        self.assertTrue(handled)
        self.undo_factory.assert_called_once_with()
        self.undo.apply.assert_called_once_with(payload)
        self.proposal_factory.assert_not_called()
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/other", self.session))

        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()
        self.undo_factory.assert_not_called()
        self.proposal_factory.assert_not_called()

    def test_factories_are_resolved_for_each_request(self) -> None:
        first_undo, second_undo = Mock(), Mock()
        first_proposal, second_proposal = Mock(), Mock()
        first_undo.preview.return_value = {"proposal": {"id": "first"}}
        second_undo.preview.return_value = {"proposal": {"id": "second"}}
        first_proposal.create.return_value = {"proposed_action": {"id": "first"}}
        second_proposal.create.return_value = {"proposed_action": {"id": "second"}}
        self.undo_factory.side_effect = [first_undo, second_undo]
        self.proposal_factory.side_effect = [first_proposal, second_proposal]
        self.handler.read_json.side_effect = [{"change_id": "first"}, {"change_id": "second"}]

        self.routes.handle(self.handler, "/api/change-history/undo/preview", self.session)
        self.routes.handle(self.handler, "/api/change-history/undo/preview", self.session)

        self.undo_factory.assert_has_calls([call(), call()])
        self.proposal_factory.assert_has_calls([call(), call()])
        first_undo.preview.assert_called_once_with("first")
        second_undo.preview.assert_called_once_with("second")
        self.assertEqual(self.handler.read_json.call_count, 2)

    def test_preview_error_does_not_create_proposal_or_send_response(self) -> None:
        self.handler.read_json.return_value = {"change_id": "synthetic-invalid"}
        self.undo.preview.side_effect = RuntimeError("synthetic preview failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic preview failure"):
            self.routes.handle(
                self.handler, "/api/change-history/undo/preview", self.session
            )

        self.proposal_factory.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_service_exception_propagates_without_response(self) -> None:
        self.handler.read_json.return_value = {"change_id": "synthetic-change-id"}
        self.undo.apply.side_effect = RuntimeError("synthetic apply failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic apply failure"):
            self.routes.handle(self.handler, "/api/change-history/undo", self.session)

        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
