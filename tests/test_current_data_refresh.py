"""An explicit current-data request refreshes Garmin and Wahoo and waits for both.

Intervals.icu is output only: no refresh is queued or run for it, and no
Intervals.icu read endpoint is called.
"""

import threading
import unittest
from unittest.mock import MagicMock, Mock

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.errors import AppError
from backend.sync.commands import (
    GarminSynchronousRefresh,
    ProviderRefreshCommandService,
    SynchronousRefresh,
    WahooSynchronousRefresh,
)
from backend.sync.jobs import JobValidationError, normalize_sync_job_request
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY


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
        WAHOO_ID: WahooSynchronousRefresh(wahoo_sync, -1),
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

    def test_the_wahoo_read_waits_for_a_running_sync_on_the_lock_itself(self) -> None:
        garmin_sync, wahoo_sync, intervals_client = Mock(), Mock(), Mock()
        service, _queue = _command_service(garmin_sync, wahoo_sync, intervals_client)

        result = service.start(WAHOO_ID, {"_wait_for_completion": True})

        self.assertEqual("completed", result["status"])
        # One call that waits inside the sync: no running() poll, no gap in between.
        wahoo_sync.running.assert_not_called()
        wahoo_sync.sync.assert_called_once_with(
            7, "Chat-Anfrage", wait_seconds=120.0, cancel_event=None
        )

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

    def test_a_cancelled_request_never_starts_a_wahoo_read(self) -> None:
        for held in (False, True):
            with self.subTest(lock_held=held):
                garmin_sync, wahoo_sync, intervals_client = Mock(), Mock(), Mock()
                service, _queue = _command_service(
                    garmin_sync, wahoo_sync, intervals_client
                )
                wahoo_sync.running.return_value = held
                cancelled = threading.Event()
                cancelled.set()

                with self.assertRaises(AppError) as raised:
                    service.start(
                        WAHOO_ID, {"_wait_for_completion": True}, cancel_event=cancelled
                    )

                self.assertEqual("chat_cancelled", raised.exception.reason)
                self.assertEqual(499, raised.exception.status)
                wahoo_sync.sync.assert_not_called()

    def test_the_wahoo_window_is_short_and_bounded_by_the_stored_period(self) -> None:
        cases = (
            (None, 84, 7),
            (-1, 84, 7),
            (30, 84, 30),
            (30, 14, 14),
            (None, 3, 3),
            (-1, -1, 7),
        )
        for requested, stored, expected in cases:
            with self.subTest(requested=requested, stored=stored):
                wahoo_sync = Mock()
                wahoo_sync.running.return_value = False
                wahoo_sync.sync.return_value = {"status": "ok"}
                refresh = WahooSynchronousRefresh(
                    wahoo_sync,
                    -1,
                    stored_days=Mock(return_value=stored),
                )
                arguments = {} if requested is None else {"days": requested}

                refresh.refresh(WAHOO_ID, arguments, None)

                wahoo_sync.sync.assert_called_once_with(
                    expected, "Chat-Anfrage", wait_seconds=120.0, cancel_event=None
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
