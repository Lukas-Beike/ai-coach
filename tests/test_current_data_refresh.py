"""An explicit current-data request refreshes Garmin and Wahoo and waits for both.

Intervals.icu is output only: no refresh is queued or run for it, and no
Intervals.icu read endpoint is called.
"""

import threading
import unittest
from unittest.mock import MagicMock, Mock

from backend.errors import AppError
from backend.providers.descriptors import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.sync.commands import (
    GarminSynchronousRefresh,
    ProviderRefreshCommandService,
    WahooSynchronousRefresh,
)
from backend.sync.jobs import JobValidationError, normalize_sync_job_request
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_runtime import SynchronousRefresh


def _command_service(
    garmin_sync: Mock, wahoo_sync: Mock, intervals_client: Mock
) -> tuple[ProviderRefreshCommandService, Mock]:
    queue = Mock()
    garmin_sync.automatic_sync_window.return_value = (2, None)
    garmin_sync.sync.return_value = {"status": "ok"}
    garmin_sync.awaited_run_status.return_value = None
    wahoo_sync.running.return_value = False
    wahoo_sync.sync.return_value = {"status": "ok"}
    refreshes: dict[str, SynchronousRefresh] = {
        GARMIN_ID: GarminSynchronousRefresh(garmin_sync, MagicMock(), -1),
        WAHOO_ID: WahooSynchronousRefresh(wahoo_sync, -1, poll_seconds=0.001),
    }
    # The refresh owners never receive an Intervals.icu client.
    del intervals_client
    return ProviderRefreshCommandService(queue, refreshes), queue


class CurrentDataRefreshTests(unittest.TestCase):
    def test_garmin_and_wahoo_are_waiting_coach_targets_and_intervals_is_not(
        self,
    ) -> None:
        registry = DEFAULT_PROVIDER_REGISTRY
        targets = registry.coach_refresh_targets()

        self.assertIn(GARMIN_ID, targets)
        self.assertIn(WAHOO_ID, targets)
        self.assertNotIn(INTERVALS_ID, targets)
        self.assertTrue(registry.get(GARMIN_ID).coach_waits_for_completion)
        self.assertTrue(registry.get(WAHOO_ID).coach_waits_for_completion)
        self.assertFalse(registry.get(INTERVALS_ID).coach_waits_for_completion)

    def test_waiting_requests_run_both_refreshes_inline_without_intervals(
        self,
    ) -> None:
        garmin_sync, wahoo_sync, intervals_client = Mock(), Mock(), Mock()
        service, queue = _command_service(garmin_sync, wahoo_sync, intervals_client)

        garmin = service.start(GARMIN_ID, {"_wait_for_completion": True})
        wahoo = service.start(WAHOO_ID, {"_wait_for_completion": True})

        self.assertEqual("completed", garmin["status"])
        self.assertEqual("completed", wahoo["status"])
        self.assertTrue(garmin["synchronous_refresh"])
        self.assertTrue(wahoo["synchronous_refresh"])
        garmin_sync.sync.assert_called_once()
        wahoo_sync.sync.assert_called_once()
        queue.enqueue.assert_not_called()
        self.assertEqual([], intervals_client.method_calls)

    def test_a_running_wahoo_sync_is_awaited_before_the_refresh_reads(self) -> None:
        garmin_sync, wahoo_sync, intervals_client = Mock(), Mock(), Mock()
        service, _queue = _command_service(garmin_sync, wahoo_sync, intervals_client)
        wahoo_sync.running.side_effect = [True, True, False]

        result = service.start(WAHOO_ID, {"_wait_for_completion": True})

        self.assertEqual("completed", result["status"])
        self.assertEqual(3, wahoo_sync.running.call_count)
        wahoo_sync.sync.assert_called_once_with(None, "Chat-Anfrage")

    def test_a_partial_or_busy_wahoo_read_is_reported_honestly(self) -> None:
        garmin_sync, wahoo_sync, intervals_client = Mock(), Mock(), Mock()
        service, _queue = _command_service(garmin_sync, wahoo_sync, intervals_client)

        wahoo_sync.sync.return_value = {"status": "partial"}
        partial = service.start(WAHOO_ID, {"_wait_for_completion": True})
        self.assertTrue(partial["partial"])

        wahoo_sync.sync.return_value = {"status": "already_running"}
        with self.assertRaises(AppError) as busy:
            service.start(WAHOO_ID, {"_wait_for_completion": True})
        self.assertEqual("provider_busy", busy.exception.reason)

        wahoo_sync.sync.return_value = {"status": "not_configured", "message": "x"}
        with self.assertRaises(AppError) as missing:
            service.start(WAHOO_ID, {"_wait_for_completion": True})
        self.assertEqual("not_configured", missing.exception.reason)

    def test_a_cancelled_wait_stops_before_the_wahoo_read_is_blocked_forever(
        self,
    ) -> None:
        garmin_sync, wahoo_sync, intervals_client = Mock(), Mock(), Mock()
        service, _queue = _command_service(garmin_sync, wahoo_sync, intervals_client)
        wahoo_sync.running.return_value = True
        wahoo_sync.sync.return_value = {"status": "already_running"}
        cancelled = threading.Event()
        cancelled.set()

        with self.assertRaises(AppError):
            service.start(
                WAHOO_ID, {"_wait_for_completion": True}, cancel_event=cancelled
            )

    def test_intervals_has_no_refresh_to_wait_for_or_queue(self) -> None:
        garmin_sync, wahoo_sync, intervals_client = Mock(), Mock(), Mock()
        service, queue = _command_service(garmin_sync, wahoo_sync, intervals_client)

        with self.assertRaises(AppError) as waiting:
            service.start(INTERVALS_ID, {"_wait_for_completion": True})
        self.assertEqual("invalid_refresh_request", waiting.exception.reason)

        for job_type in (
            "refresh",
            "performance_refresh",
            "activity_details",
            "historical_backfill",
        ):
            with self.subTest(job_type=job_type), self.assertRaises(JobValidationError):
                normalize_sync_job_request(
                    INTERVALS_ID,
                    job_type,
                    {"activity_id": "i1"},
                    all_sync_days=-1,
                )
        queue.enqueue.assert_not_called()
        self.assertEqual([], intervals_client.method_calls)


if __name__ == "__main__":
    unittest.main()
