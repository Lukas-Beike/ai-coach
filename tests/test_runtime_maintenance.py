"""Deterministic tests for maintenance operation coordination."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from backend.errors import AppError
from backend.runtime import maintenance


class MaintenanceGateTests(unittest.TestCase):
    def test_recursive_operations_count_once_per_thread(self):
        gate = maintenance.MaintenanceGate()
        with gate.operation():
            self.assertEqual(gate.state(), {"active": False, "running_operations": 1})
            with gate.operation():
                self.assertEqual(gate.state(), {"active": False, "running_operations": 1})
        self.assertEqual(gate.state(), {"active": False, "running_operations": 0})

    def test_operation_rejects_stale_generation(self):
        gate = maintenance.MaintenanceGate()
        with gate.restore():
            generation = gate.current_generation()
        with self.assertRaisesRegex(AppError, "Datenlöschung") as caught, gate.operation(generation - 1):
            pass
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "operation_invalidated")

    def test_operation_rejects_during_restore(self):
        gate = maintenance.MaintenanceGate()
        entered = threading.Event()
        release = threading.Event()

        def hold_restore():
            with gate.restore():
                entered.set()
                release.wait()

        thread = threading.Thread(target=hold_restore)
        thread.start()
        self.assertTrue(entered.wait(1))
        with self.assertRaisesRegex(AppError, "Wartungsmodus") as caught, gate.operation():
            pass
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.reason, "maintenance")
        release.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_restore_drains_other_operations_when_called_from_operation(self):
        gate = maintenance.MaintenanceGate()
        other_entered = threading.Event()
        release_other = threading.Event()
        restore_entered = threading.Event()
        release_restore = threading.Event()

        def other_operation():
            with gate.operation():
                other_entered.set()
                release_other.wait()

        other = threading.Thread(target=other_operation)
        other.start()
        self.assertTrue(other_entered.wait(1))

        def restore_from_operation():
            with gate.operation(), gate.restore():
                restore_entered.set()
                release_restore.wait()

        owner = threading.Thread(target=restore_from_operation)
        owner.start()
        self.assertFalse(restore_entered.wait(0.05))
        release_other.set()
        self.assertTrue(restore_entered.wait(1))
        self.assertEqual(gate.state(), {"active": True, "running_operations": 0})
        release_restore.set()
        other.join(1)
        owner.join(1)
        self.assertFalse(other.is_alive())
        self.assertFalse(owner.is_alive())
        self.assertEqual(gate.state(), {"active": False, "running_operations": 0})

    def test_second_restore_is_rejected_and_restore_finally_cleans_up(self):
        gate = maintenance.MaintenanceGate()
        with gate.restore():
            with self.assertRaises(AppError) as caught, gate.restore():
                pass
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(gate.state(), {"active": True, "running_operations": 0})
        self.assertEqual(gate.state(), {"active": False, "running_operations": 0})

        with self.assertRaisesRegex(AppError, "Restore body"), gate.restore():
            raise AppError(500, "Restore body")
        self.assertEqual(gate.state(), {"active": False, "running_operations": 0})

    def test_restore_increments_generation_before_body(self):
        gate = maintenance.MaintenanceGate()
        before = gate.current_generation()
        with gate.restore():
            self.assertEqual(gate.current_generation(), before + 1)

    def test_operation_finally_notifies_waiting_restore(self):
        gate = maintenance.MaintenanceGate()
        entered = threading.Event()
        release = threading.Event()
        restore_body = threading.Event()

        def operation():
            with gate.operation():
                entered.set()
                release.wait()

        worker = threading.Thread(target=operation)
        worker.start()
        self.assertTrue(entered.wait(1))

        def restore():
            with gate.restore():
                restore_body.set()

        restoring = threading.Thread(target=restore)
        restoring.start()
        self.assertFalse(restore_body.wait(0.05))
        release.set()
        self.assertTrue(restore_body.wait(1))
        worker.join(1)
        restoring.join(1)
        self.assertFalse(worker.is_alive())
        self.assertFalse(restoring.is_alive())


class MaintenanceDecoratorTests(unittest.TestCase):
    def test_maintenance_decorator_uses_patchable_module_singleton_and_wraps(self):
        gate = maintenance.MaintenanceGate()

        @maintenance.maintenance_operation
        def operation(value):
            return value + 1

        self.assertEqual(operation.__name__, "operation")
        with patch.object(maintenance, "MAINTENANCE_GATE", gate):
            self.assertEqual(operation(4), 5)
        self.assertEqual(gate.state(), {"active": False, "running_operations": 0})

    def test_claimed_decorator_swallowing_and_propagation(self):
        gate = maintenance.MaintenanceGate()
        calls = []

        @maintenance.claimed_maintenance_operation
        def claimed(job):
            calls.append(job)
            return "done"

        with patch.object(maintenance, "MAINTENANCE_GATE", gate):
            self.assertEqual(claimed({"_maintenance_generation": 0}), "done")
            self.assertIsNone(claimed({"_maintenance_generation": -1}))
            with gate.restore():
                self.assertIsNone(claimed({"_maintenance_generation": gate.current_generation()}))
        self.assertEqual(calls, [{"_maintenance_generation": 0}])

        @maintenance.claimed_maintenance_operation
        def raises(_job):
            raise AppError(422, "other", reason="other")

        with patch.object(maintenance, "MAINTENANCE_GATE", gate), self.assertRaises(AppError) as caught:
            raises({"_maintenance_generation": gate.current_generation()})
        self.assertEqual(caught.exception.reason, "other")

    def test_claimed_decorator_preserves_metadata(self):
        def claimed_job(job):
            return job

        wrapped = maintenance.claimed_maintenance_operation(claimed_job)
        self.assertIs(wrapped.__wrapped__, claimed_job)
        self.assertEqual(wrapped.__name__, claimed_job.__name__)


if __name__ == "__main__":
    unittest.main()
