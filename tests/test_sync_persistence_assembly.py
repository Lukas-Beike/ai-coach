"""Tests for explicit sync persistence composition."""

import unittest
from unittest.mock import Mock, patch

from backend.sync import persistence_assembly


class SyncPersistenceAssemblyTests(unittest.TestCase):
    def test_services_resolve_the_current_manager_on_each_call(self):
        manager = Mock()
        manager_provider = Mock(side_effect=[manager, manager])
        key_values = Mock()
        snapshots = Mock()
        utc_now = Mock()
        athlete_clock = Mock()
        athlete_clock.return_value.now = Mock()
        assembly = persistence_assembly.SyncPersistenceAssembly(
            database_manager=manager_provider,
            key_values=key_values,
            snapshots=snapshots,
            utc_now=utc_now,
            athlete_clock=athlete_clock,
        )
        manager_provider.assert_not_called()

        with patch.object(persistence_assembly, "SyncStateRepository") as state_factory:
            state = assembly.state_repository()
        with patch.object(persistence_assembly, "DailySyncMarkerService") as marker_factory:
            markers = assembly.daily_markers()

        self.assertIs(state, state_factory.return_value)
        self.assertIs(markers, marker_factory.return_value)
        state_factory.assert_called_once_with(manager, key_values, snapshots, utc_now)
        athlete_clock.assert_called_once_with()
        marker_factory.assert_called_once_with(manager, key_values, athlete_clock.return_value.now)
        self.assertEqual(manager_provider.call_count, 2)


if __name__ == "__main__":
    unittest.main()
