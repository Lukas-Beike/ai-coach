"""The sync builders read the live owners from the context (#2101)."""

from __future__ import annotations

import unittest
from datetime import UTC, date
from pathlib import Path
from unittest.mock import ANY, MagicMock, Mock, patch

from support import garmin_services

from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync import freshness, garmin, garmin_wiring, wahoo_wiring, wiring
from backend.sync.gates import resetting_providers
from backend.sync.worker import shared_sync_job_wake_event


class SyncPersistenceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.services = wiring.build_sync_persistence(self.ctx)

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.clock.now.assert_not_called()

    def test_services_resolve_the_current_manager_on_each_call(self) -> None:
        ctx = self.ctx
        ctx.database.side_effect = [Mock(name="first"), Mock(name="second")]
        with patch.object(wiring, "SyncStateRepository") as state_factory:
            self.assertIs(self.services.state_repository(), state_factory.return_value)
            self.services.state_repository()
        managers = [call.args[0] for call in state_factory.call_args_list]
        self.assertIsNot(managers[0], managers[1])
        state_factory.assert_called_with(
            managers[1], ctx.key_values, runtime_clock.utc_now
        )

    def test_daily_markers_use_the_athlete_clock(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "DailySyncMarkerService") as marker_factory:
            markers = self.services.daily_markers()

        self.assertIs(markers, marker_factory.return_value)
        marker_factory.assert_called_once_with(
            ctx.database.return_value, ctx.key_values, ctx.clock.now
        )


class ProviderSyncBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.services = wiring.build_provider_sync(self.ctx)

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.config.assert_not_called()

    def test_the_tracker_comes_from_the_shared_cache(self) -> None:
        ctx = self.ctx
        with patch.object(wiring.refresh, "PROVIDER_REFRESH_TRACKER_CACHE") as cache:
            tracker = self.services.refresh_tracker()

        self.assertIs(tracker, cache.get.return_value)
        cache.get.assert_called_once_with(
            ctx.database.return_value,
            runtime_events.STATE_EVENT_BUFFER,
            ANY,
            ctx.ids,
            retention_days=freshness.PROVIDER_REFRESH_RETENTION_DAYS,
            max_rows=freshness.PROVIDER_REFRESH_MAX_ROWS,
            retry_base_seconds=900,
            retry_max_seconds=21600,
        )
        self.assertEqual(cache.get.call_args.args[2]().tzinfo, UTC)

    def test_the_observer_wraps_the_shared_tracker_and_gate(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring.refresh, "PROVIDER_REFRESH_TRACKER_CACHE") as cache,
            patch.object(wiring.observation, "SyncOperationObserver") as observer,
        ):
            result = self.services.operation_observer()

        self.assertIs(result, observer.return_value)
        observer.assert_called_once_with(
            cache.get.return_value, ctx.maintenance, ctx.logger
        )

    def test_freshness_reads_the_live_config_and_manager(self) -> None:
        ctx = self.ctx
        with patch.object(freshness, "ProviderFreshnessService") as service:
            self.services.freshness_service()
            self.services.freshness_service()

        service.assert_called_with(
            ctx.config.return_value, ctx.database.return_value, ctx.key_values, ANY
        )
        self.assertEqual(ctx.config.call_count, 2)


class SyncJobQueueBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.markers = Mock(name="daily_sync_markers")
        self.services = wiring.build_sync_job_queue(
            self.ctx, all_sync_days=-1, daily_sync_markers=self.markers
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.coach_background_jobs.job_store.assert_not_called()
        self.markers.assert_not_called()

    def test_the_store_is_fresh_and_asks_the_coach_when_it_is_busy(self) -> None:
        ctx = self.ctx
        with patch.object(wiring.jobs, "SyncJobStore") as store:
            self.assertIs(self.services.store(), store.return_value)

        store.assert_called_once_with(
            ctx.database.return_value,
            runtime_clock.utc_now,
            ctx.ids,
            foreground_busy=ANY,
            held_providers=resetting_providers,
        )
        busy = store.call_args.kwargs["foreground_busy"]
        self.assertIs(busy(), ctx.coach_background_jobs.job_store().busy())

    def test_the_service_shares_the_event_wake_and_marker_owners(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring.jobs, "SyncJobStore") as store,
            patch.object(wiring.queue, "SyncJobQueueService") as service,
        ):
            self.assertIs(self.services.service(), service.return_value)

        service.assert_called_once_with(
            store.return_value,
            runtime_events.STATE_EVENT_BUFFER,
            ctx.maintenance,
            shared_sync_job_wake_event(),
            -1,
            self.markers.return_value,
        )

    def test_the_outcome_service_shares_the_store_events_and_wake(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring.jobs, "SyncJobStore") as store,
            patch.object(wiring.job_outcomes, "SyncJobOutcomeService") as service,
        ):
            self.assertIs(self.services.outcome_service(), service.return_value)

        service.assert_called_once_with(
            store.return_value,
            runtime_events.STATE_EVENT_BUFFER,
            shared_sync_job_wake_event(),
            ctx.redactor.redact_text,
            ctx.logger,
            ANY,
            900,
            21600,
        )


