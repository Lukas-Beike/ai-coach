from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.history import assembly as history_assembly
from backend.history.assembly import (
    HistoryAssembly,
    HistoryAthleteServices,
    HistoryPersistence,
    HistoryPlanningServices,
)


class HistoryAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        manager = Mock(name="database_manager")
        manager_factory = Mock(return_value=manager)
        deps = {
            "database_manager": manager_factory,
            "profile_repository": Mock(name="profile_repository"),
            "profile_service": Mock(name="profile_service"),
            "workout_library_service": Mock(name="workout_library_service"),
            "competition_service": Mock(name="competition_service"),
            "planned_unit_service": Mock(name="planned_unit_service"),
            "training_plan_service": Mock(name="training_plan_service"),
            "planning_revision_service": Mock(name="planning_revision"),
        }
        assembly = HistoryAssembly(dependencies=HistoryAssembly.Inputs(
            persistence=HistoryPersistence(deps["database_manager"], deps["profile_repository"]),
            athlete=HistoryAthleteServices(deps["profile_service"], deps["competition_service"]),
            planning=HistoryPlanningServices(
                deps["workout_library_service"], deps["planned_unit_service"],
                deps["training_plan_service"], deps["planning_revision_service"],
            ),
        ))
        return assembly, deps, manager

    def test_history_services_keep_manager_and_domain_owner_identities(self):
        assembly, deps, manager = self.make_assembly()
        with (
            patch.object(history_assembly, "ChangeHistoryService") as history,
            patch.object(history_assembly, "HistoryUndoService") as undo,
        ):
            assembly.change_history_service()
            assembly.undo_service()

        self.assertIs(history.call_args.args[0], manager)
        self.assertIs(history.call_args.args[1], deps["profile_repository"])
        self.assertIs(undo.call_args.args[0], manager)
        self.assertIs(undo.call_args.args[1], history.return_value)
        self.assertEqual(undo.call_args.args[2:], (
            deps["profile_service"].return_value,
            deps["workout_library_service"].return_value,
            deps["competition_service"].return_value,
            deps["planned_unit_service"].return_value,
            deps["training_plan_service"].return_value,
            deps["planning_revision_service"],
        ))


if __name__ == "__main__":
    unittest.main()
