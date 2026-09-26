"""Tests for competition and provider resync composition."""

import logging
import unittest
from unittest.mock import Mock, patch

from backend.sync import provider_resync_assembly as assembly_module
from backend.sync.provider_resync_assembly import ProviderResyncAssembly


class ProviderResyncAssemblyTests(unittest.TestCase):
    def test_competition_client_factory_resolves_transport_when_called(self):
        transport = {"client_factory": Mock(return_value="current client")}

        def current_client_factory():
            return transport["client_factory"]()

        assembly = ProviderResyncAssembly(
            config=Mock(return_value=Mock()),
            intervals_client=current_client_factory,
            competition_service=Mock(),
            intervals_sync_service=Mock(),
            garmin_sync_service=Mock(),
            database_manager=Mock(),
            key_values=Mock(),
            event_buffer=Mock(),
            redactor=Mock(),
            logger=logging.getLogger("test.provider.resync.assembly"),
            utc_now=Mock(),
            uuid_factory=Mock(),
            monotonic=Mock(),
            operation_observer=Mock(),
            intervals_resync_gate=Mock(),
            garmin_resync_gate=Mock(),
            all_sync_days=90,
        )

        with patch.object(assembly_module, "CompetitionSyncService") as service_type:
            service = assembly.competition_sync_service()
            client_factory = service_type.call_args.args[1]
            transport["client_factory"] = Mock(return_value="patched client")
            self.assertEqual(client_factory(), "patched client")

        self.assertIsNotNone(service)
        transport["client_factory"].assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
