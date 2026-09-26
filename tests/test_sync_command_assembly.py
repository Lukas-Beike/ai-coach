from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.sync.command_assembly import SyncCommandAssembly


class SyncCommandAssemblyTests(unittest.TestCase):
    def make_assembly(self) -> SyncCommandAssembly:
        self.manager = object()
        self.queue = object()
        self.intervals = object()
        self.planned_units = object()
        self.competitions = object()
        self.library_state = object()
        self.revision = object()
        self.clock = Mock()
        self.database_manager = Mock(return_value=self.manager)
        self.queue_service = Mock(return_value=self.queue)
        self.intervals_sync = Mock(return_value=self.intervals)
        self.planned_unit_service = Mock(return_value=self.planned_units)
        self.competition_service = Mock(return_value=self.competitions)
        self.library_sync_state = Mock(return_value=self.library_state)
        self.config = Mock()
        self.intervals_client = Mock()
        self.adaptive_apply = Mock()
        self.adaptive_preview = Mock()
        self.redactor = Mock()
        self.today = Mock()
        return SyncCommandAssembly(
            database_manager=self.database_manager,
            queue_service=self.queue_service,
            intervals_sync=self.intervals_sync,
            planned_unit_service=self.planned_unit_service,
            competition_service=self.competition_service,
            workout_library_sync_state=self.library_sync_state,
            planning_revision=self.revision,
            utc_now=self.clock,
            training_change_limit=24,
            all_sync_days=-1,
            config=self.config,
            intervals_client=self.intervals_client,
            adaptive_replan_apply=self.adaptive_apply,
            adaptive_replan_preview=self.adaptive_preview,
            redactor=self.redactor,
            today=self.today,
        )

    def test_authority_uses_shared_manager_library_state_revision_and_clock(self):
        assembly = self.make_assembly()
        result = object()
        with patch(
            "backend.sync.command_assembly.PlanningAuthorityService",
            return_value=result,
        ) as factory:
            self.assertIs(assembly.authority(), result)

        factory.assert_called_once_with(
            self.manager, self.library_state, self.revision, self.clock
        )
        self.database_manager.assert_called_once_with()
        self.library_sync_state.assert_called_once_with()

    def test_provider_refresh_resolves_fresh_shared_queue_and_intervals_services(self):
        assembly = self.make_assembly()
        result = object()
        with patch(
            "backend.sync.command_assembly.ProviderRefreshCommandService",
            return_value=result,
        ) as factory:
            self.assertIs(assembly.provider_refresh(), result)

        factory.assert_called_once_with(self.queue, self.intervals, -1)
        self.queue_service.assert_called_once_with()
        self.intervals_sync.assert_called_once_with()

    def test_illness_pause_uses_current_config_and_sync_authority_dependencies(self):
        assembly = self.make_assembly()
        result = object()
        with patch("backend.sync.command_assembly.IllnessPauseSyncService", return_value=result) as factory:
            self.assertIs(assembly.illness_pause(), result)

        self.config.assert_called_once_with()
        self.intervals_client.assert_called_once_with()
        self.adaptive_apply.assert_called_once_with()
        self.adaptive_preview.assert_called_once_with()
        self.competition_service.assert_called_once_with()
        factory.assert_called_once_with(
            self.config.return_value,
            self.intervals_client.return_value,
            adaptive_replan_apply_service=self.adaptive_apply.return_value,
            competition_service=self.competitions,
            adaptive_replan_preview_service=self.adaptive_preview.return_value,
            redactor=self.redactor,
            today=self.today,
        )


if __name__ == "__main__":
    unittest.main()
