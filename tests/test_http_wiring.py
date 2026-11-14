from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.http_api.wiring import build_public_state


class PublicStateWiringTests(unittest.TestCase):
    def make_services(self):
        manager = Mock(name="manager")
        config = SimpleNamespace(calendar_ical_url="https://calendar.invalid/test.ics")
        settings = Mock(name="settings")
        gate = Mock(name="maintenance_gate")
        ctx = SimpleNamespace(
            database=Mock(name="database", return_value=manager),
            config=Mock(name="config", return_value=config),
            settings=settings,
            maintenance=gate,
            app_name="Synthetic Coach",
            app_version="test-version",
            key_values=Mock(name="key_values"),
            clock=Mock(name="clock"),
            logger=Mock(name="logger"),
            provider_state=Mock(name="provider_state"),
            athlete=Mock(name="athlete"),
            planning=Mock(name="planning"),
            planning_workflows=Mock(name="planning_workflows"),
            sync_persistence=Mock(name="sync_persistence"),
            external_calendar=Mock(name="external_calendar"),
            provider_sync=Mock(name="provider_sync"),
            garmin=Mock(name="garmin"),
            sync_job_queue=Mock(name="sync_job_queue"),
            coach_conversation=Mock(name="coach_conversation"),
            coach_local=Mock(name="coach_local"),
            workout_library_sync=Mock(name="workout_library_sync"),
            diagnostic_capture=Mock(name="diagnostic_capture"),
            weather=Mock(name="weather"),
        )
        key_value_service = Mock(name="key_value_service")
        services = build_public_state(
            ctx,
            key_value_service=key_value_service,
            provider_credentials=Mock(name="provider_credentials"),
            provider_resync=Mock(name="provider_resync"),
            running_probes={},
            sync_period_defaults=Mock(return_value={"intervals": 30}),
            all_sync_days=3650,
            external_calendar_window_days=Mock(return_value=21),
        )
        return (
            services,
            ctx,
            {
                "manager": manager,
                "config": config,
                "settings": settings,
                "gate": gate,
                "key_value_service": key_value_service,
            },
        )

    def test_bootstrap_keeps_manager_lazy_and_passes_current_configuration(self):
        services, ctx, owners = self.make_services()

        service = services.bootstrap_service()

        self.assertIs(service._dependencies.config, owners["config"])
        self.assertIs(service._dependencies.settings, owners["settings"])
        self.assertIs(service._dependencies.database_manager, ctx.database)
        ctx.database.assert_not_called()
        self.assertIs(
            service._dependencies.sync_state_repository,
            ctx.sync_persistence.state_repository,
        )
        self.assertIs(
            service._dependencies.planned_unit_service, ctx.planning.planned_unit
        )

    def test_sync_projection_uses_current_maintenance_and_shared_interval_lock(self):
        services, _ctx, owners = self.make_services()

        service = services.sync_public_state_service()

        self.assertIs(service._maintenance_gate, owners["gate"])
        self.assertIs(service._database_manager, owners["manager"])
        self.assertIs(service._config, owners["config"])

    def test_state_version_service_uses_shared_repositories_and_athlete_profile(self):
        services, ctx, owners = self.make_services()
        profile_service = Mock(name="profile_service")
        ctx.athlete.profile.return_value = profile_service

        version_service = services.sync_public_state_service()._state_version_service

        self.assertIs(version_service._database_manager, owners["manager"])
        self.assertIs(
            version_service._state_version_data._key_values,
            owners["key_value_service"].return_value,
        )
        self.assertIs(version_service._profile_service, profile_service)


if __name__ == "__main__":
    unittest.main()
