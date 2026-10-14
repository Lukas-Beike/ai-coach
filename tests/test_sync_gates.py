"""Concurrency tests for provider resynchronization gates."""

from __future__ import annotations

import threading
import unittest

from provider_runtime_fakes import ACME_ID

from backend.errors import AppError
from backend.providers.descriptors import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.sync.gates import (
    GARMIN_RESYNC_GATE,
    INTERVALS_RESYNC_GATE,
    WAHOO_RESYNC_GATE,
    ProviderResyncGate,
    resync_gate,
)


class ResyncGateMappingTests(unittest.TestCase):
    def test_default_mapping_selects_each_provider_gate(self) -> None:
        self.assertIs(resync_gate(INTERVALS_ID), INTERVALS_RESYNC_GATE)
        self.assertIs(resync_gate(GARMIN_ID), GARMIN_RESYNC_GATE)
        self.assertIs(resync_gate(WAHOO_ID), WAHOO_RESYNC_GATE)

    def test_unmapped_provider_is_rejected_instead_of_falling_back(self) -> None:
        with self.assertRaises(AppError) as raised:
            resync_gate(ACME_ID)
        self.assertEqual(400, raised.exception.status)
        with self.assertRaises(AppError) as raised:
            resync_gate(INTERVALS_ID, {})
        self.assertEqual(400, raised.exception.status)

    def test_injected_mapping_replaces_defaults(self) -> None:
        acme_gate = ProviderResyncGate("Acme mock")
        gates = {ACME_ID: acme_gate}

        self.assertIs(resync_gate(ACME_ID, gates), acme_gate)
        with self.assertRaises(AppError):
            resync_gate(INTERVALS_ID, gates)


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

    def test_reset_inside_own_operation_fails_fast_instead_of_deadlocking(self) -> None:
        gate = ProviderResyncGate("Synthetic")
        with gate.operation():
            with self.assertRaisesRegex(RuntimeError, "inside a provider operation"):
                gate.begin_reset()
            self.assertFalse(gate.is_resetting())
        self.assertEqual(gate.active, 0)
        self.assertTrue(gate.begin_reset())
        gate.end_reset()

    def test_operation_cleanup_runs_after_exception(self) -> None:
        gate = ProviderResyncGate("Synthetic")
        with self.assertRaisesRegex(RuntimeError, "boom"), gate.operation():
            raise RuntimeError("boom")
        self.assertEqual(gate.active, 0)
        self.assertTrue(gate.begin_reset())
        gate.end_reset()


if __name__ == "__main__":
    unittest.main()
