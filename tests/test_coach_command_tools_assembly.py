from __future__ import annotations

import unittest
from unittest.mock import Mock

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



if __name__ == "__main__":
    unittest.main()
