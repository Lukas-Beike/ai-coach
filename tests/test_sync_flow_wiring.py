"""The output-flow sync builders read the live owners from the context (#2101)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import Mock, patch

from backend.canonical.vocabulary import ProviderId
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync import external_calendar, flow_wiring
from backend.sync.intervals_workout_export import IntervalsWorkoutExport


class PlannedUnitBuilderTests(unittest.TestCase):
    def test_the_writer_uses_the_shared_revision_and_redactor(self) -> None:
        ctx = Mock(name="context")
        services = flow_wiring.build_planned_unit_sync(ctx)
        ctx.planning_revision.assert_not_called()

        with patch.object(flow_wiring, "PlannedUnitSyncStateWriter") as writer:
            self.assertIs(services.state_writer(), writer.return_value)

        writer.assert_called_once_with(ctx.planning_revision, ctx.redactor)


class PlannedCalendarBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.writer = Mock(side_effect=["sync writer", "repair writer"])
        self.services = flow_wiring.build_planned_calendar_sync(
            self.ctx, state_writer=self.writer, future_days=35
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.config.assert_not_called()
        self.ctx.database.assert_not_called()
        self.ctx.provider_transport.intervals_client.assert_not_called()
        self.writer.assert_not_called()

    def test_the_services_get_fresh_writers_and_a_deferred_client(self) -> None:
        ctx = self.ctx
        with (
            patch.object(flow_wiring, "PlannedCalendarSyncService") as sync_type,
            patch.object(flow_wiring, "PlannedCalendarRepairService") as repair_type,
        ):
            self.assertIs(self.services.sync_service(), sync_type.return_value)
            self.assertIs(self.services.repair_service(), repair_type.return_value)

        sync_args = sync_type.call_args.args
        self.assertEqual(
            (ctx.config.return_value, ctx.database.return_value),
            sync_args[:2],
        )
        self.assertIsInstance(sync_args[2], IntervalsWorkoutExport)
        self.assertEqual(("sync writer", runtime_clock.utc_now), sync_args[3:5])
        self.assertIs(sync_args[5](), ctx.clock.now.return_value.date.return_value)
        # The planned calendar no longer takes the key-value store (#2549).
        self.assertNotIn("key_values", sync_type.call_args.kwargs)
        repair_args = repair_type.call_args.args
        self.assertEqual(ctx.database.return_value, repair_args[0])
        self.assertIsInstance(repair_args[1], IntervalsWorkoutExport)
        self.assertEqual("repair writer", repair_args[2])
        self.assertEqual(35, repair_args[-1])
        ctx.provider_transport.intervals_client.assert_not_called()

    def test_the_export_port_resolves_the_client_per_remote_call(self) -> None:
        ctx = self.ctx
        ctx.provider_transport.intervals_client.return_value.get_event.return_value = {
            "id": "event-1"
        }
        with patch.object(flow_wiring, "PlannedCalendarRepairService") as repair:
            self.services.repair_service()
        port = repair.call_args.args[1]
        ctx.provider_transport.intervals_client.assert_not_called()

        self.assertEqual({"id": "event-1"}, port.read_event("event-1"))
        ctx.provider_transport.intervals_client.assert_called_once_with()

    def test_the_run_threshold_resolver_is_read_when_a_unit_is_pushed(self) -> None:
        ctx = self.ctx
        with patch.object(flow_wiring, "PlannedCalendarSyncService") as sync_type:
            self.services.sync_service()
        run_lthr_for = sync_type.call_args.kwargs["run_lthr_for"]
        ctx.run_lthr.resolver.assert_not_called()

        unit = {"id": "unit"}
        self.assertIs(
            run_lthr_for(unit), ctx.run_lthr.resolver.return_value.return_value
        )
        ctx.run_lthr.resolver.return_value.assert_called_once_with(unit)


class WorkoutLibraryBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.services = flow_wiring.build_workout_library_sync(self.ctx)

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.config.assert_not_called()
        self.ctx.database.assert_not_called()
        self.ctx.wahoo.workout_export.assert_not_called()
        self.ctx.planning_workflows.calendar_conflict_service.assert_not_called()

    def test_the_sync_service_gets_fresh_state_and_a_deferred_client(self) -> None:
        ctx = self.ctx
        ctx.provider_transport.intervals_client.return_value.get_workout_library.return_value = []
        with (
            patch.object(flow_wiring, "WorkoutLibrarySyncStateService") as state_type,
            patch.object(flow_wiring, "WorkoutLibrarySyncService") as sync_type,
        ):
            self.assertIs(self.services.sync_service(), sync_type.return_value)
            self.services.sync_service()

        self.assertEqual(2, state_type.call_count)
        self.assertEqual(2, sync_type.call_count)
        args = sync_type.call_args.args
        self.assertEqual(ctx.config.return_value, args[0])
        port = args[1]
        self.assertIsInstance(port, IntervalsWorkoutExport)
        self.assertTrue(port.capabilities.library)
        ctx.provider_transport.intervals_client.assert_not_called()
        port.library_list()
        ctx.provider_transport.intervals_client.assert_called_once_with()
        self.assertIs(args[2], state_type.return_value)
        self.assertIs(args[3], ctx.planning_workflows.calendar_conflict_service())
        self.assertIs(
            sync_type.call_args.kwargs["local_today"](),
            ctx.clock.now.return_value.date.return_value,
        )

    def test_the_state_service_reads_the_manager_and_the_clock(self) -> None:
        ctx = self.ctx
        with patch.object(flow_wiring, "WorkoutLibrarySyncStateService") as state_type:
            self.assertIs(self.services.sync_state_service(), state_type.return_value)

        args = state_type.call_args.args
        self.assertEqual(
            (ctx.database.return_value, ctx.redactor, ctx.key_values),
            args[:3],
        )
        self.assertIs(args[3], runtime_clock.utc_now)
        # The threshold resync moved to the Garmin push state (#2546).
        self.assertEqual(4, len(args))

    def test_the_export_port_selects_a_registered_target_only(self) -> None:
        ctx = self.ctx
        self.assertIsInstance(
            self.services.export_port(ProviderId.INTERVALS), IntervalsWorkoutExport
        )
        self.assertIsInstance(self.services.export_port(), IntervalsWorkoutExport)
        with self.assertRaises(ValueError):
            self.services.export_port(ProviderId.GARMIN)
        ctx.provider_transport.intervals_client.assert_not_called()
        ctx.wahoo.workout_export.assert_not_called()

    def test_the_wahoo_target_comes_from_the_wahoo_owner_per_call(self) -> None:
        ctx = self.ctx
        ctx.wahoo.workout_export.return_value.capabilities.library = True

        port = self.services.export_port(ProviderId.WAHOO)

        self.assertIs(port, ctx.wahoo.workout_export.return_value)
        ctx.wahoo.workout_export.assert_called_once_with()


class SelectedWorkoutBuilderTests(unittest.TestCase):
    def test_the_service_uses_fresh_services_and_the_given_gate(self) -> None:
        ctx = Mock(name="context")
        calendar = Mock(name="planned calendar")
        gate = Mock(name="gate")
        services = flow_wiring.build_selected_workout_sync(
            ctx, planned_calendar=calendar, resync_gate=gate
        )
        ctx.workout_library_sync.sync_service.assert_not_called()
        calendar.sync_service.assert_not_called()

        with patch.object(flow_wiring, "SelectedWorkoutSyncService") as service_type:
            self.assertIs(services.service(), service_type.return_value)
            services.service()

        self.assertEqual(
            (
                ctx.config.return_value,
                ctx.database.return_value,
                ctx.workout_library_sync.sync_service.return_value,
                calendar.sync_service.return_value,
                calendar.repair_service.return_value,
                ctx.redactor.redact_text,
            ),
            service_type.call_args.args,
        )
        self.assertEqual({"provider_resync_gate": gate}, service_type.call_args.kwargs)
        self.assertEqual(2, ctx.workout_library_sync.sync_service.call_count)
        self.assertEqual(2, calendar.repair_service.call_count)


class ExternalCalendarBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.services = flow_wiring.build_external_calendar(self.ctx)

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.sync_persistence.daily_markers.assert_not_called()
        self.ctx.provider_sync.operation_observer.assert_not_called()

    def test_the_reader_follows_the_manager_and_the_local_date(self) -> None:
        ctx = self.ctx
        with patch.object(flow_wiring, "ExternalCalendarReader") as reader_type:
            self.assertIs(self.services.reader(), reader_type.return_value)
            self.services.reader()

        self.assertEqual(2, ctx.database.call_count)
        manager, local_date = reader_type.call_args.args
        self.assertIs(manager, ctx.database.return_value)
        self.assertIs(local_date(), ctx.clock.now.return_value.date.return_value)

    def test_the_sync_service_reads_the_live_owners_per_call(self) -> None:
        ctx = self.ctx
        with patch.object(flow_wiring, "ExternalCalendarSyncService") as service_type:
            self.assertIs(self.services.sync_service(), service_type.return_value)
            self.services.sync_service()

        self.assertEqual(2, ctx.sync_persistence.daily_markers.call_count)
        service_type.assert_called_with(
            ctx.config.return_value,
            ctx.database.return_value,
            ctx.key_values,
            ctx.sync_persistence.daily_markers.return_value,
            ctx.provider_sync.operation_observer.return_value,
            ctx.planning_workflows.adaptive_replan_preview_service.return_value,
            runtime_events.STATE_EVENT_BUFFER,
            ctx.logger,
            ctx.redactor.redact_text,
            ctx.clock.now,
            runtime_clock.utc_now,
            ctx.app_version,
            lock=external_calendar.shared_external_calendar_sync_lock(),
        )


class MetricExportBuilderTests(unittest.TestCase):
    def test_the_thresholds_read_the_live_clock_profile_and_canonical_owner(
        self,
    ) -> None:
        ctx = Mock(name="context")
        thresholds = flow_wiring.build_export_thresholds(ctx)
        ctx.canonical_read.assert_not_called()

        with (
            patch.object(flow_wiring, "read_export_thresholds") as read,
            patch.object(flow_wiring, "resolve_reader") as resolve,
            patch.object(flow_wiring, "preferences_from_profile") as preferences,
            patch.object(flow_wiring, "CanonicalTableReader") as table_reader,
        ):
            self.assertIs(thresholds("db"), read.return_value)

        resolve.assert_called_once_with(ctx.canonical_read, "db")
        ctx.athlete.profile.return_value.get_from_db.assert_called_once_with("db")
        read.assert_called_once_with(
            resolve.return_value,
            "db",
            as_of=ctx.clock.now.return_value.date.return_value,
            preferences=preferences.return_value,
            configurations=table_reader.return_value.zone_configurations.return_value,
        )

    def test_the_service_opens_a_client_only_for_a_confirmed_write(self) -> None:
        ctx = Mock(name="context")
        shared = Mock(name="thresholds")
        with patch.object(flow_wiring, "MetricExportService") as service_type:
            service = flow_wiring.build_metric_export(ctx, thresholds=shared)

        self.assertIs(service, service_type.return_value)
        args, kwargs = service_type.call_args
        self.assertIs(args[0], ctx.database)
        self.assertIs(args[1](), ctx.canonical_read)
        self.assertEqual({ProviderId.INTERVALS}, set(args[2]))
        self.assertIs(kwargs["thresholds"], shared)
        self.assertIs(kwargs["today"](), ctx.clock.now.return_value.date.return_value)
        self.assertEqual(UTC, kwargs["utc_now"]().tzinfo)
        self.assertIsInstance(kwargs["utc_now"](), datetime)
        ctx.provider_transport.intervals_client.assert_not_called()

        with patch.object(flow_wiring, "IntervalsMetricExport") as export:
            self.assertIs(args[2][ProviderId.INTERVALS](), export.return_value)
        export.call_args.args[0]()
        ctx.provider_transport.intervals_client.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
