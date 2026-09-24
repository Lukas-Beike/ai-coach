"""Focused contracts for structured provider refresh commands.

Refresh-command tests should inject/patch the queue and Intervals services here.
The previous orchestration lived in ``server._start_structured_provider_refresh``,
``server._run_structured_intervals_refresh``,
``server._retry_structured_intervals_refresh`` and
``server._queue_structured_performance_refresh``; these helpers had no direct
test patches. Existing integration tests patch
``backend.sync.intervals.IntervalsSyncService.sync`` and read queued state via
``server.sync_job_queue_service()``. New unit tests replace those composition
lookups with injected service doubles. The Coach caller appends a queued
result's ``sync_job_id`` to its turn-local list.
"""

import threading
import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.sync.commands import ProviderRefreshCommandService


class ProviderRefreshCommandServiceTests(unittest.TestCase):
    def setUp(self):
        self.queue = Mock()
        self.intervals = Mock()
        self.queue.enqueue.return_value = {"id": "job-123"}
        self.service = ProviderRefreshCommandService(
            self.queue, self.intervals, all_sync_days=-1
        )

    def test_queues_provider_refresh_without_persisting_internal_wait_flag(self):
        arguments = {"days": 7, "_wait_for_completion": False}

        result = self.service.start("garmin", arguments)

        self.assertEqual(
            result, {"ok": True, "status": "queued", "sync_job_id": "job-123"}
        )
        self.queue.enqueue.assert_called_once_with(
            "garmin", "refresh", {"days": 7}, requested_by="coach"
        )
        self.assertEqual(arguments["_wait_for_completion"], False)
        self.intervals.sync.assert_not_called()

    def test_synchronous_refresh_preserves_window_wait_performance_and_cancel(self):
        cancel_event = threading.Event()
        self.intervals.sync.return_value = {"status": "ok", "activity_days": 30}

        result = self.service.start(
            "intervals",
            {"days": "30", "_wait_for_completion": True},
            cancel_event=cancel_event,
        )

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "completed",
                "provider": "intervals",
                "activity_days": 30,
                "synchronous_refresh": True,
            },
        )
        self.intervals.sync.assert_called_once_with(
            "Chat-Anfrage",
            activity_days=30,
            wait_for_existing=True,
            wait_for_performance=True,
            cancel_event=cancel_event,
        )

    def test_retries_when_existing_sync_did_not_cover_requested_window(self):
        cancel_event = threading.Event()
        self.intervals.sync.side_effect = [
            {"status": "ok", "waited_for_existing": True, "activity_days": 3},
            {"status": "ok", "activity_days": 365},
        ]

        result = self.service.start(
            "intervals",
            {"days": 365, "_wait_for_completion": True},
            cancel_event=cancel_event,
        )

        self.assertEqual(result["activity_days"], 365)
        self.assertEqual(self.intervals.sync.call_count, 2)
        self.assertEqual(
            self.intervals.sync.call_args_list[0].kwargs,
            {
                "activity_days": 365,
                "wait_for_existing": True,
                "wait_for_performance": True,
                "cancel_event": cancel_event,
            },
        )
        self.assertEqual(
            self.intervals.sync.call_args_list[1].kwargs,
            {
                "activity_days": 365,
                "wait_for_existing": False,
                "cancel_event": cancel_event,
            },
        )

    def test_all_time_window_is_preserved_when_waiting_for_existing_sync(self):
        self.intervals.sync.return_value = {
            "status": "ok",
            "waited_for_existing": True,
            "activity_days": -1,
        }

        result = self.service.start(
            "intervals", {"days": -1, "_wait_for_completion": True}
        )

        self.assertEqual(result["activity_days"], -1)
        self.intervals.sync.assert_called_once_with(
            "Chat-Anfrage",
            activity_days=-1,
            wait_for_existing=True,
            wait_for_performance=True,
        )

    def test_busy_initial_sync_uses_existing_provider_busy_error(self):
        self.intervals.sync.return_value = {"status": "already_running"}

        with self.assertRaises(AppError) as error:
            self.service.start(
                "intervals", {"days": 30, "_wait_for_completion": True}
            )

        self.assertEqual(error.exception.status, 503)
        self.assertEqual(error.exception.reason, "provider_busy")
        self.intervals.sync.assert_called_once()

    def test_busy_response_after_retry_uses_existing_provider_busy_error(self):
        self.intervals.sync.side_effect = [
            {"status": "ok", "waited_for_existing": True, "activity_days": 3},
            {"status": "already_running"},
        ]

        with self.assertRaises(AppError) as error:
            self.service.start(
                "intervals", {"days": 30, "_wait_for_completion": True}
            )

        self.assertEqual(error.exception.status, 503)
        self.assertEqual(error.exception.reason, "provider_busy")

    def test_rejects_invalid_or_oversized_sync_windows_before_provider_call(self):
        for arguments in (
            {"days": "bad", "_wait_for_completion": True},
            {"days": 3661, "_wait_for_completion": True},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(AppError) as error:
                    self.service.start("intervals", arguments)
                self.assertEqual(error.exception.reason, "invalid_refresh_request")
        self.intervals.sync.assert_not_called()

    def test_sync_refresh_for_other_provider_is_rejected(self):
        with self.assertRaises(AppError) as error:
            self.service.start("garmin", {"_wait_for_completion": True})

        self.assertEqual(error.exception.status, 400)
        self.assertEqual(error.exception.reason, "invalid_refresh_request")
        self.intervals.sync.assert_not_called()

    def test_queues_performance_refresh_as_coach_and_returns_job_id(self):
        result = self.service.queue_performance_refresh({"reason": "fresh data"})

        self.assertEqual(
            result, {"ok": True, "status": "queued", "sync_job_id": "job-123"}
        )
        self.queue.enqueue.assert_called_once_with(
            "intervals",
            "performance_refresh",
            {"reason": "fresh data"},
            requested_by="coach",
        )


if __name__ == "__main__":
    unittest.main()
