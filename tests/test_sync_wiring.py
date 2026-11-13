"""The sync builders read the live owners from the context (#2101)."""

from __future__ import annotations

import unittest
from datetime import UTC
from unittest.mock import ANY, MagicMock, Mock, patch

from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync import freshness, wiring
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


if __name__ == "__main__":
    unittest.main()
