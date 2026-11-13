"""The executor, configured-check and scheduler builders read the live owners (#2101)."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import ANY, MagicMock, Mock, patch

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.sync import execution_wiring, scheduler, scheduler_wiring
from backend.sync.garmin_service import GARMIN_AUTOMATIC_SYNC_DAYS
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID
from backend.sync.wiring import SyncWindow

WINDOW = SyncWindow({GARMIN_ID: 84, WAHOO_ID: 84}, -1, 90, date(2020, 1, 1))


class SyncJobExecutionBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.selected = Mock(name="selected workout sync")
        self.competitions = Mock(name="competition sync")
        self.weather = Mock(name="weather sync")
        self.gate = ProviderResyncGate("Intervals.icu")
        self.after_job = Mock(name="after job")
        self.services = execution_wiring.build_sync_job_execution(
            self.ctx,
            window=WINDOW,
            selected_workout_sync_service=self.selected,
            competition_sync_service=self.competitions,
            weather_sync_service=self.weather,
            intervals_resync_gate=self.gate,
            after_job=self.after_job,
        )

    def test_building_resolves_no_owner(self) -> None:
        ctx = self.ctx
        for lazy in (self.selected, self.competitions, self.weather):
            lazy.assert_not_called()
        ctx.garmin.sync_service.assert_not_called()
        ctx.wahoo.sync_service.assert_not_called()
        ctx.sync_job_queue.outcome_service.assert_not_called()
        ctx.external_calendar.sync_service.assert_not_called()

    def test_the_executor_resolves_the_shared_owners_and_the_outcome_service(
        self,
    ) -> None:
        ctx = self.ctx
        with patch.object(execution_wiring.sync_executor, "SyncJobExecutor") as made:
            executor = self.services.executor()

        self.assertIs(executor, made.return_value)
        kwargs = made.call_args.kwargs
        self.assertIs(kwargs["outcome_service"], ctx.sync_job_queue.outcome_service())
        self.assertEqual(-1, kwargs["all_sync_days"])
        self.assertIs(kwargs["after_job"], self.after_job)
        self.assertEqual(
            {INTERVALS_ID, GARMIN_ID, WEATHER_ID, CALENDAR_ID, WAHOO_ID},
            set(kwargs["job_owners"]),
        )
        ctx.external_calendar.sync_service.assert_called_once_with()
        self.weather.assert_called_once_with()
        ctx.wahoo.sync_service.assert_called_once_with()
        ctx.wahoo.plan_push_service.assert_called_once_with()
        ctx.wahoo.stream_backfill_service.assert_called_once_with()
        # The Intervals.icu and Garmin owners are built per job, not here.
        self.selected.assert_not_called()
        self.competitions.assert_not_called()
        ctx.garmin.sync_service.assert_not_called()

    def test_the_historical_owner_reads_the_window_clock_and_state(self) -> None:
        ctx = self.ctx
        with patch.object(
            execution_wiring.sync_executor, "HistoricalSyncJobOwner"
        ) as owner:
            self.services.executor()

        owner.assert_called_with(
            sync_state_repository=ctx.sync_persistence.state_repository.return_value,
            queue_service=ctx.sync_job_queue.service.return_value,
            local_now=ctx.clock.now,
            sync_period_defaults=WINDOW.sync_period_defaults,
            all_sync_days=-1,
            sync_chunk_days=90,
            sync_earliest_date=date(2020, 1, 1),
        )

    def test_the_intervals_and_garmin_owners_are_rebuilt_for_each_job(self) -> None:
        ctx = self.ctx
        with patch.object(execution_wiring.sync_executor, "SyncJobExecutor") as made:
            self.services.executor()
        owners = made.call_args.kwargs["job_owners"]

        with (
            patch.object(execution_wiring.sync_executor, "IntervalsSyncJobOwner") as i,
            patch.object(execution_wiring.sync_executor, "GarminSyncJobOwner") as g,
        ):
            for _ in range(2):
                owners[INTERVALS_ID]._build()
                owners[GARMIN_ID]._build()

        self.assertEqual(2, self.selected.call_count)
        self.assertEqual(2, self.competitions.call_count)
        self.assertEqual(2, ctx.provider_sync.operation_observer.call_count)
        self.assertEqual(2, ctx.nutrition.intervals_sync_service.call_count)
        i.assert_called_with(
            selected_workout_sync_service=self.selected.return_value,
            competition_sync_service=self.competitions.return_value,
            sync_operation_observer=ctx.provider_sync.operation_observer.return_value,
            intervals_resync_gate=self.gate,
        )
        self.assertEqual(2, ctx.garmin.sync_service.call_count)
        self.assertEqual(2, ctx.garmin.strength_push_service.call_count)
        g.assert_called_with(
            historical_sync=ANY,
            garmin_sync_service=ctx.garmin.sync_service.return_value,
            morning_body_battery_service=ctx.morning_body_battery_service.return_value,
            garmin_fixture_loader=ctx.garmin.fixture_loader.return_value,
            all_sync_days=-1,
            activity_detail_service=ctx.garmin.activity_detail_service.return_value,
            wellness_history_service=ctx.garmin.wellness_history_service.return_value,
            stream_backfill_service=ctx.garmin.stream_backfill_service.return_value,
        )


class ProviderConfiguredChecksTests(unittest.TestCase):
    def test_each_check_reads_the_live_owner_when_asked(self) -> None:
        ctx = Mock(name="context")
        checks = execution_wiring.provider_configured_checks(ctx)

        self.assertEqual(
            {INTERVALS_ID, GARMIN_ID, WEATHER_ID, CALENDAR_ID, WAHOO_ID}, set(checks)
        )
        ctx.config.assert_not_called()
        ctx.garmin.sync_service.assert_not_called()

        ctx.config.return_value.intervals_api_key = ""
        ctx.config.return_value.calendar_ical_url = "https://example.invalid/a.ics"
        ctx.garmin.sync_service.return_value.configured.return_value = False
        ctx.wahoo.sync_service.return_value.configured.return_value = True
        self.assertFalse(checks[INTERVALS_ID]())
        self.assertTrue(checks[CALENDAR_ID]())
        self.assertFalse(checks[GARMIN_ID]())
        self.assertTrue(checks[WAHOO_ID]())
        ctx.config.return_value.intervals_api_key = "key"
        ctx.garmin.sync_service.return_value.configured.return_value = True
        self.assertTrue(checks[INTERVALS_ID]())
        self.assertTrue(checks[GARMIN_ID]())

    def test_the_weather_check_reads_the_profile_location(self) -> None:
        ctx = Mock(name="context")
        checks = execution_wiring.provider_configured_checks(ctx)
        with patch.object(execution_wiring, "WeatherSchedulePolicy") as policy:
            self.assertIs(checks[WEATHER_ID](), policy.return_value.configured())

        policy.assert_called_once_with(ctx.athlete.profile.return_value)

    def test_configured_for_job_keeps_the_table_order(self) -> None:
        checks = {
            INTERVALS_ID: lambda: True,
            GARMIN_ID: lambda: False,
            WEATHER_ID: lambda: True,
            CALENDAR_ID: lambda: True,
            WAHOO_ID: lambda: True,
        }

        self.assertEqual(
            (INTERVALS_ID, WAHOO_ID),
            execution_wiring.configured_for_job(checks, "plan_push"),
        )
        self.assertEqual(
            (WEATHER_ID, CALENDAR_ID, WAHOO_ID),
            execution_wiring.configured_for_job(checks, "refresh"),
        )


class SyncSchedulerBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock(name="context")
        self.weather = Mock(name="weather sync")
        self.retry_held = Mock(name="retry held")
        self.sleep = Mock(name="sleep")
        self.gates = (ProviderResyncGate("Garmin"), ProviderResyncGate("Wahoo"))
        self.services = scheduler_wiring.build_sync_schedulers(
            self.ctx,
            window=WINDOW,
            weather_sync=self.weather,
            garmin_resync_gate=self.gates[0],
            wahoo_resync_gate=self.gates[1],
            retry_held=self.retry_held,
            sleep=self.sleep,
        )

    def test_building_resolves_no_owner(self) -> None:
        ctx = self.ctx
        ctx.config.assert_not_called()
        ctx.garmin.sync_service.assert_not_called()
        ctx.garmin.change_check.assert_not_called()
        ctx.sync_job_queue.service.assert_not_called()
        self.weather.assert_not_called()

    def test_policies_are_built_fresh_with_the_provider_options(self) -> None:
        ctx = self.ctx
        ctx.config.return_value.calendar_ical_url = "https://example.invalid/a.ics"
        with (
            patch.object(scheduler_wiring, "build_schedule_policies") as build,
            patch.object(scheduler_wiring, "WahooSchedulePolicy") as wahoo,
            patch.object(scheduler_wiring.scheduler, "StartupSyncScheduler") as startup,
        ):
            self.assertIs(self.services.startup_scheduler(), startup.return_value)
            self.services.startup_scheduler()

        self.assertEqual(2, build.call_count)
        build.assert_called_with(
            profile=ctx.athlete.profile.return_value,
            garmin=ctx.garmin.sync_service.return_value,
            calendar_enabled=True,
            garmin_automatic_sync_days=GARMIN_AUTOMATIC_SYNC_DAYS,
            garmin_resync_gate=self.gates[0],
            garmin_change_check=ctx.garmin.change_check.return_value,
            weather_refresh_due=ANY,
            wahoo=wahoo.return_value,
        )
        wahoo.assert_called_with(
            configured=ANY,
            sync_state=ctx.sync_persistence.state_repository.return_value,
            sync_period_defaults=WINDOW.sync_period_defaults,
            all_sync_days=-1,
            resync_gate=self.gates[1],
        )
        options = build.call_args.kwargs
        self.assertIs(options["weather_refresh_due"](), self.weather().refresh_due())
        wahoo.call_args.kwargs["configured"]()
        ctx.wahoo.sync_service.return_value.configured.assert_called_once_with()
        startup.assert_called_with(
            ctx.sync_job_queue.service.return_value,
            ctx.sync_persistence.state_repository.return_value,
            config=scheduler.StartupSyncSchedulerConfig(
                sync_chunk_days=90, sync_earliest_date=date(2020, 1, 1)
            ),
            schedule_policies=build.return_value,
        )

    def test_the_daily_scheduler_carries_the_hold_marker_and_resumer(self) -> None:
        ctx = self.ctx
        with (
            patch.object(scheduler_wiring, "build_schedule_policies") as build,
            patch.object(scheduler_wiring.scheduler, "DailySyncScheduler") as daily,
            patch.object(scheduler_wiring, "BackfillChainResumer") as resumer,
        ):
            self.assertIs(self.services.daily_scheduler(), daily.return_value)

        daily.assert_called_once_with(
            ctx.sync_job_queue.service.return_value,
            ctx.sync_persistence.daily_markers.return_value,
            ctx.maintenance,
            config=scheduler.DailySyncSchedulerConfig(
                auto_update_label=scheduler.AUTO_UPDATE_LABEL
            ),
            schedule_policies=build.return_value,
            retry_held=self.retry_held,
            backfill_resumer=resumer.return_value.resume,
        )

    def test_the_backfill_resumer_gets_the_window_and_fresh_policies(self) -> None:
        ctx = self.ctx
        with (
            patch.object(scheduler_wiring, "build_schedule_policies") as build,
            patch.object(scheduler_wiring, "BackfillChainResumer") as resumer,
        ):
            self.assertIs(self.services.backfill_resumer(), resumer.return_value)

        resumer.assert_called_once_with(
            ctx.sync_job_queue.service.return_value,
            ctx.sync_persistence.state_repository.return_value,
            build.return_value,
            chunk_days=90,
            earliest_date=date(2020, 1, 1),
        )

    def test_the_loop_reads_the_morning_reading_and_the_change_check(self) -> None:
        ctx = self.ctx
        with (
            patch.object(scheduler_wiring.scheduler, "DailySyncLoop") as loop,
            patch.object(scheduler_wiring.scheduler, "DailySyncScheduler"),
        ):
            self.assertIs(self.services.daily_loop(), loop.return_value)

        kwargs = loop.call_args.kwargs
        self.assertIs(loop.call_args.args[1], ctx.morning_body_battery_service())
        self.assertIs(kwargs["sleep"], self.sleep)
        self.assertIs(kwargs["logger"], ctx.logger)
        self.assertIs(
            kwargs["housekeeping"], ctx.sync_job_queue.service().prune_finished
        )
        ctx.garmin.change_check.return_value.morning_due.return_value = True
        self.assertTrue(kwargs["morning_due"]())

    def test_the_wal_checkpoint_runs_as_background_work_under_the_gate(self) -> None:
        ctx = self.ctx
        ctx.maintenance = MagicMock(name="maintenance gate")
        with (
            patch.object(scheduler_wiring.scheduler, "DailySyncLoop") as loop,
            patch.object(scheduler_wiring.scheduler, "DailySyncScheduler"),
            patch.object(scheduler_wiring, "background_writer") as writer,
        ):
            self.services.daily_loop()
            loop.call_args.kwargs["wal_checkpoint"]()

        ctx.maintenance.operation.assert_called_once_with()
        writer.assert_called_once_with()
        ctx.database.return_value.checkpoint_wal.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