class SyncWorkerBuilderTests(unittest.TestCase):
    def test_the_worker_is_created_on_demand_over_the_queue_store(self) -> None:
        ctx, executor = Mock(name="context"), Mock(name="executor")
        services = wiring.build_sync_worker(ctx, executor=executor)
        ctx.sync_job_queue.store.assert_not_called()
        executor.assert_not_called()

        with patch.object(wiring.sync_worker, "SyncJobWorker") as worker:
            self.assertIs(services.create(), worker.return_value)

        store = ctx.sync_job_queue.store.return_value
        worker.assert_called_once_with(
            store,
            executor.return_value,
            ctx.maintenance,
            1.0,
            wake_event=shared_sync_job_wake_event(),
            requeue_unowned=store.requeue_unowned_running,
        )


class SyncCommandBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.intervals_client = Mock(name="intervals_client")
        self.refreshes = Mock(name="synchronous_refreshes")
        self.after_refresh = Mock(name="after_refresh")
        self.services = wiring.build_sync_commands(
            self.ctx,
            intervals_client=self.intervals_client,
            synchronous_refreshes=self.refreshes,
            after_refresh=self.after_refresh,
            training_change_limit=24,
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.planning.competition.assert_not_called()
        self.ctx.sync_job_queue.service.assert_not_called()
        self.refreshes.assert_not_called()

    def test_authority_uses_manager_library_state_revision_and_clock(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "PlanningAuthorityService") as factory:
            self.assertIs(self.services.authority(), factory.return_value)

        factory.assert_called_once_with(
            ctx.database.return_value,
            ctx.workout_library_sync.sync_state_service.return_value,
            ctx.planning_revision,
            runtime_clock.utc_now,
            local_today=ANY,
        )
        today = factory.call_args.kwargs["local_today"]
        self.assertIs(today(), ctx.clock.now.return_value.date.return_value)

    def test_provider_refresh_resolves_the_queue_and_refreshes_per_call(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "ProviderRefreshCommandService") as factory:
            self.assertIs(self.services.provider_refresh(), factory.return_value)
            self.services.provider_refresh()

        factory.assert_called_with(
            ctx.sync_job_queue.service.return_value,
            self.refreshes.return_value,
            self.after_refresh,
        )
        self.assertEqual(self.refreshes.call_count, 2)

    def test_illness_pause_reads_the_live_config_and_planning_owners(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "IllnessPauseSyncService") as factory:
            self.assertIs(self.services.illness_pause(), factory.return_value)

        factory.assert_called_once_with(
            ctx.config.return_value,
            self.intervals_client.return_value,
            adaptive_replan_apply_service=ctx.planning.adaptive_apply.return_value,
            competition_service=ctx.planning.competition.return_value,
            adaptive_replan_preview_service=(
                ctx.planning_workflows.adaptive_replan_preview_service.return_value
            ),
            redactor=ctx.redactor,
            today=ANY,
        )

    def test_conflicts_and_plan_push_share_the_queue(self) -> None:
        ctx = self.ctx
        queue = ctx.sync_job_queue.service.return_value
        with (
            patch.object(wiring, "SyncConflictCommandService") as conflicts,
            patch.object(wiring, "PlanPushCommandService") as push,
        ):
            self.services.conflicts()
            self.services.plan_push()

        conflicts.assert_called_once_with(ctx.planning.competition.return_value, queue)
        self.assertIs(queue, push.call_args.args[0])
        # The Garmin push needs an SDK login: the second argument checks it (#2522).
        garmin_writable = push.call_args.args[1]
        reader = MagicMock()
        reader.__enter__.return_value = "db"
        ctx.database.return_value.reader.return_value = reader
        with patch.object(wiring, "sdk_write_ready", return_value=True) as ready:
            self.assertTrue(garmin_writable())
        self.assertIs(ctx.config.return_value, ready.call_args.args[0])
        ready.call_args.args[1]("key")
        ctx.key_values.get.assert_called_once_with("db", "key")

    def test_plan_sync_and_repair_share_a_fresh_authority(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring, "PlanningAuthorityService") as authority,
            patch.object(wiring, "PlanPushCommandService") as push,
            patch.object(wiring, "StructuredPlanSyncService") as plan_sync,
            patch.object(wiring, "PlanRepairManifestService") as repair,
        ):
            self.services.structured_plan_sync()
            self.services.repair_manifest()

        plan_sync.assert_called_once_with(
            ctx.database.return_value,
            authority.return_value,
            push.return_value,
            24,
        )
        repair.assert_called_once_with(
            ctx.database.return_value, authority.return_value
        )


class GarminBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.tokens = Mock(name="tokens")
        self.run_zones = Mock(name="run_zones")
        self.services = garmin_services(
            self.ctx, tokens=self.tokens, run_zones=self.run_zones
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.config.assert_not_called()
        self.ctx.database.assert_not_called()
        self.ctx.clock.now.assert_not_called()

    def test_services_are_fresh_and_read_the_live_configuration(self) -> None:
        ctx = self.ctx
        ctx.config.side_effect = [Mock(name="first"), Mock(name="second")]
        with patch.object(garmin, "GarminFixtureLoader") as loader:
            self.assertIs(self.services.fixture_loader(), loader.return_value)
            self.services.fixture_loader()

        configs = [call.args[0] for call in loader.call_args_list]
        self.assertIsNot(configs[0], configs[1])
        loader.assert_called_with(
            configs[1],
            Path("."),
            ctx.clock.now,
            garmin_wiring.runtime_clock.utc_now,
            date(2000, 1, 1),
            -1,
        )
        self.assertIsNot(
            self.services.payload_service(), self.services.payload_service()
        )

    def test_the_remote_reader_gets_the_tokens_and_the_live_owners(self) -> None:
        ctx = self.ctx
        with (
            patch.object(garmin_wiring, "GarminRemoteReader") as reader,
            patch.object(garmin, "GarminSyncStateService") as state,
        ):
            self.assertIs(self.services.remote_reader(), reader.return_value)

        args = reader.call_args.args
        self.assertEqual(
            args[:5],
            (
                ctx.config.return_value,
                args[1],
                state.return_value,
                ctx.diagnostic_capture,
                ctx.redactor.redact_text,
            ),
        )
        self.assertIs(args[5], ctx.logger)
        self.assertEqual(args[8:11], (date(2000, 1, 1), 90, -1))
        self.assertIs(reader.call_args.kwargs["garmin_tokens"], self.tokens)

    def test_the_strength_push_reads_the_run_zones_it_was_given(self) -> None:
        with (
            patch(
                "backend.sync.garmin_strength_push.GarminStrengthPushService"
            ) as push,
            patch.object(garmin_wiring, "GarminSyncSource"),
            patch.object(garmin_wiring, "GarminRemoteReader"),
        ):
            self.assertIs(self.services.strength_push_service(), push.return_value)

        self.assertIs(push.call_args.kwargs["run_zones"], self.run_zones)
        self.assertIs(push.call_args.kwargs["database_manager"], self.ctx.database)
        self.run_zones.assert_not_called()

    def test_one_change_check_and_one_reader_per_configuration(self) -> None:
        ctx = self.ctx
        ctx.config.side_effect = None
        with (
            patch.object(garmin_wiring, "GarminChangeCheck") as check,
            patch.object(garmin_wiring, "GarminRemoteReader") as reader,
            patch.object(garmin, "GarminFixtureLoader") as loader,
        ):
            loader.return_value.path.return_value = None
            self.assertIs(self.services.change_check(), check.return_value)
            self.assertIs(self.services.change_check(), check.return_value)
            check.assert_called_once()

            client = self.services.change_personal_client()
            self.assertIs(client, reader.return_value.personal_client.return_value)
            self.services.change_personal_client()
            reader.assert_called_once()

            ctx.config.return_value = Mock(name="saved configuration")
            self.services.change_personal_client()
            self.assertEqual(reader.call_count, 2)

            loader.return_value.path.return_value = "fixture.json"
            self.assertIsNone(self.services.change_personal_client())
            self.assertEqual(reader.call_count, 2)

    def test_the_change_check_reads_the_athlete_clock_and_markers(self) -> None:
        markers = Mock(name="markers")
        services = garmin_services(self.ctx, daily_sync_markers=lambda: markers)
        with patch.object(garmin_wiring, "GarminChangeCheck") as check:
            services.change_check()

        kwargs = check.call_args.kwargs
        self.assertIs(kwargs["local_now"], self.ctx.clock.now)
        self.assertIs(kwargs["logger"], self.ctx.logger)
        kwargs["last_refresh"]()
        markers.last_success.assert_called_once_with("garmin")

    def test_projections_read_the_canonical_owner_when_used(self) -> None:
        ctx = self.ctx
        with patch.object(garmin_wiring, "GarminProjectionService") as projection:
            self.assertIs(self.services.projection_service(), projection.return_value)

        sources = projection.call_args.kwargs["canonical"]
        ctx.canonical_read = Mock(name="late canonical read")
        self.assertIs(sources.observations(), ctx.canonical_read)
        self.assertIs(sources.activity_summaries(), ctx.canonical_read)
        self.assertIs(projection.call_args.args[4], ctx.morning_body_battery_service())


class WahooBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.registry = Mock(name="secret registry")
        self.connected = Mock(name="on connected")
        self.connection = wahoo_wiring.build_wahoo_connection(
            self.ctx, secret_registry=self.registry, on_connected=self.connected
        )
        self.opener = Mock(name="opener")
        self.gate = Mock(name="gate")
        self.markers = Mock(name="markers")
        self.services = wahoo_wiring.build_wahoo_sync(
            self.ctx,
            connection=self.connection.service,
            daily_markers=self.markers,
            resync_gate=self.gate,
            export_thresholds=Mock(name="thresholds"),
            history_earliest_date=date(2020, 1, 1),
            fit_opener=lambda: self.opener,
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.config.assert_not_called()
        self.ctx.database.assert_not_called()
        self.ctx.provider_transport.json_http_client.assert_not_called()

    def test_one_connection_service_reads_the_live_owners(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wahoo_wiring, "WahooConnectionService") as service,
            patch.object(wahoo_wiring, "WahooOAuthClient") as oauth,
        ):
            self.assertIs(self.connection.service(), service.return_value)
            self.assertIs(self.connection.service(), service.return_value)
            service.assert_called_once()
            kwargs = service.call_args.kwargs
            self.assertIs(kwargs["secret_registry"], self.registry)
            self.assertIs(kwargs["on_connected"], self.connected)
            self.assertIs(kwargs["config"], ctx.config)
            self.assertIs(kwargs["database_lock"](), ctx.database_lock)
            self.assertIs(kwargs["oauth"](), oauth.return_value)

        oauth.assert_called_once_with(
            ctx.config, ctx.provider_transport.json_http_client.return_value.request
        )

    def test_the_client_resolves_the_connection_on_each_call(self) -> None:
        ctx = self.ctx
        with patch.object(wahoo_wiring, "WahooClient") as client_factory:
            self.assertIs(self.services.client(), client_factory.return_value)
            self.services.client()

        # Each call resolves the transport and the connection again.
        self.assertEqual(2, client_factory.call_count)
        self.assertEqual(2, ctx.provider_transport.json_http_client.call_count)
        current = self.connection.service()
        client_factory.assert_called_with(
            request=ctx.provider_transport.json_http_client.return_value.request,
            access_token=current.access_token,
            refresh_access_token=current.refresh_access_token,
            invalidate_access_token=current.invalidate_access_token,
        )

    def test_the_sync_service_details_and_plan_push_are_shared(self) -> None:
        with (
            patch.object(wahoo_wiring, "WahooSyncService") as sync,
            patch.object(wahoo_wiring, "WahooActivityDetailImport") as details,
            patch.object(wahoo_wiring, "WahooPlanPushService") as push,
        ):
            self.assertIs(self.services.sync_service(), sync.return_value)
            self.assertIs(self.services.sync_service(), sync.return_value)
            self.assertIs(self.services.activity_detail_import(), details.return_value)
            self.assertIs(self.services.activity_detail_import(), details.return_value)
            self.assertIs(self.services.plan_push_service(), push.return_value)
            self.assertIs(self.services.plan_push_service(), push.return_value)

        for factory in (sync, details, push):
            factory.assert_called_once()
        kwargs = sync.call_args.kwargs
        self.assertIs(kwargs["connection"], self.connection.service)
        self.assertIs(kwargs["daily_markers"], self.markers)
        self.assertIs(kwargs["gate"], self.gate)
        self.assertEqual(kwargs["details"](), details.return_value)
        self.assertIs(push.call_args.kwargs["gate"], self.gate)
        self.assertIs(push.call_args.kwargs["configured"], sync.return_value.configured)

    def test_the_fit_download_asks_the_opener_per_request(self) -> None:
        with patch.object(wahoo_wiring, "download_wahoo_fit") as download:
            result = self.services.fit_download()("https://example.invalid/a.fit")

        self.assertIs(result, download.return_value)
        download.assert_called_once_with(
            "https://example.invalid/a.fit", opener=self.opener
        )

    def test_services_are_fresh_per_call(self) -> None:
        self.assertIsNot(self.services.workout_export(), self.services.workout_export())
        self.assertIsNot(self.services.library_state(), self.services.library_state())
        self.assertIsNot(
            self.services.stream_backfill_service(),
            self.services.stream_backfill_service(),
        )


if __name__ == "__main__":
    unittest.main()
