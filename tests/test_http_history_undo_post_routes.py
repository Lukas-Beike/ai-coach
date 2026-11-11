from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.history_undo_post import HistoryUndoPostRoutes


class HistoryUndoPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.undo = Mock()
        self.undo_factory = Mock(return_value=self.undo)
        self.handler = Mock()
        self.turn_undo = Mock()
        self.routes = HistoryUndoPostRoutes(self.undo_factory, self.turn_undo)

    def test_apply_passes_whole_payload_and_sends_result(self) -> None:
        payload = {
            "change_id": "synthetic-change-id",
            "expected_current_hash": "synthetic-hash",
        }
        result = {"status": "undone", "remote_untouched": True}
        self.handler.read_json.return_value = payload
        self.undo.apply.return_value = result

        handled = self.routes.handle(self.handler, "/api/change-history/undo")

        self.assertTrue(handled)
        self.undo_factory.assert_called_once_with()
        self.undo.apply.assert_called_once_with(payload)
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_feedback_undo_returns_the_session_load_of_the_named_activity(self) -> None:
        load = Mock(return_value={"value": 120})
        routes = HistoryUndoPostRoutes(self.undo_factory, self.turn_undo, load)
        payload = {"change_id": "c", "expected_current_hash": "h", "activity_id": "a1"}
        self.handler.read_json.return_value = payload
        self.undo.apply.return_value = {
            "status": "undone",
            "entity_type": "activity_feedback",
        }

        routes.handle(self.handler, "/api/change-history/undo")

        load.assert_called_once_with("a1")
        self.handler.send_json.assert_called_once_with(
            200,
            {
                "status": "undone",
                "entity_type": "activity_feedback",
                "session_rpe_load": {"value": 120},
            },
        )

    def test_other_undo_entities_get_no_session_load(self) -> None:
        load = Mock()
        routes = HistoryUndoPostRoutes(self.undo_factory, self.turn_undo, load)
        self.handler.read_json.return_value = {"change_id": "c", "activity_id": "a1"}
        self.undo.apply.return_value = {"status": "undone", "entity_type": "profile"}

        routes.handle(self.handler, "/api/change-history/undo")

        load.assert_not_called()
        self.handler.send_json.assert_called_once_with(
            200, {"status": "undone", "entity_type": "profile"}
        )

    def test_turn_undo_passes_only_the_turn_id(self) -> None:
        result = {"status": "undone", "remote_untouched": True}
        self.handler.read_json.return_value = {
            "client_turn_id": "turn-1",
            "change_id": "ignored",
        }
        self.turn_undo.undo.return_value = result

        handled = self.routes.handle(self.handler, "/api/change-history/undo-turn")

        self.assertTrue(handled)
        self.turn_undo.undo.assert_called_once_with("turn-1")
        self.undo_factory.assert_not_called()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        # The undo preview and focus-backfill routes are no longer registered.
        for path in (
            "/api/other",
            "/api/change-history/undo/preview",
            "/api/change-history/undo-focus-backfill",
        ):
            self.assertFalse(self.routes.handle(self.handler, path))

        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()
        self.undo_factory.assert_not_called()

    def test_service_exception_propagates_without_response(self) -> None:
        self.handler.read_json.return_value = {"change_id": "synthetic-change-id"}
        self.undo.apply.side_effect = RuntimeError("synthetic apply failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic apply failure"):
            self.routes.handle(self.handler, "/api/change-history/undo")

        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
