"""Garmin snapshot writers must share the one process-wide Garmin lock.

The Garmin sync service and the Morning Body Battery refresh both write Garmin
snapshots. They coordinate through ``shared_garmin_sync_lock()``; if either
side is wired to a different lock, the two writers can interleave. The sync
service is built through the production ``GarminAssembly``; the Morning gate is
built directly because its server.py wiring is not importable here. Collaborators
are inert mocks, and no Garmin, OpenAI or database access happens.
"""

import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import Mock

from backend.performance.morning_battery_service import MorningBatteryExecutionGate
from backend.sync import garmin_service
from backend.sync.garmin_assembly import GarminAssembly
from backend.sync.garmin_service import GarminSyncCoordination, shared_garmin_sync_lock

WAIT_SECONDS = 5


class _NoopGate:
    @contextmanager
    def operation(self) -> Iterator[None]:
        yield


def _morning_gate(wait_seconds: int = 0) -> MorningBatteryExecutionGate:
    return MorningBatteryExecutionGate(
        shared_garmin_sync_lock(), _NoopGate(), _NoopGate(), wait_seconds
    )


def _garmin_assembly() -> GarminAssembly:
    provider: Any = Mock(name="provider")
    persistence: Any = Mock(name="persistence")
    telemetry: Any = Mock(name="telemetry")
    control: Any = Mock(name="control")
    control.lock_wait_seconds = 0
    control.resync_gate = None
    return GarminAssembly(
        dependencies=GarminAssembly.Inputs(
            provider=provider,
            persistence=persistence,
            telemetry=telemetry,
            control=control,
        )
    )


class GarminSnapshotWriterLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = shared_garmin_sync_lock()
        self.assertFalse(self.lock.locked(), "Garmin lock leaked from another test")

    def test_shared_lock_is_the_module_level_garmin_lock(self) -> None:
        self.assertIs(shared_garmin_sync_lock(), garmin_service.GARMIN_SYNC_LOCK)
        self.assertIs(shared_garmin_sync_lock(), shared_garmin_sync_lock())

    def test_production_garmin_sync_service_uses_the_global_lock(self) -> None:
        sync_service = _garmin_assembly().sync_service()

        self.assertFalse(sync_service.running())
        self.assertTrue(self.lock.acquire(timeout=WAIT_SECONDS))
        try:
            self.assertTrue(sync_service.running())
        finally:
            self.lock.release()
        self.assertFalse(sync_service.running())

    def test_sync_coordination_reports_running_while_the_lock_is_held(self) -> None:
        coordination = GarminSyncCoordination()

        self.assertFalse(coordination.running())
        self.assertTrue(self.lock.acquire(timeout=WAIT_SECONDS))
        try:
            self.assertTrue(coordination.running())
        finally:
            self.lock.release()
        self.assertFalse(coordination.running())

    def test_sync_coordination_refuses_a_held_lock_without_blocking(self) -> None:
        coordination = GarminSyncCoordination()

        self.assertTrue(self.lock.acquire(timeout=WAIT_SECONDS))
        try:
            self.assertFalse(coordination.acquire())
            self.assertFalse(coordination.acquire(timeout=0))
        finally:
            self.lock.release()

        self.assertTrue(coordination.acquire(timeout=0))
        coordination.release()
        self.assertFalse(self.lock.locked())

    def test_morning_gate_uses_the_same_lock_as_sync_coordination(self) -> None:
        coordination = GarminSyncCoordination()
        gate = _morning_gate()

        with gate.shared_lock() as acquired:
            self.assertTrue(acquired)
            self.assertTrue(coordination.running())
        self.assertFalse(coordination.running())

    def test_morning_gate_yields_not_acquired_while_sync_holds_the_lock(self) -> None:
        gate = _morning_gate()

        self.assertTrue(self.lock.acquire(timeout=WAIT_SECONDS))
        try:
            with gate.shared_lock() as acquired:
                self.assertFalse(acquired)
            # A not-acquired gate must not release a lock it does not own.
            self.assertTrue(self.lock.locked())
        finally:
            self.lock.release()

    def test_sync_held_on_another_thread_is_seen_by_morning_gate(self) -> None:
        coordination = GarminSyncCoordination()
        gate = _morning_gate()
        holding = threading.Event()
        release = threading.Event()
        acquired_by_worker: list[bool] = []

        def hold_like_a_sync_run() -> None:
            acquired = self.lock.acquire(timeout=WAIT_SECONDS)
            acquired_by_worker.append(acquired)
            holding.set()
            if not acquired:
                return
            try:
                release.wait(WAIT_SECONDS)
            finally:
                self.lock.release()

        worker = threading.Thread(target=hold_like_a_sync_run)
        worker.start()
        try:
            self.assertTrue(holding.wait(WAIT_SECONDS))
            self.assertEqual(acquired_by_worker, [True])
            self.assertTrue(coordination.running())
            with gate.shared_lock() as acquired:
                self.assertFalse(acquired)
        finally:
            release.set()
            worker.join(WAIT_SECONDS)
        self.assertFalse(worker.is_alive())
        self.assertFalse(coordination.running())


if __name__ == "__main__":
    unittest.main()
