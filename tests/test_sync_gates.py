"""Concurrency tests for provider resynchronization gates."""

from __future__ import annotations

import threading
import unittest

from backend.errors import AppError
from backend.sync.gates import ProviderResyncGate


class ProviderResyncGateTests(unittest.TestCase):
    def test_reset_waits_for_active_operation_and_blocks_new_threads(self) -> None:
        gate = ProviderResyncGate("Synthetic")
        operation_entered = threading.Event()
        release_operation = threading.Event()
        reset_started = threading.Event()
        reset_acquired = threading.Event()
        errors: list[AppError] = []

        def operate() -> None:
            with gate.operation():
                operation_entered.set()
                release_operation.wait(2)

        def reset() -> None:
            reset_started.set()
            if gate.begin_reset():
                reset_acquired.set()

        operation_thread = threading.Thread(target=operate)
        reset_thread = threading.Thread(target=reset)
        operation_thread.start()
        self.assertTrue(operation_entered.wait(2))
        reset_thread.start()
        self.assertTrue(reset_started.wait(2))
        with gate.condition:
            self.assertTrue(gate.condition.wait_for(lambda: gate.resetting, timeout=2))
        self.assertFalse(reset_acquired.wait(0.05))
        with self.assertRaises(AppError) as raised, gate.operation():
            pass
        errors.append(raised.exception)
        self.assertEqual(errors[0].status, 409)

        release_operation.set()
        operation_thread.join(2)
        reset_thread.join(2)
        self.assertTrue(reset_acquired.is_set())
        self.assertTrue(gate.is_resetting())
        gate.end_reset()
        self.assertFalse(gate.is_resetting())

    def test_reset_owner_may_run_nested_operation(self) -> None:
        gate = ProviderResyncGate("Synthetic")
        self.assertTrue(gate.begin_reset())
        try:
            with gate.operation():
                self.assertEqual(gate.active, 0)
            self.assertFalse(gate.begin_reset())
        finally:
            gate.end_reset()
        self.assertEqual(gate.active, 0)

    def test_operation_cleanup_runs_after_exception(self) -> None:
        gate = ProviderResyncGate("Synthetic")
        with self.assertRaisesRegex(RuntimeError, "boom"), gate.operation():
            raise RuntimeError("boom")
        self.assertEqual(gate.active, 0)
        self.assertTrue(gate.begin_reset())
        gate.end_reset()


if __name__ == "__main__":
    unittest.main()
