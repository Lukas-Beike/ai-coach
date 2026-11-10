"""Tests for competition and provider resync composition."""

import logging
import unittest
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.providers.descriptors import GARMIN_ID, INTERVALS_ID
from backend.sync import provider_resync_assembly as assembly_module
from backend.sync.full_resync import resync_field_keys
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_resync_assembly import (
    CompetitionSyncOwners,
    GarminFullResync,
    ProviderResyncAssembly,
    ProviderResyncPersistence,
    ProviderResyncRuntime,
    ResyncProviderOwners,
    WahooFullResync,
    full_resync_handlers,
)


def _build_assembly(
    intervals_gate: ProviderResyncGate, garmin_gate: ProviderResyncGate
) -> ProviderResyncAssembly:
    return ProviderResyncAssembly(
        dependencies=ProviderResyncAssembly.Inputs(
            competition=CompetitionSyncOwners(
                config=Mock(return_value=Mock()),
                intervals_client=Mock(),
                competition_service=Mock(),
            ),
            resync=ResyncProviderOwners(
                garmin_sync_service=Mock(),
                garmin_resync_gate=garmin_gate,
                all_sync_days=-1,
            ),
            persistence=ProviderResyncPersistence(
                database_manager=Mock(),
                key_values=Mock(),
                event_buffer=Mock(),
                redactor=Mock(),
            ),
            runtime=ProviderResyncRuntime(
                logger=logging.getLogger("test.provider.resync.handlers"),
                utc_now=Mock(),
                uuid_factory=Mock(),
                monotonic=Mock(),
                operation_observer=Mock(),
            ),
        )
    )


class FullResyncHandlerWiringTests(unittest.TestCase):
    def test_garmin_handler_runs_full_window_with_resync_label(self):
        garmin = Mock()
        garmin.configured.return_value = True
        garmin.sync.return_value = {"records": 4}
        handlers = full_resync_handlers(
            garmin_service=garmin,
            all_sync_days=-1,
        )

        self.assertEqual(handlers[GARMIN_ID].run("op-1", Mock()), {"records": 4})
        garmin.sync.assert_called_once_with(
            days=-1, operation_id="op-1", reason="Vollständiger Resync"
        )

    def test_factory_rejects_handler_without_registered_state_keys(self):
        intervals_gate = ProviderResyncGate("Intervals.icu")
        garmin_gate = ProviderResyncGate("Garmin")
        assembly = _build_assembly(intervals_gate, garmin_gate)

        with (
            patch.object(assembly_module, "CompetitionSyncService"),
            patch.object(
                assembly_module,
                "full_resync_handlers",
                return_value={INTERVALS_ID: Mock(), "acme-mock": Mock()},
            ),
            patch.object(assembly_module, "FullProviderResyncService") as service_type,
            self.assertRaisesRegex(ValueError, "acme-mock"),
        ):
            assembly.full_resync_service()

        service_type.assert_not_called()


class ResyncFieldKeysTests(unittest.TestCase):
    def test_rejects_descriptor_without_four_state_keys(self):
        with self.assertRaisesRegex(ValueError, "needs keys for"):
            resync_field_keys({"acme-mock": ("a", "b", "c")})

    def test_names_keys_by_role_in_declared_order(self):
        self.assertEqual(
            resync_field_keys({"acme-mock": ("r", "s", "t", "e")}),
            {
                "acme-mock": {
                    "running": "r",
                    "status": "s",
                    "last_at": "t",
                    "error": "e",
                }
            },
        )


