from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from backend.http_api.public_state_assembly import (
    PublicStateAssembly,
    PublicStateCalendarSettings,
    PublicStateCoreInputs,
    PublicStateOperationalServices,
    PublicStateOwnerAssemblies,
    PublicStateProjectionOwners,
)


class PublicStateAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        names = (
            "database_manager",
            "database_lock",
            "config",
            "settings",
            "maintenance_gate",
            "key_values",
            "key_value_service",
            "sync_persistence",
            "planning_data",
            "athlete_data",
            "external_calendar",
            "provider_sync",
            "garmin",
            "sync_job_queue",
            "weather",
            "workout_library_sync",
            "provider_resync",
            "coach_conversation",
            "calendar_local",
            "planning_season",
            "intervals_state",
            "diagnostic_capture",
            "intervals_sync_lock",
            "workout_library_sync_running",
            "snapshot_repository",
            "daily_context",
            "adaptive_followup",
            "adaptive_preview",
            "morning_checkin",
            "quick_actions",
            "provider_state",
            "local_date",
            "local_now",
            "calendar_window",
            "calendar_history",
            "calendar_future",
            "sync_defaults",
            "all_sync_days",
            "workout_label",
        )
        deps = {name: Mock(name=name) for name in names}
        manager = Mock(name="manager")
        lock = MagicMock(name="database_lock")
        config = SimpleNamespace(calendar_ical_url="https://calendar.invalid/test.ics")
        settings = Mock(name="settings")
        gate = Mock(name="maintenance_gate")
        deps["database_manager"].return_value = manager
        deps["database_lock"].return_value = lock
        deps["config"].return_value = config
        deps["settings"].return_value = settings
        deps["maintenance_gate"].return_value = gate
        deps["calendar_window"].return_value = 21
        deps["calendar_history"].return_value = 14
        deps["calendar_future"].return_value = 42
        deps["all_sync_days"].return_value = 3650
        deps["workout_label"].return_value = "Synthetic workout"
        deps["sync_defaults"].return_value = {"intervals": 30}
        assembly = PublicStateAssembly(
            dependencies=PublicStateAssembly.Inputs(
                core=PublicStateCoreInputs(
                    database_manager=deps["database_manager"],
                    database_lock=deps["database_lock"],
                    config=deps["config"],
                    settings=deps["settings"],
                    maintenance_gate=deps["maintenance_gate"],
                    app_name="Synthetic Coach",
                    app_version="test-version",
                    key_values=deps["key_values"],
                    key_value_service=deps["key_value_service"],
                ),
                owners=PublicStateOwnerAssemblies(
                    snapshot_repository=deps["snapshot_repository"],
                    sync_persistence=deps["sync_persistence"],
                    planning_data=deps["planning_data"],
                    athlete_data=deps["athlete_data"],
                    external_calendar=deps["external_calendar"],
                    provider_sync=deps["provider_sync"],
                    garmin=deps["garmin"],
                    sync_job_queue=deps["sync_job_queue"],
                ),
                projections=PublicStateProjectionOwners(
                    weather=deps["weather"],
                    workout_library_sync=deps["workout_library_sync"],
                    provider_resync=deps["provider_resync"],
                    coach_conversation=deps["coach_conversation"],
                    calendar_local=deps["calendar_local"],
                    planning_season=deps["planning_season"],
                    intervals_state=deps["intervals_state"],
                    diagnostic_capture=deps["diagnostic_capture"],
                ),
                operations=PublicStateOperationalServices(
                    intervals_sync_lock=deps["intervals_sync_lock"],
                    workout_library_sync_running=deps["workout_library_sync_running"],
                    daily_planning_context_service=deps["daily_context"],
                    adaptive_preview_followup_service=deps["adaptive_followup"],
                    adaptive_replan_preview_service=deps["adaptive_preview"],
                    morning_checkin_state_service=deps["morning_checkin"],
                    coach_quick_actions_service=deps["quick_actions"],
                    provider_state_service=deps["provider_state"],
                ),
                calendar=PublicStateCalendarSettings(
                    local_date=deps["local_date"],
                    local_now=deps["local_now"],
                    external_calendar_window_days=deps["calendar_window"],
                    calendar_history_days=deps["calendar_history"],
                    calendar_future_days=deps["calendar_future"],
                    sync_period_defaults=deps["sync_defaults"],
                    all_sync_days=deps["all_sync_days"],
                    planned_workout_label=deps["workout_label"],
                ),
            )
        )
        return (
            assembly,
            deps,
            {
                "manager": manager,
                "lock": lock,
                "config": config,
                "settings": settings,
                "gate": gate,
            },
        )

    def test_bootstrap_keeps_manager_lazy_and_passes_current_configuration(self):
        assembly, deps, owners = self.make_assembly()

        service = assembly.bootstrap_service()

        self.assertIs(service._dependencies.config, owners["config"])
        self.assertIs(service._dependencies.settings, owners["settings"])
        self.assertIs(service._dependencies.database_lock, owners["lock"])
        deps["database_manager"].assert_not_called()
        deps["sync_persistence"].assert_called_once_with()
        deps["planning_data"].assert_called_once_with()

    def test_sync_projection_uses_current_maintenance_and_shared_interval_lock(self):
        assembly, deps, owners = self.make_assembly()

        service = assembly.sync_public_state_service()

        self.assertIs(service._maintenance_gate, owners["gate"])
        self.assertIs(service._intervals_sync_lock, deps["intervals_sync_lock"]())
        self.assertIs(service._database_manager, owners["manager"])
        self.assertIs(service._config, owners["config"])

    def test_state_version_service_uses_shared_repositories_and_athlete_profile(self):
        assembly, deps, owners = self.make_assembly()
        profile_service = Mock(name="profile_service")
        athlete = deps["athlete_data"].return_value
        athlete.profile.return_value = profile_service

        service = assembly.state_version_service()

        self.assertIs(service._database_manager, owners["manager"])
        self.assertIs(
            service._state_version_data._key_values, deps["key_value_service"]()
        )
        self.assertIs(
            service._state_version_data._snapshots, deps["snapshot_repository"]
        )
        self.assertIs(service._profile_service, profile_service)

    def test_public_state_assembly_retains_the_reentrant_lock_and_settings(self):
        assembly, _deps, owners = self.make_assembly()

        service = assembly.state_service()

        self.assertIs(service._deps.database_lock, owners["lock"])
        self.assertIs(service._deps.config, owners["config"])
        self.assertIs(service._deps.settings, owners["settings"])
        self.assertIs(service._deps.database_manager, _deps["database_manager"])


if __name__ == "__main__":
    unittest.main()
