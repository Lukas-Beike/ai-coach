"""Focused contracts for structured provider refresh commands.

Refresh-command tests should inject/patch the queue and Intervals services here.
The previous orchestration lived in ``server._start_structured_provider_refresh``,
``server._run_structured_intervals_refresh``,
``server._retry_structured_intervals_refresh`` and
``server._queue_structured_performance_refresh``; these helpers had no direct
test patches. Existing integration tests patch
``backend.sync.intervals.IntervalsSyncService.sync`` and read queued state via
``server.SYNC_JOB_QUEUE.service()``. New unit tests replace those composition
lookups with injected service doubles. The Coach caller appends a queued
result's ``sync_job_id`` to its turn-local list.
"""

import threading
import unittest
from datetime import date
from unittest.mock import Mock

from backend.errors import AppError
from backend.sync.commands import (
    GarminSynchronousRefresh,
    ProviderRefreshCommandService,
)


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
            self.service.start("intervals", {"days": 30, "_wait_for_completion": True})

        self.assertEqual(error.exception.status, 503)
        self.assertEqual(error.exception.reason, "provider_busy")
        self.intervals.sync.assert_called_once()

    def test_busy_response_after_retry_uses_existing_provider_busy_error(self):
        self.intervals.sync.side_effect = [
            {"status": "ok", "waited_for_existing": True, "activity_days": 3},
            {"status": "already_running"},
        ]

        with self.assertRaises(AppError) as error:
            self.service.start("intervals", {"days": 30, "_wait_for_completion": True})

        self.assertEqual(error.exception.status, 503)
        self.assertEqual(error.exception.reason, "provider_busy")

    def test_rejects_invalid_or_oversized_sync_windows_before_provider_call(self):
        for arguments in (
            {"days": "bad", "_wait_for_completion": True},
            {"days": 366, "_wait_for_completion": True},
            {"days": 3661, "_wait_for_completion": True},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(AppError) as error:
                    self.service.start("intervals", arguments)
                self.assertEqual(error.exception.reason, "invalid_refresh_request")
        self.intervals.sync.assert_not_called()

    def test_waiting_refresh_without_days_uses_the_stored_sync_period(self):
        self.intervals.sync_period.return_value = 90
        self.intervals.sync.return_value = {"status": "ok", "activity_days": 90}

        result = self.service.start("intervals", {"_wait_for_completion": True})

        self.assertEqual(result["activity_days"], 90)
        self.assertEqual(self.intervals.sync.call_args.kwargs["activity_days"], 90)

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


class GarminSynchronousRefreshTests(unittest.TestCase):
    def setUp(self):
        self.garmin = Mock()
        self.battery = Mock()
        self.garmin.automatic_sync_window.return_value = (3, date(2026, 10, 10))
        self.garmin.sync.return_value = {"status": "ok"}
        self.garmin.awaited_run_status.return_value = None
        self.refresh = GarminSynchronousRefresh(
            self.garmin, self.battery, all_sync_days=-1
        )

    def test_uses_scheduled_catch_up_window_without_requested_days(self):
        cancel_event = threading.Event()

        result = self.refresh.refresh(
            "garmin", {"_wait_for_completion": True}, cancel_event
        )

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "completed",
                "provider": "garmin",
                "activity_days": 3,
                "partial": False,
                "history_limited": False,
                "synchronous_refresh": True,
            },
        )
        self.garmin.sync.assert_called_once_with(
            days=3,
            reason="Chat-Anfrage",
            end_date=date(2026, 10, 10),
            wait_for_existing=True,
            cancel_event=cancel_event,
            include_recovery=True,
        )
        self.battery.refresh.assert_called_once_with()

    def test_all_history_sentinel_uses_scheduled_catch_up_window(self):
        result = self.refresh.refresh("garmin", {"days": -1}, None)

        self.assertEqual(result["activity_days"], 3)
        self.assertTrue(result["history_limited"])
        self.garmin.automatic_sync_window.assert_called_once()
        self.assertEqual(
            self.garmin.sync.call_args.kwargs["end_date"], date(2026, 10, 10)
        )

    def test_honors_requested_days_ending_today(self):
        result = self.refresh.refresh(
            "garmin", {"days": "30", "_wait_for_completion": True}, None
        )

        self.assertEqual(result["activity_days"], 30)
        self.assertFalse(result["history_limited"])
        self.garmin.automatic_sync_window.assert_not_called()
        self.garmin.sync.assert_called_once_with(
            days=30,
            reason="Chat-Anfrage",
            end_date=None,
            wait_for_existing=True,
            cancel_event=None,
            include_recovery=True,
        )

    def test_rejects_invalid_or_oversized_days_before_provider_call(self):
        for days in ("bad", 0, -2, 91, 3661):
            with self.subTest(days=days):
                with self.assertRaises(AppError) as error:
                    self.refresh.refresh("garmin", {"days": days}, None)
                self.assertEqual(error.exception.reason, "invalid_refresh_request")
        self.garmin.sync.assert_not_called()

    def test_runs_own_sync_after_waiting_for_another_run(self):
        self.garmin.sync.side_effect = [
            {"status": "ok", "waited_for_existing": True},
            {"status": "partial"},
        ]

        result = self.refresh.refresh("garmin", {"days": 30}, None)

        self.assertEqual(self.garmin.sync.call_count, 2)
        self.assertTrue(self.garmin.sync.call_args_list[0].kwargs["wait_for_existing"])
        self.assertFalse(self.garmin.sync.call_args_list[1].kwargs["wait_for_existing"])
        self.assertTrue(result["partial"])
        self.garmin.awaited_run_status.assert_called_once_with(30, None, None)
        self.battery.refresh.assert_called_once_with()

    def test_awaited_run_covering_the_window_is_not_repeated(self):
        self.garmin.awaited_run_status.return_value = "ok"
        self.garmin.sync.return_value = {
            "status": "ok",
            "waited_for_existing": True,
            "synced_at": "2026-10-10T06:00:00+00:00",
        }

        result = self.refresh.refresh("garmin", {"days": 30}, None)

        self.garmin.sync.assert_called_once()
        self.garmin.awaited_run_status.assert_called_once_with(
            30, None, "2026-10-10T06:00:00+00:00"
        )
        self.assertFalse(result["partial"])
        self.battery.refresh.assert_called_once_with()

    def test_awaited_run_with_failed_collection_is_reported_partial(self):
        self.garmin.awaited_run_status.return_value = "partial"
        self.garmin.sync.return_value = {"status": "ok", "waited_for_existing": True}

        result = self.refresh.refresh("garmin", {"days": 30}, None)

        self.garmin.sync.assert_called_once()
        self.assertTrue(result["partial"])
        self.battery.refresh.assert_called_once_with()

    def test_busy_rerun_after_waiting_keeps_awaited_data_as_partial(self):
        self.garmin.sync.side_effect = [
            {"status": "ok", "waited_for_existing": True},
            {"status": "already_running"},
        ]

        result = self.refresh.refresh("garmin", {}, None)

        self.assertTrue(result["partial"])
        self.battery.refresh.assert_called_once_with()

    def test_partial_sync_is_reported_and_still_refreshes_body_battery(self):
        self.garmin.sync.return_value = {"status": "partial"}

        result = self.refresh.refresh("garmin", {}, None)

        self.assertTrue(result["partial"])
        self.assertEqual(result["status"], "completed")
        self.battery.refresh.assert_called_once_with()

    def test_busy_sync_uses_existing_provider_busy_error(self):
        self.garmin.sync.return_value = {"status": "already_running"}

        with self.assertRaises(AppError) as error:
            self.refresh.refresh("garmin", {}, None)

        self.assertEqual(error.exception.status, 503)
        self.assertEqual(error.exception.reason, "provider_busy")
        self.assertIn("Garmin", str(error.exception))
        self.assertNotIn("garmin-", str(error.exception))
        self.battery.refresh.assert_not_called()

    def test_unrecognized_sync_status_fails_without_body_battery_refresh(self):
        self.garmin.sync.return_value = {"status": "cancelled"}

        with self.assertRaises(AppError) as error:
            self.refresh.refresh("garmin", {}, None)

        self.assertEqual(error.exception.status, 503)
        self.assertEqual(error.exception.reason, "provider_refresh_failed")
        self.battery.refresh.assert_not_called()

    def test_sync_failure_propagates_without_body_battery_refresh(self):
        self.garmin.sync.side_effect = AppError(503, "Garmin down")

        with self.assertRaises(AppError):
            self.refresh.refresh("garmin", {}, None)

        self.battery.refresh.assert_not_called()

    def test_command_service_waits_through_registered_garmin_refresh(self):
        queue = Mock()
        service = ProviderRefreshCommandService(
            queue,
            Mock(),
            all_sync_days=-1,
            synchronous_refreshes={"garmin": self.refresh},
        )

        result = service.start("garmin", {"_wait_for_completion": True})

        self.assertEqual(result["status"], "completed")
        queue.enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