class ProviderResyncAssemblyTests(unittest.TestCase):
    def test_competition_client_factory_resolves_transport_when_called(self):
        transport = {"client_factory": Mock(return_value="current client")}

        def current_client_factory():
            return transport["client_factory"]()

        assembly = ProviderResyncAssembly(
            dependencies=ProviderResyncAssembly.Inputs(
                competition=CompetitionSyncOwners(
                    config=Mock(return_value=Mock()),
                    intervals_client=current_client_factory,
                    competition_service=Mock(),
                ),
                resync=ResyncProviderOwners(
                    garmin_sync_service=Mock(),
                    garmin_resync_gate=Mock(),
                    all_sync_days=90,
                ),
                persistence=ProviderResyncPersistence(
                    database_manager=Mock(),
                    key_values=Mock(),
                    event_buffer=Mock(),
                    redactor=Mock(),
                ),
                runtime=ProviderResyncRuntime(
                    logger=logging.getLogger("test.provider.resync.assembly"),
                    utc_now=Mock(),
                    uuid_factory=Mock(),
                    monotonic=Mock(),
                    operation_observer=Mock(),
                ),
            )
        )

        with patch.object(assembly_module, "CompetitionSyncService") as service_type:
            service = assembly.competition_sync_service()
            client_factory = service_type.call_args.args[1]
            transport["client_factory"] = Mock(return_value="patched client")
            self.assertEqual(client_factory(), "patched client")

        self.assertIsNotNone(service)
        transport["client_factory"].assert_called_once_with()


class GarminFullResyncTests(unittest.TestCase):
    def _resync(self, status: str) -> GarminFullResync:
        service = Mock()
        service.sync.return_value = {"status": status, "records": 3}
        return GarminFullResync(garmin_service=service, all_sync_days=-1)

    def test_a_complete_run_returns_the_sync_result(self):
        self.assertEqual(
            self._resync("ok").run("op-1", Mock()), {"status": "ok", "records": 3}
        )

    def test_a_partial_run_is_returned_so_the_service_does_not_record_it_complete(
        self,
    ):
        self.assertEqual(
            self._resync("partial").run("op-1", Mock())["status"], "partial"
        )

    def test_a_contended_run_is_a_409_failure(self):
        with self.assertRaises(AppError) as caught:
            self._resync("already_running").run("op-1", Mock())

        self.assertEqual(409, caught.exception.status)
        self.assertEqual("already_running", caught.exception.reason)

    def test_a_run_without_configuration_is_a_503_failure(self):
        with self.assertRaises(AppError) as caught:
            self._resync("not_configured").run("op-1", Mock())

        self.assertEqual(503, caught.exception.status)
        self.assertEqual("not_configured", caught.exception.reason)


class ResyncRunsSharingTests(unittest.TestCase):
    def test_every_service_of_one_assembly_shares_one_run_registry(self):
        assembly = _build_assembly(
            ProviderResyncGate("Intervals.icu"), ProviderResyncGate("Garmin")
        )

        first = assembly.full_resync_service()
        second = assembly.full_resync_service()

        self.assertIsNot(first, second)
        self.assertIs(first._runs, second._runs)


class WahooFullResyncTests(unittest.TestCase):
    def _resync(self, status: str) -> tuple[WahooFullResync, Mock]:
        sync = Mock()
        sync.configured.return_value = True
        sync.sync.return_value = {"status": status}
        return WahooFullResync(sync_service=sync, all_sync_days=-1), sync

    def test_completed_run_returns_the_sync_result_over_the_full_window(self):
        resync, sync = self._resync("completed")

        self.assertEqual(resync.run("op-1", Mock()), {"status": "completed"})
        sync.sync.assert_called_once_with(
            days=-1, reason="Vollständiger Resync", operation_id="op-1"
        )

    def test_not_configured_run_is_a_503_failure(self):
        resync, _sync = self._resync("not_configured")

        with self.assertRaises(AppError) as caught:
            resync.run("op-1", Mock())

        self.assertEqual(503, caught.exception.status)
        self.assertEqual("not_configured", caught.exception.reason)

    def test_contended_run_is_a_409_failure(self):
        resync, _sync = self._resync("already_running")

        with self.assertRaises(AppError) as caught:
            resync.run("op-1", Mock())

        self.assertEqual(409, caught.exception.status)
        self.assertEqual("already_running", caught.exception.reason)

    def test_truncated_run_is_a_failure_and_not_a_complete_resync(self):
        resync, _sync = self._resync("partial")

        with self.assertRaises(AppError) as caught:
            resync.run("op-1", Mock())

        self.assertEqual(502, caught.exception.status)
        self.assertEqual("partial_resync", caught.exception.reason)


if __name__ == "__main__":
    unittest.main()
