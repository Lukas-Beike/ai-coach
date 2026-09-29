"""Direct lifecycle and maintenance contracts for the durable Coach worker."""

from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import Mock, patch

from backend.coach.job_worker import CoachJobWorker
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate


class CoachJobWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = CoachJobWorker()
        self.gate = MaintenanceGate()
        self.jobs = Mock()
        self.runner = Mock()

    def test_start_uses_one_daemon_and_does_not_repeat_while_alive(self) -> None:
        with patch("backend.coach.job_worker.threading.Thread") as thread:
            thread.return_value.is_alive.return_value = True
            self.worker.start(lambda: self.jobs, lambda: self.runner, self.gate, Mock())
            self.worker.start(lambda: self.jobs, lambda: self.runner, self.gate, Mock())

        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["name"], "coach-job-worker")
        self.assertTrue(thread.call_args.kwargs["daemon"])
        self.assertEqual(thread.call_args.kwargs["target"], self.worker.run_forever)
        self.assertEqual(len(thread.call_args.kwargs["args"]), 4)
        thread.return_value.start.assert_called_once_with()
        self.jobs.claim.assert_not_called()

    def test_claim_and_runner_share_outer_maintenance_operation(self) -> None:
        job = {"client_turn_id": "synthetic"}
        self.jobs.claim.return_value = job

        def execute(claimed):
            self.assertIs(claimed, job)
            self.assertEqual(self.gate.state()["running_operations"], 1)
            self.worker.stop()

        self.runner.run.side_effect = execute
        self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate, Mock())

        self.jobs.claim.assert_called_once_with()
        self.runner.run.assert_called_once_with(job)
        self.assertEqual(self.gate.state()["running_operations"], 0)

    def test_maintenance_rejection_does_not_claim_and_wakes_for_shutdown(self) -> None:
        self.worker.wake_event.wait = Mock(side_effect=lambda seconds: self.worker.stop())
        with self.gate.restore():
            self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate, Mock())

        self.jobs.claim.assert_not_called()
        self.worker.wake_event.wait.assert_called_once_with(5)

    def test_nonmaintenance_claim_error_does_not_kill_the_worker(self) -> None:
        self.jobs.claim.side_effect = [
            AppError(500, "synthetic", reason="claim_failed"),
            {"client_turn_id": "synthetic"},
        ]
        self.runner.run.side_effect = lambda _job: self.worker.stop()

        self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate, Mock())

        self.assertEqual(self.jobs.claim.call_count, 2)
        self.runner.run.assert_called_once()
        self.assertEqual(self.gate.state()["running_operations"], 0)

    def test_transient_claim_error_does_not_kill_worker_or_replay_job(self) -> None:
        job = {"client_turn_id": "synthetic"}
        self.jobs.claim.side_effect = [sqlite3.OperationalError("private detail"), job]
        self.runner.run.side_effect = lambda _job: self.worker.stop()

        with patch("backend.coach.job_worker._LOGGER.error") as log_error:
            self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate, Mock())

        self.assertEqual(self.jobs.claim.call_count, 2)
        self.runner.run.assert_called_once_with(job)
        self.assertEqual(log_error.call_args.kwargs["extra"]["error_class"], "OperationalError")
        self.assertNotIn("private detail", repr(log_error.call_args))

    def test_runner_error_leaves_claimed_job_unreplayed_and_worker_polling(self) -> None:
        job = {"client_turn_id": "synthetic"}
        self.jobs.claim.side_effect = [job, None]
        self.runner.run.side_effect = RuntimeError("private detail")
        recovery = Mock()
        waits = 0

        def wait_until_second_poll(_seconds):
            nonlocal waits
            waits += 1
            if waits == 2:
                self.worker.stop()

        self.worker.wake_event.wait = Mock(side_effect=wait_until_second_poll)

        with patch("backend.coach.job_worker._LOGGER.error") as log_error:
            self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate, recovery)

        self.assertEqual(self.jobs.claim.call_count, 2)
        self.runner.run.assert_called_once_with(job)
        recovery.assert_called_once_with()
        self.assertEqual(self.worker.wake_event.wait.call_args_list[0].args, (5,))
        self.assertEqual(log_error.call_args.kwargs["extra"]["error_class"], "RuntimeError")
        self.assertNotIn("private detail", repr(log_error.call_args))

    def test_stop_during_claim_recovery_wait_exits_without_reclaiming(self) -> None:
        self.jobs.claim.side_effect = sqlite3.OperationalError("private detail")
        self.worker.wake_event.wait = Mock(side_effect=lambda _seconds: self.worker.stop())

        self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate, Mock())

        self.jobs.claim.assert_called_once_with()
        self.runner.run.assert_not_called()
        self.worker.wake_event.wait.assert_called_once_with(5)

    def test_recovery_failure_is_retried_before_claiming_more_jobs(self) -> None:
        job = {"client_turn_id": "synthetic"}
        self.jobs.claim.side_effect = [job, None]
        self.runner.run.side_effect = RuntimeError("private detail")
        recovery = Mock(side_effect=[RuntimeError("database unavailable"), None])
        waits = 0

        def wait_until_recovery_completes(_seconds):
            nonlocal waits
            waits += 1
            if waits == 3:
                self.worker.stop()

        self.worker.wake_event.wait = Mock(side_effect=wait_until_recovery_completes)
        with patch("backend.coach.job_worker._LOGGER.error") as log_error:
            self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate, recovery)

        self.assertEqual(recovery.call_count, 2)
        self.assertEqual(self.jobs.claim.call_count, 2)
        self.assertEqual(log_error.call_args.kwargs["extra"]["event"], "coach_worker_recovery_failed")


if __name__ == "__main__":
    unittest.main()
