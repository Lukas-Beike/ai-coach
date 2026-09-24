"""Tests for synchronization command HTTP transport."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.sync_commands_post import SyncCommandPostRoute


class SyncCommandPostRouteTests(unittest.TestCase):
    def test_unknown_path_does_not_construct_endpoint(self) -> None:
        factory = Mock()
        handler = Mock()

        handled = SyncCommandPostRoute(factory).handle(handler, "/api/unknown")

        self.assertFalse(handled)
        factory.assert_not_called()
        handler.read_json.assert_not_called()
        handler.send_json.assert_not_called()

    def test_bodyless_command_preserves_status_and_payload(self) -> None:
        endpoint = Mock()
        endpoint.execute.return_value = (202, {"id": "job-3"})
        handler = Mock()

        handled = SyncCommandPostRoute(lambda: endpoint).handle(
            handler, "/api/weather/sync"
        )

        self.assertTrue(handled)
        handler.read_json.assert_not_called()
        endpoint.execute.assert_called_once_with("/api/weather/sync", None)
        handler.send_json.assert_called_once_with(202, {"id": "job-3"})

    def test_body_command_reads_json_before_constructing_endpoint(self) -> None:
        order: list[str] = []
        endpoint = Mock()
        endpoint.execute.return_value = (202, {"id": "job-4"})
        handler = Mock()
        handler.read_json.side_effect = lambda: order.append("body") or {"days": 7}

        def make_endpoint() -> Mock:
            order.append("endpoint")
            return endpoint

        SyncCommandPostRoute(make_endpoint).handle(handler, "/api/sync")

        self.assertEqual(order, ["body", "endpoint"])
        endpoint.execute.assert_called_once_with("/api/sync", {"days": 7})


if __name__ == "__main__":
    unittest.main()
