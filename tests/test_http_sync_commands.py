"""HTTP sync command parsing, authorization preconditions, and queue contracts."""

import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.sync_commands import SyncCommandEndpoint


class SyncCommandEndpointTests(unittest.TestCase):
    def setUp(self):
        self.queue = Mock()
        self.state = Mock()
        self.performance = Mock()
        self.full_resync = Mock()
        self.endpoint = SyncCommandEndpoint(
            self.queue, self.state, self.performance, self.full_resync,
            lambda: "operation-1", {"intervals": 90, "garmin": 30}, -1,
        )

    def test_body_policy_preserves_bodyless_routes_and_unknown_paths(self):
        self.assertFalse(SyncCommandEndpoint.handles("/api/other"))
        self.assertFalse(SyncCommandEndpoint.needs_body("/api/weather/sync"))
        self.assertTrue(SyncCommandEndpoint.needs_body("/api/garmin/full-resync"))
        self.assertTrue(SyncCommandEndpoint.needs_body("/api/sync/jobs/abc-123/resolve"))
        self.assertFalse(SyncCommandEndpoint.handles("/api/sync/jobs/not_valid/resolve"))

    def test_manual_period_validation_precedes_queue_mutation(self):
        self.state.sync_period.return_value = 30
        self.state.set_sync_period.side_effect = ValueError("invalid")
        with self.assertRaises(AppError) as raised:
            self.endpoint.execute("/api/garmin/sync", {"days": 91})
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("zwischen 1 und 90 Tagen", raised.exception.message)
        self.queue.enqueue.assert_not_called()
        self.state.set_sync_period.side_effect = None
        self.state.set_sync_period.return_value = 7
        self.queue.enqueue.return_value = {"id": "job-1"}
        self.assertEqual(
            self.endpoint.execute("/api/garmin/sync", {"days": 7}),
            (202, {"id": "job-1"}),
        )
        self.queue.enqueue.assert_called_once_with(
            "garmin", "refresh", {"days": 7, "reason": "manual"}, requested_by="user"
        )

    def test_full_resync_requires_exact_confirmation_before_provider_call(self):
        with self.assertRaises(AppError):
            self.endpoint.execute("/api/intervals/full-resync", {"confirm": "yes"})
        self.full_resync.resync.assert_not_called()
        self.full_resync.resync.return_value = {"status": "ok"}
        self.assertEqual(
            self.endpoint.execute("/api/intervals/full-resync", {"confirm": "FULL_RESYNC"}),
            (200, {"status": "ok"}),
        )
        self.full_resync.resync.assert_called_once_with(
            "intervals", operation_id="operation-1"
        )

    def test_job_request_and_conflict_resolution_keep_requested_by_and_status(self):
        self.queue.enqueue.return_value = {"id": "job-2"}
        self.assertEqual(
            self.endpoint.execute("/api/sync/jobs", {"provider": "weather", "force": True}),
            (202, {"id": "job-2"}),
        )
        self.queue.enqueue.assert_called_once_with(
            "weather", "refresh", {"force": True}, requested_by="user"
        )
        self.queue.resolve.return_value = {"status": "resolved"}
        self.assertEqual(
            self.endpoint.execute("/api/sync/jobs/abc-123/resolve", {"strategy": "keep_local"}),
            (200, {"status": "resolved"}),
        )
        self.queue.resolve.assert_called_once_with("abc-123", {"strategy": "keep_local"})

if __name__ == "__main__":
    unittest.main()
