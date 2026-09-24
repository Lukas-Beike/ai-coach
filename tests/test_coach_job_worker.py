"""Direct lifecycle and maintenance contracts for the durable Coach worker."""

from __future__ import annotations

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
            self.worker.start(lambda: self.jobs, lambda: self.runner, self.gate)
            self.worker.start(lambda: self.jobs, lambda: self.runner, self.gate)

        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["name"], "coach-job-worker")
        self.assertTrue(thread.call_args.kwargs["daemon"])
        self.assertEqual(thread.call_args.kwargs["target"], self.worker.run_forever)
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
        self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate)

        self.jobs.claim.assert_called_once_with()
        self.runner.run.assert_called_once_with(job)
        self.assertEqual(self.gate.state()["running_operations"], 0)

    def test_maintenance_rejection_does_not_claim_and_wakes_for_shutdown(self) -> None:
        self.worker.wake_event.wait = Mock(side_effect=lambda seconds: self.worker.stop())
        with self.gate.restore():
            self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate)

        self.jobs.claim.assert_not_called()
        self.worker.wake_event.wait.assert_called_once_with(5)

    def test_nonmaintenance_claim_error_propagates(self) -> None:
        self.jobs.claim.side_effect = AppError(500, "synthetic", reason="claim_failed")

        with self.assertRaises(AppError) as caught:
            self.worker.run_forever(lambda: self.jobs, lambda: self.runner, self.gate)

        self.assertEqual(caught.exception.reason, "claim_failed")
        self.runner.run.assert_not_called()
        self.assertEqual(self.gate.state()["running_operations"], 0)


if __name__ == "__main__":
    unittest.main()
