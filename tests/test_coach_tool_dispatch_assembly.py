from __future__ import annotations

import unittest
from unittest.mock import DEFAULT, Mock, patch

from backend.coach import tool_dispatch_assembly
from backend.coach.tool_dispatch_assembly import (
    CoachPlanningToolOwners,
    CoachProposalToolOwners,
    CoachReadToolOwners,
    CoachSyncToolOwners,
    CoachToolDispatchAssembly,
)


class CoachToolDispatchAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        dependencies = {
            name: Mock(name=name)
            for name in (
                "read_tools", "profile_update", "athlete_records", "artifacts",
                "plan_replacement", "training_changes", "manager", "db_lock",
                "library", "library_plans", "sync_tools", "adaptive_preview",
                "adaptive_apply", "training_plan", "history_undo", "proposal_creation",
            )
        }
        assembly = CoachToolDispatchAssembly(dependencies=CoachToolDispatchAssembly.Inputs(
            reads=CoachReadToolOwners(
                read_tools=dependencies["read_tools"],
                profile_update=dependencies["profile_update"],
                athlete_records=dependencies["athlete_records"],
            ),
            planning=CoachPlanningToolOwners(
                training_plan_artifacts=dependencies["artifacts"],
                training_plan_replacement=dependencies["plan_replacement"],
                training_changes=dependencies["training_changes"],
                database_manager=dependencies["manager"],
                database_lock=dependencies["db_lock"],
                workout_library_service=dependencies["library"],
                training_plan_service=dependencies["training_plan"],
            ),
            sync=CoachSyncToolOwners(
                library_plan_tools=dependencies["library_plans"],
                sync_tools=dependencies["sync_tools"],
                history_undo=dependencies["history_undo"],
            ),
            proposals=CoachProposalToolOwners(
                adaptive_preview=dependencies["adaptive_preview"],
                adaptive_apply=dependencies["adaptive_apply"],
                proposal_creation=dependencies["proposal_creation"],
            ),
        ))
        return assembly, dependencies

    def test_assembly_is_lazy_and_preserves_deferred_factory_identities(self):
        assembly, dependencies = self.make_assembly()
        constructors = (
            "CoachPlanArtifactToolService",
            "CoachPlanningChangeToolService",
            "TrainingTemplateToolService",
            "CoachPlanningActionToolService",
            "CoachToolDispatchService",
        )
        with patch.multiple(tool_dispatch_assembly, **{name: DEFAULT for name in constructors}) as factories:
            factories["CoachToolDispatchService"].side_effect = [Mock(), Mock()]
            first = assembly.service()
            second = assembly.service()

        self.assertIsNot(first, second)
        self.assertEqual(factories["CoachToolDispatchService"].call_count, 2)
        args = factories["CoachToolDispatchService"].call_args.args
        self.assertIs(args[0], dependencies["read_tools"])
        self.assertIs(args[1], dependencies["profile_update"])
        self.assertIs(args[2], dependencies["athlete_records"])
        self.assertIs(args[3], factories["CoachPlanArtifactToolService"].return_value)
        self.assertIs(args[4], factories["CoachPlanningChangeToolService"].return_value)
        self.assertIs(args[5], factories["TrainingTemplateToolService"].return_value)
        self.assertIs(args[6], dependencies["library_plans"])
        self.assertIs(args[7], dependencies["sync_tools"])
        self.assertIs(args[8], factories["CoachPlanningActionToolService"].return_value)
        self.assertEqual(factories["TrainingTemplateToolService"].call_count, 2)
        factories["TrainingTemplateToolService"].assert_called_with(
            dependencies["manager"], dependencies["db_lock"], dependencies["library"]
        )
        self.assertEqual(factories["CoachPlanArtifactToolService"].call_count, 2)
        factories["CoachPlanArtifactToolService"].assert_called_with(dependencies["artifacts"])
        self.assertEqual(factories["CoachPlanningChangeToolService"].call_count, 2)
        factories["CoachPlanningChangeToolService"].assert_called_with(
            dependencies["plan_replacement"], dependencies["training_changes"]
        )
        self.assertEqual(factories["CoachPlanningActionToolService"].call_count, 2)
        factories["CoachPlanningActionToolService"].assert_called_with(
            dependencies["adaptive_preview"],
            dependencies["adaptive_apply"],
            dependencies["training_plan"],
            dependencies["history_undo"],
            dependencies["proposal_creation"],
        )
        dependencies["manager"].assert_not_called()
        dependencies["artifacts"].assert_not_called()
        dependencies["sync_tools"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
