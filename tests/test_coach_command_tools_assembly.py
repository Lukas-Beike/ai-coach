from __future__ import annotations

import unittest
from unittest.mock import DEFAULT, Mock, patch

from backend.coach import command_tools_assembly
from backend.coach.command_tools_assembly import (
    CoachAthleteToolFactories,
    CoachCommandToolsAssembly,
    CoachProfileToolDependencies,
    CoachSyncAuthorityTools,
    CoachSyncMutationTools,
    CoachSyncProvider,
)


class CoachCommandToolsAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        names = (
            "sync_job_queue",
            "planning_authority",
            "sync_conflict_commands",
            "structured_plan_sync",
            "plan_repair_manifest",
            "plan_push_command",
            "provider_refresh_command",
            "checkin_service",
            "activity_feedback_service",
            "competition_service",
            "nutrition_diary_service",
            "nutrition_meal_library_service",
            "profile_service",
            "database_manager",
            "database_lock",
            "duplicate_activity",
            "intervals_client",
        )
        dependencies = {name: Mock(name=name) for name in names}
        assembly = CoachCommandToolsAssembly(
            sync_authority=CoachSyncAuthorityTools(
                **{
                    name: dependencies[name]
                    for name in (
                        "sync_job_queue",
                        "planning_authority",
                        "sync_conflict_commands",
                        "structured_plan_sync",
                    )
                }
            ),
            sync_mutations=CoachSyncMutationTools(
                **{
                    name: dependencies[name]
                    for name in (
                        "plan_repair_manifest",
                        "plan_push_command",
                        "provider_refresh_command",
                        "duplicate_activity",
                    )
                }
            ),
            sync_provider=CoachSyncProvider(
                intervals_client=dependencies["intervals_client"]
            ),
            athlete_tools=CoachAthleteToolFactories(
                **{
                    name: dependencies[name]
                    for name in (
                        "checkin_service",
                        "activity_feedback_service",
                        "competition_service",
                        "nutrition_diary_service",
                        "nutrition_meal_library_service",
                    )
                }
            ),
            profile_tools=CoachProfileToolDependencies(
                dependencies["profile_service"],
                dependencies["database_manager"],
                dependencies["database_lock"],
            ),
        )
        return assembly, dependencies

    def test_factories_keep_resolution_lazy_and_preserve_shared_dependencies(self):
        assembly, deps = self.make_assembly()
        for name, dependency in deps.items():
            if name not in {"database_lock", "intervals_client"}:
                dependency.assert_not_called()

        with patch.multiple(
            command_tools_assembly,
            CoachSyncToolService=DEFAULT,
            CoachAthleteRecordToolService=DEFAULT,
            CoachProfileUpdateService=DEFAULT,
        ) as constructors:
            assembly.sync_tool_service()
            assembly.athlete_record_tool_service()
            assembly.profile_update_service()

        constructors["CoachSyncToolService"].assert_called_once_with(
            deps["sync_job_queue"].return_value,
            deps["planning_authority"].return_value,
            deps["sync_conflict_commands"].return_value,
            deps["structured_plan_sync"].return_value,
            deps["plan_repair_manifest"].return_value,
            deps["plan_push_command"].return_value,
            deps["provider_refresh_command"].return_value,
            duplicate_activity=deps["duplicate_activity"].return_value,
            intervals_client_factory=deps["intervals_client"],
            nutrition_diary=deps["nutrition_diary_service"].return_value,
        )
        constructors["CoachAthleteRecordToolService"].assert_called_once_with(
            deps["checkin_service"].return_value,
            deps["activity_feedback_service"].return_value,
            deps["competition_service"].return_value,
            deps["nutrition_diary_service"].return_value,
            deps["nutrition_meal_library_service"].return_value,
            equipment=None,
        )
        constructors["CoachProfileUpdateService"].assert_called_once_with(
            deps["profile_service"].return_value,
            deps["database_manager"].return_value,
            deps["database_lock"],
        )
        for name, dependency in deps.items():
            if name not in {"database_lock", "intervals_client"}:
                expected_calls = 2 if name == "nutrition_diary_service" else 1
                self.assertEqual(dependency.call_count, expected_calls)


if __name__ == "__main__":
    unittest.main()
