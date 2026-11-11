from __future__ import annotations

import unittest
from unittest.mock import Mock

from support import dispatch_route

from backend.http_api.coach_get import CoachGetRoutes

SESSION = {"csrf_hash": "csrf-session-one", "other": "must-not-be-used"}


class FakeHandler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.responses: list[tuple[int, object]] = []

    def send_json(self, status: int, payload: object) -> None:
        self.responses.append((status, payload))


class CoachGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history = Mock()
        self.history.page.return_value = {"messages": []}
        self.receipts = Mock()
        self.receipts.read.return_value = {"client_turn_id": "turn-1"}
        self.jobs = Mock()
        self.jobs.stream_status.return_value = {"status": "idle"}
        self.history_factory = Mock(return_value=self.history)
        self.receipts_factory = Mock(return_value=self.receipts)
        self.jobs_factory = Mock(return_value=self.jobs)
        self.routes = CoachGetRoutes(
            self.history_factory,
            self.receipts_factory,
            self.jobs_factory,
        )

    def test_history_uses_the_session_csrf_scope_and_query_defaults(self) -> None:
        handler = FakeHandler("/api/chat/history")

        self.assertTrue(dispatch_route(self.routes, handler, "/api/chat/history", session=SESSION))

        self.history.page.assert_called_once_with(
            None, None, None, session_csrf_hash="csrf-session-one"
        )
        self.assertEqual(handler.responses, [(200, {"messages": []})])
        self.receipts_factory.assert_not_called()
        self.jobs_factory.assert_not_called()

    def test_history_preserves_decoded_query_values(self) -> None:
        handler = FakeHandler(
            "/api/chat/history?cursor=cursor%2Fnext&limit=37&q=easy+run%26tempo"
        )

        self.assertTrue(dispatch_route(self.routes, handler, "/api/chat/history", session=SESSION))

        self.history.page.assert_called_once_with(
            "cursor/next", "37", "easy run&tempo", session_csrf_hash="csrf-session-one"
        )

    def test_receipt_uses_query_value_and_the_session_csrf_scope(self) -> None:
        handler = FakeHandler("/api/chat/receipt?client_turn_id=turn-1")

        self.assertTrue(dispatch_route(self.routes, handler, "/api/chat/receipt", session=SESSION))

        self.receipts.read.assert_called_once_with("turn-1", "csrf-session-one")
        self.assertEqual(handler.responses, [(200, {"client_turn_id": "turn-1"})])
        self.history_factory.assert_not_called()
        self.jobs_factory.assert_not_called()

    def test_receipt_query_default_is_none(self) -> None:
        handler = FakeHandler("/api/chat/receipt")

        self.assertTrue(dispatch_route(self.routes, handler, "/api/chat/receipt", session=SESSION))

        self.receipts.read.assert_called_once_with(None, "csrf-session-one")

    def test_status_uses_the_session_csrf_scope(self) -> None:
        handler = FakeHandler("/api/chat/status")

        self.assertTrue(dispatch_route(self.routes, handler, "/api/chat/status", session=SESSION))

        self.jobs.stream_status.assert_called_once_with("csrf-session-one")
        self.assertEqual(handler.responses, [(200, {"status": "idle"})])
        self.history_factory.assert_not_called()
        self.receipts_factory.assert_not_called()

    def test_unknown_path_has_no_service_calls(self) -> None:
        handler = FakeHandler("/api/chat/other")

        self.assertFalse(dispatch_route(self.routes, handler, "/api/chat/other", session=SESSION))

        self.history_factory.assert_not_called()
        self.receipts_factory.assert_not_called()
        self.jobs_factory.assert_not_called()
        self.assertEqual(handler.responses, [])


if __name__ == "__main__":
    unittest.main()
