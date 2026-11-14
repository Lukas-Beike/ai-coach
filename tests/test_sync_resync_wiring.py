"""The competition and provider resync builder reads the live owners (#2101)."""

import unittest
import uuid
from unittest.mock import Mock, patch

from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.errors import AppError
from backend.sync import resync_wiring as resync_module
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS, resync_field_keys
from backend.sync.gates import ProviderResyncGate
from backend.sync.resync_wiring import (
    GarminFullResync,
    WahooFullResync,
    build_provider_resync,
    full_resync_handlers,
)


class FullResyncHandlerWiringTests(unittest.TestCase):
    def test_garmin_handler_runs_full_window_with_resync_label(self):
        garmin = Mock()
        garmin.configured.return_value = True
        garmin.sync.return_value = {"records": 4}
        handlers = full_resync_handlers(
            garmin_service=garmin,
            wahoo_service=Mock(),
            all_sync_days=-1,
        )

        self.assertEqual({GARMIN_ID, WAHOO_ID}, set(handlers))
        self.assertEqual(handlers[GARMIN_ID].run("op-1", Mock()), {"records": 4})
        garmin.sync.assert_called_once_with(
            days=-1, operation_id="op-1", reason="Vollständiger Resync"
        )

    def test_every_handler_has_its_registered_state_keys(self):
        # Replaces the former build-time check of the runtime bindings (#2070).
        handlers = full_resync_handlers(
            garmin_service=Mock(), wahoo_service=Mock(), all_sync_days=-1
        )
        self.assertEqual(set(PROVIDER_RESYNC_KEYS), set(handlers))


class ResyncFieldKeysTests(unittest.TestCase):
    def test_rejects_descriptor_without_four_state_keys(self):
        with self.assertRaisesRegex(ValueError, "needs keys for"):
            resync_field_keys({"wahoo": ("a", "b", "c")})

    def test_names_keys_by_role_in_declared_order(self):
        self.assertEqual(
            resync_field_keys({"wahoo": ("r", "s", "t", "e")}),
            {
                "wahoo": {
                    "running": "r",
                    "status": "s",
                    "last_at": "t",
                    "error": "e",
                }
            },
        )


class ProviderResyncBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.gates = (ProviderResyncGate("Garmin"), ProviderResyncGate("Wahoo"))
        self.after = Mock(name="after resync")
        self.services = build_provider_resync(
            self.ctx,
            garmin_resync_gate=self.gates[0],
            wahoo_resync_gate=self.gates[1],
            all_sync_days=-1,
            after_resync=self.after,
        )

    def test_building_resolves_no_owner(self):
        self.ctx.config.assert_not_called()
        self.ctx.database.assert_not_called()
        self.ctx.provider_transport.intervals_client.assert_not_called()

    def test_competition_client_factory_resolves_transport_when_called(self):
        ctx = self.ctx
        with patch.object(resync_module, "CompetitionSyncService") as service_type:
            service = self.services.competition_sync_service()
            client_factory = service_type.call_args.args[1]
            ctx.provider_transport.intervals_client.assert_not_called()
            ctx.provider_transport = Mock(
                intervals_client=Mock(return_value="patched client")
            )
            self.assertEqual(client_factory(), "patched client")

        self.assertIs(service, service_type.return_value)
        self.assertEqual(
            (ctx.config.return_value,),
            service_type.call_args.args[:1],
        )
        self.assertIs(service_type.call_args.args[3], ctx.planning.competition())

    def test_competition_services_are_fresh_per_call(self):
        with patch.object(resync_module, "CompetitionSyncReconciler") as reconciler:
            self.services.competition_reconciler()
            self.services.competition_reconciler()

        self.assertEqual(2, reconciler.call_count)
        reconciler.assert_called_with(self.ctx.database.return_value, uuid.uuid4)

    def test_the_full_resync_reads_the_live_garmin_and_wahoo_owners(self):
        ctx = self.ctx
        with patch.object(resync_module, "full_resync_handlers") as handlers:
            service = self.services.full_resync_service()

        handlers.assert_called_once_with(
            garmin_service=ctx.garmin.sync_service.return_value,
            wahoo_service=ctx.wahoo.sync_service.return_value,
            all_sync_days=-1,
        )
        self.assertIs(service._handlers, handlers.return_value)
        self.assertEqual(
            {GARMIN_ID: self.gates[0], WAHOO_ID: self.gates[1]}, service._gates
        )
        self.assertIs(service._after_resync, self.after)

    def test_every_service_of_one_builder_shares_one_run_registry(self):
        first = self.services.full_resync_service()
        second = self.services.full_resync_service()

        self.assertIsNot(first, second)
        self.assertIs(first._runs, second._runs)


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

    def test_a_contended_or_unconfigured_run_is_a_failure(self):
        for status, http_status in (("already_running", 409), ("not_configured", 503)):
            with self.subTest(status=status), self.assertRaises(AppError) as caught:
                self._resync(status).run("op-1", Mock())

            self.assertEqual(http_status, caught.exception.status)
            self.assertEqual(status, caught.exception.reason)


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

    def test_an_unconfigured_contended_or_truncated_run_is_a_failure(self):
        # A truncated run is a failure, not a complete resync.
        for status, http_status, reason in (
            ("not_configured", 503, "not_configured"),
            ("already_running", 409, "already_running"),
            ("partial", 502, "partial_resync"),
        ):
            with self.subTest(status=status):
                resync, _sync = self._resync(status)

                with self.assertRaises(AppError) as caught:
                    resync.run("op-1", Mock())

                self.assertEqual(http_status, caught.exception.status)
                self.assertEqual(reason, caught.exception.reason)


if __name__ == "__main__":
    unittest.main()
