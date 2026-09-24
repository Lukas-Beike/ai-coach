"""Direct contract tests for authenticated sync and activity GET routes."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import Mock

from backend.http_api.sync_get import SyncGetRoutes


class FakeHandler:
    def __init__(self, path: str = "") -> None:
        self.path = path
        self.responses: list[tuple[int, object]] = []

    def send_json(self, status: int, payload: object) -> None:
        self.responses.append((status, payload))


class SyncGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = Mock()
        self.queue = Mock()
        self.sync_state = Mock()
        self.activities = Mock()
        self.auth_factory = Mock(return_value=self.auth)
        self.queue_factory = Mock(return_value=self.queue)
        self.sync_state_factory = Mock(return_value=self.sync_state)
        self.activity_factory = Mock(return_value=self.activities)
        self.today = Mock(return_value=date(2026, 9, 24))
        self.routes = SyncGetRoutes(
            self.auth_factory,
            self.queue_factory,
            self.sync_state_factory,
            self.activity_factory,
            self.today,
            -1,
        )
        self.handler = FakeHandler()

    def test_sync_job_payload_and_exact_path_pattern(self) -> None:
        self.queue.state.return_value = {"id": "a1-b2", "state": "running"}
        self.assertTrue(self.routes.handle(self.handler, "/api/sync/jobs/a1-b2"))
        self.assertEqual(self.handler.responses, [(200, self.queue.state.return_value)])
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.queue.state.assert_called_once_with("a1-b2")

        for path in (
            "/api/sync/jobs/",
            "/api/sync/jobs/G123",
            "/api/sync/jobs/g123",
            "/api/sync/jobs/123/extra",
        ):
            with self.subTest(path=path):
                handler = FakeHandler()
                factories = (
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                )
                route = SyncGetRoutes(
                    *factories, lambda: date(2026, 9, 24), -1
                )
                self.assertFalse(route.handle(handler, path))
                for factory in factories:
                    factory.assert_not_called()
                self.assertEqual(handler.responses, [])

    def test_sync_status_payload_is_forwarded_unchanged(self) -> None:
        payload = {"status": "idle", "jobs": [{"id": "fake"}]}
        self.sync_state.state.return_value = payload
        self.assertTrue(self.routes.handle(self.handler, "/api/sync/status"))
        self.assertEqual(self.handler.responses, [(200, payload)])
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.sync_state.state.assert_called_once_with()

    def test_activity_query_uses_first_value_and_local_today_per_request(self) -> None:
        self.activities.page.return_value = {"activities": []}
        self.handler.path = (
            "/api/activities?cursor=first&cursor=second&limit=12&limit=24"
            "&days=7&days=30"
        )
        self.assertTrue(self.routes.handle(self.handler, "/api/activities"))
        self.activities.page.assert_called_once_with(
            "first", "12", "7", today=date(2026, 9, 24)
        )
        self.assertEqual(self.handler.responses, [(200, {"activities": []})])

        self.activities.page.reset_mock()
        self.today.return_value = date(2026, 9, 25)
        self.handler.path = "/api/activities"
        self.assertTrue(self.routes.handle(self.handler, "/api/activities"))
        self.activities.page.assert_called_once_with(
            None, None, -1, today=date(2026, 9, 25)
        )
        self.assertEqual(self.today.call_count, 2)

    def test_authentication_failure_precedes_data_factory_and_clock(self) -> None:
        denied = RuntimeError("denied")
        self.auth.require_auth.side_effect = denied
        with self.assertRaisesRegex(RuntimeError, "denied"):
            self.routes.handle(self.handler, "/api/activities")
        self.queue_factory.assert_not_called()
        self.sync_state_factory.assert_not_called()
        self.activity_factory.assert_not_called()
        self.today.assert_not_called()

    def test_auth_factory_is_resolved_for_each_keep_alive_request(self) -> None:
        second_auth = Mock()
        self.auth_factory.side_effect = [self.auth, second_auth]
        self.sync_state.state.return_value = {"status": "idle"}
        self.routes.handle(self.handler, "/api/sync/status")
        self.routes.handle(self.handler, "/api/sync/status")
        self.assertEqual(self.auth_factory.call_count, 2)
        self.auth.require_auth.assert_called_once_with(self.handler)
        second_auth.require_auth.assert_called_once_with(self.handler)

    def test_unknown_path_resolves_no_factories(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/sync/other"))
        self.auth_factory.assert_not_called()
        self.queue_factory.assert_not_called()
        self.sync_state_factory.assert_not_called()
        self.activity_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
