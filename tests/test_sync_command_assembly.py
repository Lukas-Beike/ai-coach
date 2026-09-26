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


if __name__ == "__main__":
    unittest.main()
