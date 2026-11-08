"""Tests for planned-unit sync persistence and reconciliation composition."""

import unittest
from datetime import date
from unittest.mock import Mock, patch

from backend.sync import planned_unit_assembly as assembly_module
from backend.sync.planned_unit_assembly import (
    PlannedUnitOwners,
    PlannedUnitRuntime,
    PlannedUnitSyncAssembly,
)


class PlannedUnitSyncAssemblyTests(unittest.TestCase):
    def _assembly(self, callbacks):
        return PlannedUnitSyncAssembly(
            dependencies=PlannedUnitSyncAssembly.Inputs(
                owners=PlannedUnitOwners(
                    callbacks["database_manager"],
                    callbacks["planned_unit_service"],
                    callbacks["planning_revision_service"],
                ),
                runtime=PlannedUnitRuntime(
                    callbacks["redactor"],
                    callbacks["utc_now"],
                    callbacks["today"],
                ),
            )
        )

    def test_construction_defers_current_resources(self):
        callbacks = {
            "database_manager": Mock(),
            "planned_unit_service": Mock(),
            "planning_revision_service": Mock(),
            "redactor": Mock(),
            "utc_now": Mock(),
            "today": Mock(return_value=date(2026, 9, 26)),
        }

        assembly = self._assembly(callbacks)

        self.assertIsNotNone(assembly)
        callbacks["database_manager"].assert_not_called()
        callbacks["planned_unit_service"].assert_not_called()
        callbacks["today"].assert_not_called()

    def test_state_writer_uses_shared_revision_and_redactor(self):
        callbacks = {
            "database_manager": Mock(),
            "planned_unit_service": Mock(),
            "planning_revision_service": Mock(),
            "redactor": Mock(),
            "utc_now": Mock(),
            "today": Mock(),
        }
        assembly = self._assembly(callbacks)

        with patch.object(assembly_module, "PlannedUnitSyncStateWriter") as writer_type:
            writer = assembly.state_writer()

        self.assertIsNotNone(writer)
        writer_type.assert_called_once_with(
            callbacks["planning_revision_service"], callbacks["redactor"]
        )



if __name__ == "__main__":
    unittest.main()
