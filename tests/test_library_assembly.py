"""Tests for workout-library provider synchronization composition."""

import unittest
from unittest.mock import Mock, patch

from backend.sync import library_assembly as assembly_module
from backend.sync.library_assembly import (
    WorkoutLibraryProvider,
    WorkoutLibraryState,
    WorkoutLibrarySyncAssembly,
)


class WorkoutLibrarySyncAssemblyTests(unittest.TestCase):
    def _callbacks(self):
        return {
            "config": Mock(return_value="current config"),
            "database_manager": Mock(return_value="current manager"),
            "intervals_client": Mock(),
            "workout_library_service": Mock(return_value="local library"),
            "utc_now": Mock(),
            "uuid_factory": Mock(),
        }

    def _assembly(self, callbacks):
        return WorkoutLibrarySyncAssembly(
            dependencies=WorkoutLibrarySyncAssembly.Inputs(
                provider=WorkoutLibraryProvider(
                    callbacks["config"],
                    callbacks["database_manager"],
                    callbacks["intervals_client"],
                    callbacks["workout_library_service"],
                ),
                state=WorkoutLibraryState(
                    Mock(),
                    Mock(),
                    Mock(),
                    callbacks["utc_now"],
                ),
                uuid_factory=callbacks["uuid_factory"],
            )
        )

    def test_construction_does_not_resolve_runtime_dependencies(self):
        callbacks = self._callbacks()

        self._assembly(callbacks)

        for callback in callbacks.values():
            callback.assert_not_called()

    def test_service_creation_uses_fresh_sync_state_and_deferred_transport(self):
        callbacks = self._callbacks()
        assembly = self._assembly(callbacks)

        with (
            patch.object(
                assembly_module, "WorkoutLibrarySyncStateService"
            ) as state_type,
            patch.object(assembly_module, "WorkoutLibrarySyncService") as sync_type,
        ):
            service = assembly.sync_service()
            next_service = assembly.sync_service()

        self.assertIsNotNone(service)
        self.assertIsNotNone(next_service)
        self.assertEqual(state_type.call_count, 2)
        self.assertIs(sync_type.call_args.args[1], callbacks["intervals_client"])
        self.assertEqual(sync_type.call_count, 2)

    def test_refresh_composes_library_and_remote_reconciliation_owners(self):
        callbacks = self._callbacks()
        assembly = self._assembly(callbacks)

        with patch.object(
            assembly_module, "WorkoutLibraryRefreshService"
        ) as refresh_type:
            refresh = assembly.refresh_service()

        self.assertIsNotNone(refresh)
        self.assertEqual(refresh_type.call_args.args[0], "current config")
        self.assertEqual(refresh_type.call_args.args[4], "local library")
        self.assertIs(refresh_type.call_args.args[2], callbacks["intervals_client"])
        self.assertEqual(callbacks["workout_library_service"].call_count, 1)


if __name__ == "__main__":
    unittest.main()
