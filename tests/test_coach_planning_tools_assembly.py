from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.coach import planning_tools_assembly
from backend.coach.planning_tools_assembly import (
    CoachAdaptivePlanningDependencies,
    CoachPlanArtifactDependencies,
    CoachPlanningToolsAssembly,
    CoachTrainingPatchDependencies,
)


class CoachPlanningToolsAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        manager = Mock(name="database_manager")
        lock = Mock(name="database_lock")
        local_plan = Mock(name="local_plan_creation")
        local_plan_factory = Mock(return_value=local_plan)
        today = Mock(return_value="today")
        utc_now = Mock(return_value="now")
        uuid_factory = Mock(name="uuid_factory")
        library_plan = Mock(name="library_plan")
        library_plan_factory = Mock(return_value=library_plan)
        validator = Mock(name="validator")
        validator_factory = Mock(return_value=validator)
        changes = Mock(name="changes")
        changes_factory = Mock(return_value=changes)
        conflicts = Mock(name="conflicts")
        conflicts_factory = Mock(return_value=conflicts)
        keys = Mock(name="key_values")
        events = Mock(name="event_buffer")
        preview = Mock(name="adaptive_preview")
        preview_factory = Mock(return_value=preview)
        illness_sync = Mock(name="illness_sync")
        illness_factory = Mock(return_value=illness_sync)
        manager_factory = Mock(return_value=manager)
        assembly = CoachPlanningToolsAssembly(
            dependencies=CoachPlanningToolsAssembly.Inputs(
                database_manager=manager_factory,
                artifacts=CoachPlanArtifactDependencies(
                    local_plan_creation_service=local_plan_factory,
                    athlete_date=today,
                    utc_now=utc_now,
                    uuid_factory=uuid_factory,
                ),
                workout_library_plan_service=library_plan_factory,
                training_patch=CoachTrainingPatchDependencies(
                    database_lock=lock,
                    training_change_validator=validator_factory,
                    training_change_service=changes_factory,
                    calendar_conflict_service=conflicts_factory,
                    key_value_repository=keys,
                    event_buffer=events,
                    training_change_limit=40,
                ),
                adaptive=CoachAdaptivePlanningDependencies(
                    adaptive_preview_service=preview_factory,
                    illness_pause_sync_service=illness_factory,
                ),
            )
        )
        return assembly, locals()

    def test_assembly_is_lazy_and_preserves_domain_owner_identities(self):
        assembly, deps = self.make_assembly()
        deps["manager_factory"].assert_not_called()
        deps["local_plan_factory"].assert_not_called()
        deps["preview_factory"].assert_not_called()

        with patch.object(
            planning_tools_assembly, "TrainingPlanArtifactService"
        ) as artifact_factory:
            assembly.training_plan_artifact_service()
        artifact_args = artifact_factory.call_args.args
        self.assertIs(artifact_args[0], deps["manager"])
        self.assertIs(artifact_args[1], deps["local_plan"])
        self.assertIs(artifact_args[2], deps["today"])
        self.assertIs(artifact_args[3], deps["utc_now"])
        self.assertIs(artifact_args[4], deps["uuid_factory"])

        with patch.object(
            planning_tools_assembly, "CoachTrainingPatchService"
        ) as patch_factory:
            assembly.training_patch_service()
        patch_args = patch_factory.call_args.args
        self.assertIs(patch_args[0], deps["manager"])
        self.assertIs(patch_args[1], deps["lock"])
        self.assertIs(patch_args[2], deps["validator"])
        self.assertIs(patch_args[3], deps["changes"])
        self.assertIs(patch_args[4], deps["local_plan"])
        self.assertIs(patch_args[5], deps["conflicts"])
        self.assertIs(patch_args[6], deps["keys"])
        self.assertIs(patch_args[7], deps["events"])
        self.assertIs(patch_args[8], deps["today"])
        self.assertEqual(patch_args[9], 40)

        with patch.object(
            planning_tools_assembly, "CoachAdaptiveApplyService"
        ) as adaptive_factory:
            assembly.adaptive_apply_service()
        adaptive_args = adaptive_factory.call_args.args
        self.assertIs(adaptive_args[0], deps["preview"])
        self.assertIs(adaptive_args[1], deps["illness_sync"])
        self.assertIs(adaptive_args[2], deps["manager"])
        self.assertIs(adaptive_args[3], deps["lock"])

    def test_library_plan_tool_uses_shared_plan_factory(self):
        assembly, deps = self.make_assembly()
        with patch.object(
            planning_tools_assembly, "CoachLibraryPlanToolService"
        ) as factory:
            assembly.library_plan_tool_service()
        self.assertIs(factory.call_args.args[0], deps["library_plan"])
        self.assertEqual(deps["library_plan_factory"].call_count, 1)


if __name__ == "__main__":
    unittest.main()
