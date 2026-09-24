import logging
import threading
import time
import unittest
from unittest.mock import Mock, call

from backend.errors import AppError
from backend.sync.scheduler import DailySyncLoop


class StopLoop(BaseException):
    pass


class LimitedSleeper:
    def __init__(self, iterations):
        self.iterations = iterations
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)
        if len(self.calls) > self.iterations:
            raise StopLoop


class DailySyncLoopTests(unittest.TestCase):
    def make_loop(self, scheduler, morning, iterations=1):
        sleeper = LimitedSleeper(iterations)
        logger = Mock(spec=logging.Logger)
        return DailySyncLoop(
            scheduler,
            morning,
            sleep=sleeper,
            logger=logger,
        ), sleeper, logger

    def test_sleeps_before_scheduling_then_refreshes_each_iteration(self):
        events = []

        class Scheduler:
            def schedule(self):
                events.append("schedule")

        class MorningBattery:
            def refresh(self):
                events.append("refresh")

        sleeper = LimitedSleeper(2)

        def record_sleep(seconds):
            events.append("sleep")
            sleeper(seconds)

        logger = Mock(spec=logging.Logger)
        loop = DailySyncLoop(
            Scheduler(), MorningBattery(), sleep=record_sleep, logger=logger
        )
        with self.assertRaises(StopLoop):
            loop.run()

        self.assertEqual(events, ["sleep", "schedule", "refresh", "sleep", "schedule", "refresh", "sleep"])
        self.assertEqual(sleeper.calls, [300, 300, 300])

    def test_maintenance_error_skips_morning_refresh_and_continues(self):
        scheduler = Mock()
        scheduler.schedule.side_effect = [
            AppError(503, "maintenance", reason="maintenance"),
            None,
        ]
        morning = Mock()
        loop, sleeper, logger = self.make_loop(scheduler, morning, iterations=2)

        with self.assertRaises(StopLoop):
            loop.run()

        self.assertEqual(sleeper.calls, [300, 300, 300])
        scheduler.schedule.assert_has_calls([call(), call()])
        morning.refresh.assert_called_once_with()
        logger.error.assert_not_called()

    def test_other_app_error_logs_once_and_continues(self):
        scheduler = Mock()
        scheduler.schedule.side_effect = [
            AppError(503, "failed", reason="provider_error"),
            None,
        ]
        morning = Mock()
        loop, sleeper, logger = self.make_loop(scheduler, morning, iterations=2)

        with self.assertRaises(StopLoop):
            loop.run()

        self.assertEqual(sleeper.calls, [300, 300, 300])
        morning.refresh.assert_called_once_with()
        logger.error.assert_called_once_with(
            "Automatic synchronization scheduling failed",
            extra={"event": "daily_sync_failed"},
        )

    def test_unexpected_exception_propagates(self):
        scheduler = Mock()
        scheduler.schedule.side_effect = RuntimeError("unexpected")
        morning = Mock()
        loop, sleeper, logger = self.make_loop(scheduler, morning)

        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            loop.run()

        self.assertEqual(sleeper.calls, [300])
        morning.refresh.assert_not_called()
        logger.error.assert_not_called()

    def test_stop_interrupts_wait_without_scheduling_another_refresh(self):
        scheduler = Mock()
        morning = Mock()
        stop_event = threading.Event()
        loop = DailySyncLoop(
            scheduler,
            morning,
            sleep=time.sleep,
            logger=Mock(spec=logging.Logger),
            stop_event=stop_event,
        )
        thread = threading.Thread(target=loop.run)
        thread.start()
        loop.stop()
        thread.join(1)

        self.assertFalse(thread.is_alive())
        scheduler.schedule.assert_not_called()
        morning.refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
