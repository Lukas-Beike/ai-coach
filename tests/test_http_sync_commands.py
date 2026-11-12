"""HTTP sync command parsing, authorization preconditions, and queue contracts."""

import unittest
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.http_api import sync_commands
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.nutrition.contracts import nutrition_approval_item


class SyncCommandEndpointTests(unittest.TestCase):
    def setUp(self):
        self.queue = Mock()
        self.state = Mock()
        self.performance = Mock()
        self.full_resync = Mock()
        self.endpoint = SyncCommandEndpoint(
            self.queue,
            self.state,
            self.full_resync,
            lambda: "operation-1",
            {"intervals": 90, "garmin": 30},
            -1,
            provider_configured=lambda provider: True,
        )

    def test_body_policy_preserves_bodyless_routes_and_unknown_paths(self):
        self.assertFalse(SyncCommandEndpoint.handles("/api/other"))
        self.assertFalse(SyncCommandEndpoint.needs_body("/api/weather/sync"))
        self.assertTrue(SyncCommandEndpoint.needs_body("/api/garmin/full-resync"))
        self.assertFalse(SyncCommandEndpoint.handles("/api/sync/jobs/abc-123/resolve"))

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

    def test_full_resync_is_accepted_with_its_operation_id_and_runs_in_the_background(
        self,
    ):
        self.full_resync.start.return_value = {
            "status": "started",
            "source": "garmin",
            "operation_id": "operation-1",
        }
        status, body = self.endpoint.execute(
            "/api/garmin/full-resync", {"confirm": "FULL_RESYNC"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(body["operation_id"], "operation-1")
        self.full_resync.start.assert_called_once_with("garmin", "operation-1")
        self.full_resync.resync.assert_not_called()

    def test_a_repeated_full_resync_request_is_not_accepted_as_a_new_run(self):
        self.full_resync.start.return_value = {
            "status": "already_running",
            "source": "wahoo",
            "operation_id": "operation-0",
        }
        status, body = self.endpoint.execute(
            "/api/wahoo/full-resync", {"confirm": "FULL_RESYNC"}
        )
        self.assertEqual((status, body["status"]), (200, "already_running"))

    def test_confirmation_bound_requests_start_nothing_without_it(self):
        with self.assertRaises(AppError) as raised:
            self.endpoint.execute("/api/garmin/full-resync", {})
        self.assertEqual(raised.exception.status, 400)
        self.full_resync.start.assert_not_called()
        # Only the Coach card exports nutrition, never this route (#2137).
        day = {"date": "2026-09-24", "total_kcal": 2000}
        cases = [
            ("nutrition_sync", {"date": "2026-09-24"}),
            ("nutrition_sync", {"pending_limit": 3}),
            ("nutrition_sync", {}),
            ("nutrition_sync", None),
            # A client can compute a manifest itself; it proves no approval.
            ("nutrition_sync", {"approval_manifest": [nutrition_approval_item(day)]}),
            # The queue normalizes the type, so the route must as well.
            ("Nutrition_Sync", {"pending_limit": 3}),
            (" NUTRITION_SYNC ", {"date": "2026-09-24"}),
        ]
        for job_type, payload in cases:
            with (
                self.subTest(job_type=job_type, payload=payload),
                self.assertRaises(AppError) as raised,
            ):
                self.endpoint.execute(
                    "/api/sync/jobs",
                    {"provider": "intervals", "type": job_type}
                    | ({} if payload is None else {"payload": payload}),
                )
            self.assertEqual(raised.exception.status, 400)
        self.queue.enqueue.assert_not_called()

    def test_job_request_keeps_requested_by_and_status(self):
        self.queue.enqueue.return_value = {"id": "job-2"}
        self.assertEqual(
            self.endpoint.execute(
                "/api/sync/jobs", {"provider": "weather", "force": True}
            ),
            (202, {"id": "job-2"}),
        )
        self.queue.enqueue.assert_called_once_with(
            "weather",
            "refresh",
            {"force": True},
            requested_by="user",
            item_operations=None,
        )

    def test_a_ui_plan_push_stores_one_job_item_per_entry(self):
        first, second = "a" * 8 + "-" + "0" * 27, "b" * 8 + "-" + "0" * 27
        entries = [
            {"library_workout_id": first, "expected_payload_hash": "1" * 64},
            {"library_workout_id": second, "expected_payload_hash": "2" * 64},
            {"library_workout_id": first, "expected_payload_hash": "1" * 64},
        ]
        self.queue.enqueue.return_value = {"id": "job-3"}
        self.endpoint.execute(
            "/api/sync/jobs",
            {"provider": "wahoo", "type": "plan_push", "payload": {"entries": entries}},
        )
        operations = self.queue.enqueue.call_args.kwargs["item_operations"]
        self.assertEqual(
            operations,
            [
                {"item_key": first, "operation": "plan_push", "payload_hash": "1" * 64},
                {
                    "item_key": second,
                    "operation": "plan_push",
                    "payload_hash": "2" * 64,
                },
            ],
        )

    def test_route_table_is_derived_once_not_per_request(self):
        with patch.object(sync_commands, "_build_path_routes") as build:
            for _ in range(5):
                self.assertTrue(SyncCommandEndpoint.handles("/api/garmin/sync"))
                self.assertTrue(SyncCommandEndpoint.needs_body("/api/garmin/sync"))
                SyncCommandEndpoint(
                    self.queue,
                    self.state,
                    self.full_resync,
                    lambda: "operation-1",
                    {"intervals": 90, "garmin": 30},
                    -1,
                    provider_configured=lambda provider: True,
                )
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
