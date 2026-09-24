from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.coach_get import CoachGetRoutes


class FakeHandler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.responses: list[tuple[int, object]] = []

    def send_json(self, status: int, payload: object) -> None:
        self.responses.append((status, payload))


class CoachGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = Mock()
        self.auth.require_auth.return_value = {
            "csrf_hash": "csrf-session-one",
            "other": "must-not-be-used",
        }
        self.history = Mock()
        self.history.page.return_value = {"messages": []}
        self.receipts = Mock()
        self.receipts.read.return_value = {"client_turn_id": "turn-1"}
        self.jobs = Mock()
        self.jobs.stream_status.return_value = {"status": "idle"}
        self.auth_factory = Mock(return_value=self.auth)
        self.history_factory = Mock(return_value=self.history)
        self.receipts_factory = Mock(return_value=self.receipts)
        self.jobs_factory = Mock(return_value=self.jobs)
        self.routes = CoachGetRoutes(
            self.auth_factory,
            self.history_factory,
            self.receipts_factory,
            self.jobs_factory,
        )

    def test_history_uses_authenticated_csrf_scope_and_query_defaults(self) -> None:
        handler = FakeHandler("/api/chat/history")

        self.assertTrue(self.routes.handle(handler, "/api/chat/history"))

        self.auth.require_auth.assert_called_once_with(handler)
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

        self.assertTrue(self.routes.handle(handler, "/api/chat/history"))

        self.history.page.assert_called_once_with(
            "cursor/next", "37", "easy run&tempo", session_csrf_hash="csrf-session-one"
        )

    def test_receipt_uses_query_value_and_authenticated_csrf_scope(self) -> None:
        handler = FakeHandler("/api/chat/receipt?client_turn_id=turn-1")

        self.assertTrue(self.routes.handle(handler, "/api/chat/receipt"))

        self.receipts.read.assert_called_once_with("turn-1", "csrf-session-one")
        self.assertEqual(handler.responses, [(200, {"client_turn_id": "turn-1"})])
        self.history_factory.assert_not_called()
        self.jobs_factory.assert_not_called()

    def test_receipt_query_default_is_none(self) -> None:
        handler = FakeHandler("/api/chat/receipt")

        self.assertTrue(self.routes.handle(handler, "/api/chat/receipt"))

        self.receipts.read.assert_called_once_with(None, "csrf-session-one")

    def test_status_uses_authenticated_csrf_scope(self) -> None:
        handler = FakeHandler("/api/chat/status")

        self.assertTrue(self.routes.handle(handler, "/api/chat/status"))

        self.jobs.stream_status.assert_called_once_with("csrf-session-one")
        self.assertEqual(handler.responses, [(200, {"status": "idle"})])
        self.history_factory.assert_not_called()
        self.receipts_factory.assert_not_called()

    def test_auth_service_is_resolved_for_each_keep_alive_request(self) -> None:
        second_auth = Mock()
        second_auth.require_auth.return_value = {"csrf_hash": "csrf-session-two"}
        self.auth_factory.side_effect = [self.auth, second_auth]
        first = FakeHandler("/api/chat/status")
        second = FakeHandler("/api/chat/status")

        self.assertTrue(self.routes.handle(first, "/api/chat/status"))
        self.assertTrue(self.routes.handle(second, "/api/chat/status"))

        self.assertEqual(self.auth_factory.call_count, 2)
        self.auth.require_auth.assert_called_once_with(first)
        second_auth.require_auth.assert_called_once_with(second)
        self.jobs.stream_status.assert_has_calls(
            [unittest.mock.call("csrf-session-one"), unittest.mock.call("csrf-session-two")]
        )

    def test_unknown_path_has_no_auth_or_service_calls(self) -> None:
        handler = FakeHandler("/api/chat/other")

        self.assertFalse(self.routes.handle(handler, "/api/chat/other"))

        self.auth_factory.assert_not_called()
        self.history_factory.assert_not_called()
        self.receipts_factory.assert_not_called()
        self.jobs_factory.assert_not_called()
        self.assertEqual(handler.responses, [])

    def test_auth_error_propagates_before_service_resolution(self) -> None:
        denied = AppError(401, "unauthorized")
        self.auth.require_auth.side_effect = denied
        handler = FakeHandler("/api/chat/history")

        with self.assertRaises(AppError) as caught:
            self.routes.handle(handler, "/api/chat/history")

        self.assertIs(caught.exception, denied)
        self.history_factory.assert_not_called()
        self.receipts_factory.assert_not_called()
        self.jobs_factory.assert_not_called()
        self.assertEqual(handler.responses, [])


if __name__ == "__main__":
    unittest.main()
