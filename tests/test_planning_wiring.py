"""The planning builders read their owners from the application context (#2100)."""

from __future__ import annotations

import unittest
import uuid
from datetime import date, timedelta
from typing import Any
from unittest.mock import Mock, patch

from backend.athlete.checkins import CHECKIN_TEXT_LIMITS
from backend.planning import adaptive as planning_adaptive
from backend.planning import changes as planning_changes
from backend.planning import wiring as planning_wiring
from backend.planning.adaptive_preview_service import AdaptivePreviewLimits
from backend.providers.calendar import EXTERNAL_CALENDAR_WINDOW_DAYS
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events


class PlanningDataBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock()
        self.services = planning_wiring.build_planning_data(self.ctx)

    def test_building_resolves_no_database_or_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.planning_workflows.calendar_conflict_service.assert_not_called()

    def test_each_service_is_fresh_over_the_active_manager(self) -> None:
        self.assertIsNot(self.services.competition(), self.services.competition())
        manager = self.ctx.database.return_value

        self.assertIs(manager, self.services.workout_library()._database_manager)
        self.assertIs(manager, self.services.training_plan()._database_manager)
        self.assertEqual(4, self.ctx.database.call_count)

    def test_competition_arguments(self) -> None:
        with patch.object(planning_wiring, "CompetitionService") as service:
            self.services.competition()

        manager, repository, utc_now, local_date = service.call_args.args
        self.assertIs(self.ctx.database.return_value, manager)
        self.assertIsNotNone(repository)
        self.assertIs(runtime_clock.utc_now, utc_now)
        self.assertIs(local_date(), self.ctx.clock.now.return_value.date.return_value)

    def test_training_plan_arguments(self) -> None:
        with patch.object(planning_wiring, "TrainingPlanService") as service:
            self.services.training_plan()

        manager, _repository, key_values, revisions, events, utc_now = (
            service.call_args.args
        )
        self.assertIs(self.ctx.database.return_value, manager)
        self.assertIs(self.ctx.key_values, key_values)
        self.assertIs(self.ctx.planning_revision, revisions)
        self.assertIs(runtime_events.STATE_EVENT_BUFFER, events)
        self.assertIs(runtime_clock.utc_now, utc_now)

    def test_planned_unit_arguments_and_late_edges(self) -> None:
        with patch.object(planning_wiring, "PlannedUnitService") as service:
            self.services.planned_unit()

        args = service.call_args.args
        self.assertEqual(9, len(args))
        (
            manager,
            revisions,
            utc_now,
            local_date,
            ids,
            redact,
            conflicts,
            publish,
            resync,
        ) = args
        self.assertIs(self.ctx.database.return_value, manager)
        self.assertIs(self.ctx.planning_revision, revisions)
        self.assertIs(runtime_clock.utc_now, utc_now)
        self.assertIs(local_date(), self.ctx.clock.now.return_value.date.return_value)
        self.assertIs(uuid.uuid4, ids)
        self.assertIs(self.ctx.redactor.redact_text, redact)
        self.assertIs(
            self.ctx.planning_workflows.calendar_conflict_service.return_value,
            conflicts,
        )
        with patch.object(runtime_events.STATE_EVENT_BUFFER, "publish") as published:
            publish()
        published.assert_called_once_with("coach", {"status": "changed"})
        self.assertIs(resync("db", ["payload"]), self.ctx.run_lthr.resync.return_value)
        self.ctx.run_lthr.resync.assert_called_once_with("db", ["payload"])

    def test_the_conflict_service_is_read_on_every_call(self) -> None:
        with patch.object(
            planning_wiring.planning_adaptive, "AdaptiveReplanApplyService"
        ) as service:
            self.services.adaptive_apply()
            self.services.adaptive_apply()

        self.assertEqual(
            2, self.ctx.planning_workflows.calendar_conflict_service.call_count
        )
        args = service.call_args.args
        self.assertIs(self.ctx.database.return_value, args[0])
        self.assertIs(self.ctx.planning_revision, args[2])
        self.assertIs(
            self.ctx.planning_workflows.calendar_conflict_service.return_value,
            args[5],
        )

    def test_workout_library_arguments(self) -> None:
        with patch.object(planning_wiring, "WorkoutLibraryService") as service:
            self.services.workout_library()

        manager, utc_now, ids, publish = service.call_args.args
        self.assertIs(self.ctx.database.return_value, manager)
        self.assertIs(runtime_clock.utc_now, utc_now)
        self.assertIs(uuid.uuid4, ids)
        with patch.object(runtime_events.STATE_EVENT_BUFFER, "publish") as published:
            publish()
        published.assert_called_once_with("coach", {"status": "changed"})


class PlanningWorkflowBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock()
        self.services = planning_wiring.build_planning_workflows(self.ctx)

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.external_calendar.reader.assert_not_called()
        self.ctx.weather.service.assert_not_called()

    def test_calendar_conflicts_read_the_calendar_on_every_call(self) -> None:
        with patch.object(planning_wiring, "CalendarConflictService") as service:
            self.services.calendar_conflict_service()
            self.services.calendar_conflict_service()

        self.assertEqual(2, self.ctx.external_calendar.reader.call_count)
        service.assert_called_with(
            self.ctx.database.return_value,
            self.ctx.external_calendar.reader.return_value,
        )

    def test_library_plan_service_publishes_the_coach_event(self) -> None:
        with patch.object(planning_wiring, "WorkoutLibraryPlanService") as service:
            self.services.workout_library_plan_service()

        manager, units, conflicts, publish = service.call_args.args
        self.assertIs(self.ctx.database.return_value, manager)
        self.assertIs(self.ctx.planning.planned_unit.return_value, units)
        self.assertIsNotNone(conflicts)
        with patch.object(runtime_events.STATE_EVENT_BUFFER, "publish") as published:
            publish()
        published.assert_called_once_with("coach", {"status": "changed"})

    def test_local_plan_creation_arguments(self) -> None:
        with patch.object(
            planning_wiring, "LocalTrainingPlanCreationService"
        ) as service:
            self.services.local_plan_creation_service()

        args = service.call_args.args
        self.assertEqual(10, len(args))
        self.assertIs(self.ctx.database.return_value, args[0])
        self.assertIs(self.ctx.planning.planned_unit.return_value, args[2])
        self.assertIs(self.ctx.planning.workout_library.return_value, args[3])
        self.assertIs(self.ctx.planning_revision, args[5])
        self.assertIs(args[6](), self.ctx.clock.now.return_value.date.return_value)
        self.assertIs(runtime_clock.utc_now, args[7])
        self.assertIs(uuid.uuid4, args[8])
        self.assertIs(self.ctx.logger, args[9])

    def test_daily_context_reads_the_athlete_and_the_canonical_reader(self) -> None:
        with patch.object(planning_wiring, "DailyPlanningContextService") as service:
            self.services.daily_planning_context_service()

        args = service.call_args.args
        self.assertEqual(10, len(args))
        self.assertIs(self.ctx.key_values, args[1])
        self.assertIs(self.ctx.athlete.checkin.return_value, args[2])
        self.assertIs(self.ctx.morning_body_battery_service.return_value, args[4])
        self.assertIs(self.ctx.athlete.activity_feedback.return_value, args[5])
        self.assertIs(args[8](), self.ctx.canonical_read)
        profile = self.ctx.athlete.profile.return_value
        profile.get_from_db.return_value = {}
        args[9]("db")
        profile.get_from_db.assert_called_once_with("db")
        profile.get.return_value = {"timezone": "Europe/Berlin"}
        self.assertEqual("Europe/Berlin", service.call_args.kwargs["timezone"]())
        profile.get.return_value = {}
        self.assertEqual("UTC", service.call_args.kwargs["timezone"]())

    def test_state_service_reads_the_late_owners(self) -> None:
        with patch.object(planning_wiring, "StructuredTrainingStateService") as service:
            self.services.structured_training_state_service()

        args = service.call_args.args
        self.assertIs(self.ctx.planning.competition.return_value, args[2])
        self.assertIs(self.ctx.planning.training_plan.return_value, args[3])
        self.assertIs(
            self.ctx.coach_conversation.dialogue_read_service.return_value.artifact_refs,
            args[4],
        )
        self.assertIs(self.ctx.sync_job_queue.service.return_value.list, args[5])

    def test_change_service_arguments(self) -> None:
        with (
            patch.object(
                planning_changes, "StructuredTrainingChangeService"
            ) as service,
            patch.object(
                planning_changes, "StructuredTrainingChangeValidator"
            ) as check,
            patch.object(planning_changes, "StructuredTrainingPlanResolver") as resolve,
        ):
            self.services.structured_training_change_service()

        args = service.call_args.args
        self.assertEqual(9, len(args))
        self.assertIs(check.return_value, args[1])
        self.assertIs(resolve.return_value, args[2])
        self.assertIs(self.ctx.planning.planned_unit.return_value, args[3])
        self.assertIs(self.ctx.planning_revision, args[4])
        self.assertIs(self.ctx.planning.training_plan.return_value, args[5])
        self.assertEqual(planning_changes.TRAINING_CHANGE_LIMIT, args[7])
        with patch.object(runtime_events.STATE_EVENT_BUFFER, "publish") as published:
            args[8]()
        published.assert_called_once_with("planning", {"status": "changed"})

    def test_replacement_service_arguments(self) -> None:
        with patch.object(
            planning_wiring, "StructuredTrainingPlanReplacementService"
        ) as service:
            self.services.structured_training_plan_replacement_service()

        args = service.call_args.args
        self.assertEqual(10, len(args))
        self.assertIs(self.ctx.planning_revision, args[2])
        self.assertIs(self.ctx.key_values, args[4])
        self.assertIs(self.ctx.planning.planned_unit.return_value, args[6])
        self.assertIs(runtime_clock.utc_now, args[8])
        self.assertIs(uuid.uuid4, args[9])

    def test_adaptive_preview_reads_the_weather_and_calendar_live(self) -> None:
        with (
            patch.object(planning_wiring, "AdaptiveReplanPreviewService") as service,
            patch.object(planning_wiring, "overnight_reader") as overnight,
        ):
            self.services.adaptive_replan_preview_service()
            self.services.adaptive_replan_preview_service()

        self.assertEqual(2, self.ctx.weather.service.call_count)
        self.assertEqual(2, self.ctx.external_calendar.reader.call_count)
        args = service.call_args.args
        self.assertEqual(12, len(args))
        self.assertIs(self.ctx.athlete.checkin.return_value, args[2])
        self.assertIs(self.ctx.planning.planned_unit.return_value, args[3])
        self.assertIs(self.ctx.external_calendar.reader.return_value, args[4])
        self.assertIs(self.ctx.weather.service.return_value, args[5])
        self.assertIs(overnight.return_value, args[11])
        self.assertEqual(
            AdaptivePreviewLimits(
                EXTERNAL_CALENDAR_WINDOW_DAYS,
                CHECKIN_TEXT_LIMITS["illness"],
                planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS,
                planning_adaptive.WEATHER_ADAPTIVE_MAX_MINUTES,
            ),
            args[9],
        )
        manager, reader, _preferences, local_date = overnight.call_args.args
        self.assertIs(self.ctx.database.return_value, manager)
        self.assertIs(reader(), self.ctx.canonical_read)
        self.assertIs(local_date(), self.ctx.clock.now.return_value.date.return_value)


class PlanGuardBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock()
        self.today = self.ctx.clock.now.return_value.date.return_value
        self.services = planning_wiring.build_plan_guard(self.ctx)

    def build(self) -> tuple[Any, Any]:
        with (
            patch.object(planning_wiring, "PlanGuardService") as service,
            patch.object(planning_wiring, "PlannedUnitEstimator") as estimator,
        ):
            self.services.plan_guard_service()
        self.estimator = estimator
        return service, service.call_args.kwargs

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.performance.training_reports.assert_not_called()
        self.ctx.planning.planned_unit.assert_not_called()

    def test_the_estimator_reads_the_context_when_used(self) -> None:
        with patch.object(planning_wiring, "PlannedUnitEstimator") as estimator:
            self.services.planned_unit_estimator()
            self.services.planned_unit_estimator()

        self.assertEqual(2, estimator.call_count)
        kwargs = estimator.call_args.kwargs
        self.assertIs(self.ctx.database, kwargs["database_manager"])
        self.assertIs(self.ctx.canonical_read, kwargs["observation_reader"]())
        self.assertIs(self.today, kwargs["today"]())
        kwargs["zone_configurations"]()
        self.ctx.athlete.zones.return_value.configurations.assert_called_once_with()
        profile = self.ctx.athlete.profile.return_value
        with patch.object(planning_wiring, "preferences_from_profile") as preferences:
            kwargs["source_preferences"]("db")
        profile.get_from_db.assert_called_once_with("db")
        preferences.assert_called_once_with(profile.get_from_db.return_value)

    def test_every_guard_is_fresh_and_reads_the_late_owners_on_use(self) -> None:
        _service, kwargs = self.build()

        self.assertIs(self.estimator.return_value, kwargs["estimate_unit"])
        self.ctx.planning.planned_unit.assert_not_called()
        kwargs["planned_units"]()
        self.ctx.planning.planned_unit.return_value.list.assert_called_once_with(
            1000, future_only=True
        )
        kwargs["competitions"]()
        self.ctx.planning.competition.return_value.list.assert_called_once_with()
        kwargs["calendar_events"]()
        reader = self.ctx.external_calendar.reader.return_value
        reader.list_events_in_window.assert_called_once_with(56)
        self.assertIs(self.today, kwargs["today"]())
        profile = self.ctx.athlete.profile.return_value
        profile.get.return_value = {"training_model": None}
        self.assertEqual("", kwargs["training_model"]())
        self.assertIs(profile.get.return_value, kwargs["profile"]())

    def test_reads_run_over_the_active_database_and_canonical_reader(self) -> None:
        _service, kwargs = self.build()
        owners = (self.ctx.database.return_value, self.ctx.canonical_read, self.today)

        with (
            patch.object(planning_wiring, "read_completed") as completed,
            patch.object(planning_wiring, "read_load_thresholds") as thresholds,
        ):
            kwargs["completed_activities"]()
            kwargs["history"].recent_completed()
            kwargs["thresholds"]()

        self.assertEqual(
            [
                (owners, {}),
                (owners, {"days": planning_wiring.LAST_TEST_DAYS}),
            ],
            [(call.args, call.kwargs) for call in completed.call_args_list],
        )
        args = thresholds.call_args.args
        self.assertEqual(owners, args[:3])
        configurations = self.ctx.athlete.zones.return_value.configurations
        self.assertIs(configurations.return_value, args[3])

    def test_illness_and_the_return_stage_use_the_preview_service(self) -> None:
        service, kwargs = self.build()
        preview = self.ctx.planning_workflows.adaptive_replan_preview_service
        preview.return_value.latest_illness_pause.return_value = (
            "pause",
            "2026-09-01",
        )

        with patch.object(planning_wiring, "recent_illness") as illness:
            kwargs["illness"]()

        illness.assert_called_once_with(
            self.ctx.athlete.checkin.return_value.list.return_value,
            self.today,
            "2026-09-01",
        )
        self.ctx.athlete.checkin.return_value.list.assert_called_once_with(10)
        preview.return_value.latest_illness_pause.return_value = None
        with patch.object(planning_wiring, "recent_illness") as illness:
            kwargs["illness"]()
        self.assertIsNone(illness.call_args.args[2])
        return_stage = service.return_value.with_return_stage.call_args.args[0]
        self.assertIs(
            preview.return_value.enforced_return_stage.return_value, return_stage()
        )

    def test_templates_are_the_undated_library_entries(self) -> None:
        service, _kwargs = self.build()
        library = self.ctx.planning.workout_library.return_value
        library.list.return_value = [
            {"id": 1, "date": ""},
            {"id": 2, "date": "2026-09-01"},
        ]
        guard = service.return_value.with_return_stage.return_value

        self.assertEqual(
            {"1": {"id": 1, "date": ""}}, guard.with_templates.call_args.args[0]()
        )
        library.list.assert_called_once_with(1000)

    def test_progress_lessons_and_strength_read_the_training_reports(self) -> None:
        _service, kwargs = self.build()
        reports = self.ctx.performance.training_reports.return_value
        reports.report.block_review.return_value = {"lessons": ["l"]}

        with (
            patch.object(planning_wiring, "read_progress") as progress,
            patch.object(planning_wiring, "read_lessons") as lessons,
            patch.object(planning_wiring, "strength_expected") as strength,
        ):
            kwargs["progress"]()
            kwargs["history"].lessons()
            profile = self.ctx.athlete.profile.return_value
            profile.get.return_value = {"training_preferences_strength": "gym"}
            kwargs["expects_strength"]()

        progress.assert_called_once_with(reports)
        self.assertEqual(["l"], lessons.call_args.args[0]())
        reports.report.block_review.assert_called_once_with(
            {}, reports.timezone.return_value, with_curves=False
        )
        competitions = self.ctx.planning.competition.return_value.list.return_value
        strength.assert_called_once_with("gym", competitions, self.today)

    def test_recent_units_start_before_the_last_test_window(self) -> None:
        _service, kwargs = self.build()
        self.ctx.clock.now.return_value.date.return_value = date(2026, 9, 30)

        kwargs["history"].recent_units()

        self.ctx.planning.planned_unit.return_value.list.assert_called_once_with(
            1000,
            future_only=True,
            since=date(2026, 9, 30) - timedelta(days=planning_wiring.LAST_TEST_DAYS),
        )


if __name__ == "__main__":
    unittest.main()
