"""Tests for competition and provider resync composition."""

import logging
import unittest
from unittest.mock import MagicMock, Mock, patch

from backend.errors import AppError
from backend.providers.descriptors import GARMIN_ID, INTERVALS_ID
from backend.sync import provider_resync_assembly as assembly_module
from backend.sync.full_resync import resync_field_keys
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_resync_assembly import (
    CompetitionSyncOwners,
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
                config=Mock(return_value=Mock(intervals_api_key="key")),
                intervals_sync_service=Mock(),
                garmin_sync_service=Mock(),
                intervals_resync_gate=intervals_gate,
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
    def test_built_in_handlers_are_keyed_by_provider_identifier(self):
        handlers = full_resync_handlers(
            config=Mock(intervals_api_key="key"),
            intervals_service=Mock(),
            garmin_service=Mock(),
            competition_service=Mock(),
            gates={INTERVALS_ID: Mock(), GARMIN_ID: Mock()},
            all_sync_days=-1,
        )

        self.assertEqual(list(handlers), [INTERVALS_ID, GARMIN_ID])
        self.assertTrue(handlers[INTERVALS_ID].configured())

    def test_garmin_handler_runs_full_window_with_resync_label(self):
        garmin = Mock()
        garmin.configured.return_value = True
        garmin.sync.return_value = {"records": 4}
        handlers = full_resync_handlers(
            config=Mock(intervals_api_key="key"),
            intervals_service=Mock(),
            garmin_service=garmin,
            competition_service=Mock(),
            gates={INTERVALS_ID: Mock()},
            all_sync_days=-1,
        )

        self.assertEqual(handlers[GARMIN_ID].run("op-1", Mock()), {"records": 4})
        garmin.sync.assert_called_once_with(
            days=-1, operation_id="op-1", reason="Vollständiger Resync"
        )

    def test_intervals_handler_holds_its_gate_during_competition_sync(self):
        gate = ProviderResyncGate("Intervals.icu")
        active_during_competitions = []

        def competition_sync(**kwargs):
            active_during_competitions.append(gate.active)
            return {"imported": 0}

        intervals = Mock()
        intervals.sync.return_value = {"activities": 1}
        competition = Mock()
        competition.sync.side_effect = competition_sync
        handlers = full_resync_handlers(
            config=Mock(intervals_api_key="key"),
            intervals_service=intervals,
            garmin_service=Mock(),
            competition_service=competition,
            gates={INTERVALS_ID: gate},
            all_sync_days=-1,
        )

        result = handlers[INTERVALS_ID].run("op-2", MagicMock())

        self.assertEqual(result, {"activities": 1, "competitions": {"imported": 0}})
        self.assertEqual(active_during_competitions, [1])
        self.assertEqual(gate.active, 0)

    def test_full_resync_service_receives_registered_gates_and_handlers(self):
        intervals_gate = ProviderResyncGate("Intervals.icu")
        garmin_gate = ProviderResyncGate("Garmin")
        assembly = _build_assembly(intervals_gate, garmin_gate)

        with (
            patch.object(assembly_module, "CompetitionSyncService"),
            patch.object(
                assembly_module, "full_resync_handlers", return_value={}
            ) as handler_factory,
            patch.object(assembly_module, "FullProviderResyncService") as service_type,
        ):
            assembly.full_resync_service()

        gates = handler_factory.call_args.kwargs["gates"]
        self.assertIs(gates[INTERVALS_ID], intervals_gate)
        self.assertIs(gates[GARMIN_ID], garmin_gate)
        self.assertIs(service_type.call_args.kwargs["gates"], gates)
        self.assertEqual(service_type.call_args.args[0], {})

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
                    config=Mock(return_value=Mock()),
                    intervals_sync_service=Mock(),
                    garmin_sync_service=Mock(),
                    intervals_resync_gate=Mock(),
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
