"""Tests for explicit planned-calendar composition."""

import unittest
from datetime import date
from unittest.mock import Mock, patch

from backend.sync import planned_calendar_assembly as assembly_module
from backend.sync.planned_calendar_assembly import PlannedCalendarSyncAssembly


class PlannedCalendarSyncAssemblyTests(unittest.TestCase):
    def _assembly(self, callbacks):
        return PlannedCalendarSyncAssembly(
            config=callbacks["config"],
            database_manager=callbacks["database_manager"],
            intervals_client=callbacks["intervals_client"],
            state_writer=callbacks["state_writer"],
            utc_now=callbacks["utc_now"],
            today=callbacks["today"],
            future_days=35,
        )

    def test_construction_does_not_resolve_runtime_dependencies(self):
        callbacks = {
            "config": Mock(),
            "database_manager": Mock(),
            "intervals_client": Mock(),
            "state_writer": Mock(),
            "utc_now": Mock(),
            "today": Mock(return_value=date(2026, 9, 26)),
        }

        self._assembly(callbacks)

        for callback in callbacks.values():
            callback.assert_not_called()

    def test_services_receive_fresh_state_writers_and_deferred_transport(self):
        callbacks = {
            "config": Mock(return_value="current config"),
            "database_manager": Mock(return_value="current manager"),
            "intervals_client": Mock(),
            "state_writer": Mock(side_effect=["sync writer", "repair writer"]),
            "utc_now": Mock(),
            "today": Mock(),
        }
        assembly = self._assembly(callbacks)

        with patch.object(assembly_module, "PlannedCalendarSyncService") as sync_type, patch.object(
            assembly_module, "PlannedCalendarRepairService"
        ) as repair_type:
            sync_service = assembly.sync_service()
            repair_service = assembly.repair_service()

        self.assertIsNotNone(sync_service)
        self.assertIsNotNone(repair_service)
        self.assertIs(sync_type.call_args.args[2], callbacks["intervals_client"])
        self.assertIs(repair_type.call_args.args[2], callbacks["intervals_client"])
        self.assertEqual(sync_type.call_args.args[3], "sync writer")
        self.assertEqual(repair_type.call_args.args[3], "repair writer")
        self.assertEqual(repair_type.call_args.args[-1], 35)
        self.assertEqual(callbacks["state_writer"].call_count, 2)


if __name__ == "__main__":
    unittest.main()
