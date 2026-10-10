"""Tests for selected-workout synchronization composition."""

import unittest
from unittest.mock import Mock, patch

from backend.sync import selected_assembly as assembly_module
from backend.sync.selected_assembly import (
    SelectedWorkoutControls,
    SelectedWorkoutProviders,
    SelectedWorkoutSyncAssembly,
)


class SelectedWorkoutSyncAssemblyTests(unittest.TestCase):
    def _callbacks(self):
        return {
            "config": Mock(return_value="current config"),
            "database_manager": Mock(return_value="current manager"),
            "workout_library_sync_service": Mock(return_value="library sync"),
            "planned_calendar_sync_service": Mock(return_value="calendar sync"),
            "planned_calendar_repair_service": Mock(return_value="calendar repair"),
        }

    def _assembly(self, callbacks):
        return SelectedWorkoutSyncAssembly(
            dependencies=SelectedWorkoutSyncAssembly.Inputs(
                providers=SelectedWorkoutProviders(**callbacks),
                controls=SelectedWorkoutControls(Mock(), Mock(), 120, Mock()),
            )
        )

    def test_construction_does_not_resolve_subordinate_owners(self):
        callbacks = self._callbacks()

        assembly = self._assembly(callbacks)

        self.assertIsNotNone(assembly)
        for callback in callbacks.values():
            callback.assert_not_called()

    def test_service_uses_fresh_services_and_shared_sync_controls(self):
        callbacks = self._callbacks()
        redactor = Mock()
        lock = Mock()
        gate = Mock()
        assembly = SelectedWorkoutSyncAssembly(
            dependencies=SelectedWorkoutSyncAssembly.Inputs(
                providers=SelectedWorkoutProviders(**callbacks),
                controls=SelectedWorkoutControls(redactor, lock, 90, gate),
            )
        )

        with patch.object(
            assembly_module, "SelectedWorkoutSyncService"
        ) as service_type:
            service = assembly.service()

        self.assertIsNotNone(service)
        self.assertEqual(
            service_type.call_args.args,
            (
                "current config",
                "current manager",
                "library sync",
                "calendar sync",
                "calendar repair",
                redactor,
            ),
        )
        self.assertEqual(
            service_type.call_args.kwargs,
            {
                "lock": lock,
                "wait_seconds": 90,
                "provider_resync_gate": gate,
            },
        )


if __name__ == "__main__":
    unittest.main()
