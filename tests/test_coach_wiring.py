"""The Coach builders read the live owners from the application context (#2102)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import DEFAULT, Mock, patch

from backend.coach import streams as coach_streams
from backend.coach import tool_wiring, turn_wiring, wiring
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.coach.write_gate import ImpactVerdict
from backend.providers.model_seam import ModelTurn
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance


def _ctx() -> Mock:
    ctx = Mock(name="context")
    ctx.clock.now.return_value.date.return_value = "2026-09-26"
    return ctx


class CoachConversationBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.chats, self.lock = Mock(name="chats"), Mock(name="conversation_lock")
        self.services = wiring.build_coach_conversation(
            self.ctx, chat_repository=self.chats, conversation_lock=self.lock
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.model_transport.openai_responses_client.assert_not_called()
        self.ctx.athlete.profile.assert_not_called()

    def test_provision_and_reset_read_the_manager_and_client_on_each_call(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring, "CoachConversationProvisionService") as provision,
            patch.object(wiring, "CoachConversationResetService") as reset,
        ):
            self.services.provision_service()
            self.services.reset_service()
            self.services.reset_service()

        provision.assert_called_once_with(
            ctx.database.return_value,
            ctx.key_values,
            ctx.model_transport.openai_responses_client.return_value,
            wiring.uuid.uuid4,
            logger=ctx.logger,
        )
        reset.assert_called_with(
            ctx.database.return_value,
            ctx.key_values,
            ctx.model_transport.openai_responses_client.return_value,
            coach_streams.CHAT_STREAM_REGISTRY,
            self.lock,
            runtime_clock.utc_now,
            wiring.uuid.uuid4,
            ctx.logger,
        )
        self.assertEqual(ctx.model_transport.openai_responses_client.call_count, 3)
        self.assertEqual(ctx.database.call_count, 3)

    def test_message_history_and_dialogue_share_the_chat_owners(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring, "CoachMessageService") as message,
            patch.object(wiring, "CoachConversationHistoryService") as history,
            patch.object(wiring, "CoachDialogueReadService") as dialogue,
        ):
            self.services.message_service()
            self.services.history_service()
            self.services.dialogue_read_service()

        manager = ctx.database.return_value
        message.assert_called_with(
            manager, self.chats, runtime_events.STATE_EVENT_BUFFER
        )
        history.assert_called_once_with(manager, self.chats, ctx.key_values)
        dialogue.assert_called_once_with(
            manager,
            message.return_value,
            ctx.key_values,
            ctx.athlete.profile.return_value,
        )

    def test_the_transport_wraps_the_live_model_transport(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "CoachResponseTransport") as transport:
            self.assertIs(self.services.response_transport(), transport.return_value)

        transport.assert_called_once_with(
            ctx.model_transport.complete, ctx.model_transport.stream
        )

    def test_the_attachment_context_reads_the_manager(self) -> None:
        with patch.object(wiring, "CoachAttachmentContextService") as attachments:
            self.services.attachment_context_service()

        attachments.assert_called_once_with(self.ctx.database.return_value)


class CoachLocalBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.services = wiring.build_coach_local(self.ctx)

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.planning_workflows.adaptive_replan_preview_service.assert_not_called()
        self.ctx.garmin.sync_service.assert_not_called()

    def test_dialogue_and_clarification_keep_the_shared_state(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring, "CoachDialogueActionService") as action,
            patch.object(wiring, "CoachDialoguePlanScopeService") as scope,
            patch.object(wiring, "CoachClarificationService") as clarification,
        ):
            self.services.dialogue_action_service()
            self.services.clarification_service()

        manager = ctx.database.return_value
        scope.assert_called_once_with(manager)
        args = action.call_args.args
        self.assertIs(args[0], manager)
        # The queue accessor is passed on, not resolved.
        self.assertIs(args[1], ctx.sync_job_queue.service)
        self.assertIs(args[2], scope.return_value)
        self.assertEqual(args[3](), "2026-09-26")
        clarification.assert_called_once_with(manager, ctx.key_values)

    def test_the_morning_checkin_reads_the_live_canonical_reader(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring, "ManualMorningCheckinService") as morning,
            patch.object(wiring, "GarminSleepObservations") as observations,
        ):
            self.services.manual_morning_checkin_service()

        args = morning.call_args.args
        self.assertEqual(
            args[:3],
            (
                ctx.garmin.sync_service.return_value,
                ctx.garmin.payload_service.return_value,
                ctx.morning_body_battery_service.return_value,
            ),
        )
        self.assertEqual(args[4], ctx.logger)
        self.assertIs(
            morning.call_args.kwargs["observations"], observations.return_value
        )
        manager, reader = observations.call_args.args
        self.assertIs(manager, ctx.database.return_value)
        self.assertIs(reader(), ctx.canonical_read)

    def test_quick_actions_and_the_checkin_state_use_the_athlete_day(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring, "CoachQuickActionsService") as quick,
            patch.object(wiring, "MorningCheckinStateService") as state,
        ):
            self.services.quick_actions_service()
            self.services.morning_checkin_state_service()

        args = quick.call_args.args
        self.assertEqual(
            args[:3],
            (
                ctx.database.return_value,
                ctx.key_values,
                ctx.planning_workflows.adaptive_replan_preview_service.return_value,
            ),
        )
        self.assertEqual(args[3](), "2026-09-26")
        self.assertEqual(args[4], wiring.PLANNED_WORKOUT_LABEL)
        self.assertEqual(state.call_args.args[2](), "2026-09-26")


class CoachContextBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.warnings, self.guard = Mock(name="threshold"), Mock(name="plan_guard")
        self.services = wiring.build_coach_context(
            self.ctx, threshold_warnings=self.warnings, plan_guard=self.guard
        )

    def test_building_resolves_no_owner(self) -> None:
        for owner in (self.ctx.athlete.checkin, self.ctx.weather.service):
            owner.assert_not_called()
        self.warnings.assert_not_called()
        self.guard.plan_guard_service.assert_not_called()

    def test_the_structured_context_reads_the_named_owners(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "CoachStructuredContextService") as factory:
            self.services.structured_context_service()

        args, kwargs = factory.call_args
        self.assertIs(args[0], ctx.athlete.checkin.return_value)
        self.assertIs(args[1], ctx.weather.service.return_value)
        self.assertIs(args[2], ctx.athlete.activity_feedback.return_value)
        planning, performance = args[3], args[4]
        self.assertIs(planning._planned_unit_service, ctx.planning.planned_unit())
        self.assertIs(
            planning._daily_planning_context_service,
            ctx.planning_workflows.daily_planning_context_service(),
        )
        self.assertIs(
            planning._external_calendar_reader, ctx.external_calendar.reader()
        )
        self.assertIs(performance._profile_service, ctx.athlete.profile.return_value)
        self.assertIs(
            performance._garmin_payload_service, ctx.garmin.payload_service.return_value
        )
        self.assertIs(
            kwargs["nutrition_meal_library"], ctx.nutrition.meal_library_service
        )
        self.assertIs(kwargs["threshold_warnings"], self.warnings)
        self.assertEqual(kwargs["today"](), "2026-09-26")

    def test_the_canonical_and_curve_sources_are_read_when_used(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "CoachStructuredContextService") as factory:
            self.services.structured_context_service()
        performance = factory.call_args.args[4]

        canonical = performance._canonical
        self.assertIs(canonical.database_manager, ctx.database)
        self.assertIs(canonical.observation_reader(), ctx.canonical_read)
        self.assertIs(canonical.serving(), ctx.canonical_read)
        ctx.performance.curve_records.assert_not_called()
        performance._lt1_session_records(90)
        # The curve records come without building the whole report bundle.
        ctx.performance.curve_records.assert_called_once_with(90)
        ctx.performance.training_reports.assert_not_called()
        self.assertIs(
            factory.call_args.kwargs["planning_brief"](),
            self.guard.plan_guard_service().brief(),
        )

    def test_limits_and_output_tokens_are_read_on_each_call(self) -> None:
        limits = {
            "local_planned_limit": 20,
            "library_limit": 30,
            "library_description_limit": 200,
            "section_limits": {"planning": 1000},
            "total_char_limit": 10000,
            "activity_limit_per_sport": 5,
            "planned_event_limit": 25,
        }
        with (
            patch.object(wiring, "_context_limits", return_value=limits) as read,
            patch.object(wiring, "CoachStructuredContextService"),
            patch.object(wiring, "CoachTrainingContextService") as training,
            patch.object(wiring, "CoachRequestPayloadService") as payload,
            patch.object(wiring.coach_limits, "COACH_DEFAULT_MAX_OUTPUT_TOKENS", 5000),
        ):
            self.services.training_context_service()
            limits["total_char_limit"] = 12000
            self.services.training_context_service()
            self.services.request_payload_service()

        self.assertEqual(training.call_args_list[0].kwargs["total_char_limit"], 10000)
        self.assertEqual(training.call_args_list[1].kwargs["total_char_limit"], 12000)
        self.assertEqual(
            training.call_args.kwargs["section_limits"], {"planning": 1000}
        )
        self.assertIs(payload.call_args.args[1], self.ctx.settings)
        self.assertEqual(payload.call_args.args[2], 5000)
        self.assertEqual(read.call_count, 3)

    def test_the_preview_reads_the_current_messages_and_limits(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring, "CoachStructuredContextService") as structured,
            patch.object(wiring, "CoachTrainingContextService") as training,
            patch.object(wiring, "CoachContextPreviewService") as preview,
        ):
            self.services.preview_service()

        args = preview.call_args.args
        self.assertIs(args[0], ctx.coach_conversation.message_service.return_value)
        self.assertIs(args[1], training.return_value)
        self.assertIs(args[3], ctx.planning.workout_library.return_value)
        self.assertEqual(
            args[4].library_limit, wiring.coach_context.COACH_LIBRARY_LIMIT
        )
        self.assertEqual(structured.call_count, 2)


class CoachReadToolBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.activity_read = Mock(name="activity_read")
        self.history, self.guard = Mock(name="history"), Mock(name="plan_guard")
        self.services = wiring.build_coach_read_tools(
            self.ctx,
            activity_read=self.activity_read,
            history=self.history,
            plan_guard=self.guard,
        )

    def test_the_read_service_takes_the_owner_factories_unresolved(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "CoachReadToolService") as factory:
            self.services.read_service()

        args = factory.call_args.args
        self.assertIs(args[0], ctx.athlete.profile)
        self.assertIs(args[1], ctx.planning_workflows.structured_training_state_service)
        self.assertIs(args[3], ctx.planning.workout_library)
        self.assertIs(args[4], ctx.planning.planned_unit)
        self.assertIs(args[5], self.history.change_history_service)
        self.assertEqual(args[8], wiring.coach_limits.COACH_TRAINING_CHANGE_LIMIT)
        self.assertIs(args[9], ctx.nutrition.diary_service)
        self.assertIs(args[11], ctx.coach_context.structured_context_service)
        self.activity_read.assert_not_called()
        ctx.coach_context.structured_context_service.assert_not_called()

    def test_the_activity_reads_use_the_injected_and_live_owners(self) -> None:
        ctx = self.ctx
        with patch.object(wiring, "CoachReadToolService") as read_factory:
            self.services.read_service()
        activity_reads = read_factory.call_args.args[2]
        with patch.object(wiring, "CoachActivityReadToolService") as factory:
            self.assertIs(activity_reads(), factory.return_value)

        args = factory.call_args.args
        self.assertEqual(
            args[:3],
            (
                self.activity_read.return_value,
                ctx.garmin.payload_service.return_value,
                ctx.athlete.profile.return_value,
            ),
        )
        self.assertEqual(args[3](), "2026-09-26")
        self.assertEqual(
            args[4:],
            (
                ctx.performance.training_reports.return_value,
                ctx.planning.planned_unit.return_value,
                self.guard.planned_unit_estimator.return_value,
                ctx.athlete.session_corrections.return_value,
            ),
        )


class CoachProposalBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.history = Mock(name="history")
        self.services = wiring.build_coach_proposals(self.ctx, history=self.history)

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.history.undo_service.assert_not_called()

    def test_read_creation_and_confirmation_use_the_current_manager(self) -> None:
        ctx = self.ctx
        with (
            patch.object(wiring, "CoachProposalReadService") as read,
            patch.object(wiring, "CoachProposalCreationService") as create,
            patch.object(wiring, "CoachProposalConfirmationService") as confirm,
        ):
            self.services.read_service()
            self.services.creation_service()
            self.services.confirmation_service()

        for factory in (read, create, confirm):
            self.assertIs(factory.call_args.args[0], ctx.database.return_value)
        self.assertEqual(ctx.database.call_count, 3)
        kwargs = create.call_args.kwargs
        self.assertIs(kwargs["nutrition_diary_service"], ctx.nutrition.diary_service)
        self.assertEqual(kwargs["today"](), "2026-09-26")
        with patch.object(wiring.time, "time", return_value=42.0):
            self.assertEqual(kwargs["now"](), 42.0)

    def test_execution_reads_the_gate_and_the_dispatcher_late(self) -> None:
        ctx = self.ctx
        gate = Mock(name="replacement_gate")
        with (
            patch.object(wiring, "CoachProposalExecutionService") as factory,
            patch.object(runtime_maintenance, "MAINTENANCE_GATE", gate),
        ):
            self.services.execution_service()

        args, kwargs = factory.call_args
        self.assertEqual(
            args,
            (
                ctx.database.return_value,
                self.history.undo_service.return_value,
                ctx.provider_transport.intervals_client,
                gate,
            ),
        )
        ctx.provider_transport.intervals_client.assert_not_called()
        ctx.coach_tool_dispatch.service.assert_not_called()
        self.assertIs(
            kwargs["tool_dispatch_service"](), ctx.coach_tool_dispatch.service()
        )


class CoachPlanningToolBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.guard, self.commands = Mock(name="plan_guard"), Mock(name="sync_commands")
        self.services = tool_wiring.build_coach_planning_tools(
            self.ctx, plan_guard=self.guard, sync_commands=self.commands
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.planning_workflows.local_plan_creation_service.assert_not_called()
        self.commands.illness_pause.assert_not_called()

    def test_the_artifact_and_library_plan_tools_use_the_workflows(self) -> None:
        ctx = self.ctx
        with (
            patch.object(tool_wiring, "TrainingPlanArtifactService") as artifact,
            patch.object(tool_wiring, "CoachLibraryPlanToolService") as library,
        ):
            self.services.training_plan_artifact_service()
            self.services.library_plan_tool_service()

        args = artifact.call_args.args
        self.assertEqual(
            args[:2],
            (
                ctx.database.return_value,
                ctx.planning_workflows.local_plan_creation_service.return_value,
            ),
        )
        self.assertEqual(args[2](), "2026-09-26")
        self.assertIs(args[3], runtime_clock.utc_now)
        library.assert_called_once_with(
            ctx.planning_workflows.workout_library_plan_service.return_value
        )

    def test_the_patch_service_binds_the_limit_and_the_event_buffer(self) -> None:
        ctx, workflows = self.ctx, self.ctx.planning_workflows
        with patch.object(tool_wiring, "CoachTrainingPatchService") as factory:
            self.services.training_patch_service()

        args = factory.call_args.args
        self.assertEqual(
            args[:7],
            (
                ctx.database.return_value,
                workflows.structured_training_change_validator.return_value,
                workflows.structured_training_change_service.return_value,
                workflows.local_plan_creation_service.return_value,
                workflows.calendar_conflict_service.return_value,
                ctx.key_values,
                runtime_events.STATE_EVENT_BUFFER,
            ),
        )
        self.assertEqual(args[7](), "2026-09-26")
        self.assertEqual(args[8], tool_wiring.coach_limits.COACH_TRAINING_CHANGE_LIMIT)

    def test_the_adaptive_apply_takes_the_plan_guard_accessor_unresolved(self) -> None:
        ctx = self.ctx
        with patch.object(tool_wiring, "CoachAdaptiveApplyService") as factory:
            self.services.adaptive_apply_service()

        factory.assert_called_once_with(
            ctx.planning_workflows.adaptive_replan_preview_service.return_value,
            self.commands.illness_pause.return_value,
            ctx.database.return_value,
            self.guard.plan_guard_service,
        )
        self.guard.plan_guard_service.assert_not_called()


class CoachCommandToolBuilderTests(unittest.TestCase):
    def test_factories_are_lazy_and_pass_the_owners_in_order(self) -> None:
        ctx, commands = _ctx(), Mock(name="sync_commands")
        services = tool_wiring.build_coach_command_tools(ctx, sync_commands=commands)
        ctx.database.assert_not_called()
        commands.authority.assert_not_called()

        with patch.multiple(
            tool_wiring,
            CoachSyncToolService=DEFAULT,
            CoachAthleteRecordToolService=DEFAULT,
            CoachProfileUpdateService=DEFAULT,
        ) as constructors:
            services.sync_tool_service()
            services.athlete_record_tool_service()
            services.profile_update_service()

        constructors["CoachSyncToolService"].assert_called_once_with(
            ctx.sync_job_queue.service.return_value,
            commands.authority.return_value,
            commands.conflicts.return_value,
            commands.structured_plan_sync.return_value,
            commands.repair_manifest.return_value,
            commands.plan_push.return_value,
            commands.provider_refresh.return_value,
            nutrition_diary=ctx.nutrition.diary_service.return_value,
        )
        constructors["CoachAthleteRecordToolService"].assert_called_once_with(
            ctx.athlete.checkin.return_value,
            ctx.athlete.activity_feedback.return_value,
            ctx.planning.competition.return_value,
            ctx.nutrition.diary_service.return_value,
            ctx.nutrition.meal_library_service.return_value,
            equipment=ctx.athlete.equipment.return_value,
            session_corrections=ctx.athlete.session_corrections.return_value,
        )
        constructors["CoachProfileUpdateService"].assert_called_once_with(
            ctx.athlete.profile.return_value,
            ctx.database.return_value,
        )


class CoachToolDispatchBuilderTests(unittest.TestCase):
    def test_one_dispatcher_is_built_on_first_use_over_unresolved_factories(
        self,
    ) -> None:
        ctx, history = _ctx(), Mock(name="history")
        services = tool_wiring.build_coach_tool_dispatch(ctx, history=history)
        ctx.coach_read_tools.read_service.assert_not_called()
        constructors = (
            "CoachPlanArtifactToolService",
            "CoachPlanningChangeToolService",
            "TrainingTemplateToolService",
            "CoachPlanningActionToolService",
            "CoachToolDispatchService",
        )
        with patch.multiple(
            tool_wiring, **{name: DEFAULT for name in constructors}
        ) as built:
            first, second = services.service(), services.service()

        self.assertIs(first, second)
        built["CoachToolDispatchService"].assert_called_once()
        args = built["CoachToolDispatchService"].call_args.args
        planning, commands, workflows = (
            ctx.coach_planning_tools,
            ctx.coach_command_tools,
            ctx.planning_workflows,
        )
        self.assertEqual(
            args,
            (
                ctx.coach_read_tools.read_service,
                commands.profile_update_service,
                commands.athlete_record_tool_service,
                built["CoachPlanArtifactToolService"].return_value,
                built["CoachPlanningChangeToolService"].return_value,
                built["TrainingTemplateToolService"].return_value,
                planning.library_plan_tool_service,
                commands.sync_tool_service,
                built["CoachPlanningActionToolService"].return_value,
            ),
        )
        built["CoachPlanArtifactToolService"].assert_called_once_with(
            planning.training_plan_artifact_service
        )
        built["CoachPlanningChangeToolService"].assert_called_once_with(
            workflows.structured_training_plan_replacement_service,
            workflows.structured_training_change_service,
        )
        built["TrainingTemplateToolService"].assert_called_once_with(
            ctx.database, ctx.planning.workout_library
        )
        built["CoachPlanningActionToolService"].assert_called_once_with(
            workflows.adaptive_replan_preview_service,
            planning.adaptive_apply_service,
            ctx.planning.training_plan,
            history.undo_service,
            ctx.coach_proposals.creation_service,
        )
        ctx.database.assert_not_called()
        planning.training_plan_artifact_service.assert_not_called()


class CoachToolRoundBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.ctx.coach_dialogue_tools = ({"name": "read_tool"}, {"name": "write_tool"})
        self.guard, self.commands = Mock(name="plan_guard"), Mock(name="sync_commands")
        self.root = Path("repository-root")
        self.services = tool_wiring.build_coach_tool_rounds(
            self.ctx,
            root=self.root,
            read_only_tools=frozenset({"read_tool"}),
            plan_guard=self.guard,
            sync_commands=self.commands,
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.coach_background_jobs.job_store.assert_not_called()
        self.ctx.coach_turns.structured_response_service.assert_not_called()

    def test_the_round_resolves_each_owner_when_it_is_built(self) -> None:
        ctx = self.ctx
        with patch.multiple(
            tool_wiring,
            CoachStructuredToolRoundService=DEFAULT,
            CoachStructuredToolRoundJournal=DEFAULT,
            CoachStructuredToolExecutionService=DEFAULT,
            CoachStructuredToolFailureService=DEFAULT,
        ) as built:
            self.services.service()

        built["CoachStructuredToolExecutionService"].assert_called_once_with(
            ctx.database.return_value,
            ctx.key_values,
            ctx.coach_local.clarification_service.return_value,
            ctx.coach_planning_tools.training_patch_service.return_value,
            ctx.coach_proposals.creation_service.return_value,
            ctx.coach_tool_dispatch.service.return_value,
            ctx.profile_mutation_coordinator,
            self.guard.plan_guard_service,
        )
        built["CoachStructuredToolFailureService"].assert_called_once_with(
            self.root, ctx.logger, frozenset({"read_tool", "write_tool"})
        )
        args = built["CoachStructuredToolRoundService"].call_args.args
        self.assertIs(args[0], ctx.database)
        self.assertIs(args[7], ctx.coach_context.training_context_service.return_value)
        self.assertIs(args[8], ctx.coach_turns.structured_response_service.return_value)
        self.assertEqual(args[11], ctx.profile_mutation_coordinator)
        # The journal and the round each take a fresh job store.
        self.assertEqual(ctx.coach_background_jobs.job_store.call_count, 2)

    def test_the_round_limits_are_read_on_each_call(self) -> None:
        with patch.object(
            tool_wiring.structured_tool_round, "COACH_TOOL_MAX_ROUNDS", 3
        ):
            first = self.services.service()._limits
        with patch.object(
            tool_wiring.structured_tool_round, "COACH_TOOL_MAX_ROUNDS", 4
        ):
            second = self.services.service()._limits

        self.assertEqual((first.max_rounds, second.max_rounds), (3, 4))

    def test_the_write_gate_classifies_through_the_live_transport(self) -> None:
        ctx = self.ctx
        transport = ctx.coach_conversation.response_transport
        transport.return_value.request.return_value = ModelTurn(
            text='{"requests": [{"domain": "planning", "delete": false, "bulk": true}]}'
        )

        gate = self.services.service()._write_gate

        self.assertEqual(gate._read_only_tools, frozenset({"read_tool"}))
        self.assertIs(gate._logger, ctx.logger)
        transport.assert_not_called()
        classifier = gate._classifier_factory("synthetic-model")
        self.assertEqual(
            classifier("Plan neu aufbauen", "", ""),
            ImpactVerdict(frozenset({"planning"}), bulk=frozenset({"planning"})),
        )
        request = transport.return_value.request.call_args.args[0]
        self.assertEqual(request.model, "synthetic-model")
        self.assertEqual(request.reasoning_effort, "low")


class CoachBackgroundJobBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.chats, self.sessions = Mock(name="chats"), Mock(name="sessions")
        self.root = Path("repository-root")
        self.services = turn_wiring.build_coach_background_jobs(
            self.ctx,
            chat_repository=self.chats,
            root=self.root,
            read_only_tools=frozenset({"read_tool"}),
            session_auth_service=self.sessions,
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.coach_turns.chat_turn_service.assert_not_called()
        self.ctx.coach_local.manual_morning_checkin_service.assert_not_called()

    def test_the_store_and_submission_read_the_worker_gate_and_limits_per_call(
        self,
    ) -> None:
        ctx = self.ctx
        gate = Mock(name="gate")
        with (
            patch.object(runtime_maintenance, "MAINTENANCE_GATE", gate),
            patch.object(turn_wiring.coach_limits, "COACH_BACKGROUND_HORIZON_DAYS", 30),
            patch.object(
                turn_wiring.coach_attachments, "MAX_ATTACHMENT_STORAGE_BYTES", 1024
            ),
        ):
            store = self.services.job_store()
            submission = self.services.job_submission_service()
            cancellation = self.services.cancellation_service()

        self.assertIs(store._database_manager, ctx.database)
        self.assertIs(store._wake_event, COACH_JOB_WORKER.wake_event)
        self.assertIs(store._maintenance_gate, gate)
        self.assertIs(submission._stream_registry, coach_streams.CHAT_STREAM_REGISTRY)
        self.assertIs(submission._settings_service, ctx.settings)
        self.assertEqual(submission._background_horizon_days, 30)
        self.assertEqual(submission._max_attachment_storage_bytes, 1024)
        self.assertIs(cancellation._streams, coach_streams.CHAT_STREAM_REGISTRY)

    def test_the_failure_service_keeps_the_shared_storage_and_event_owners(
        self,
    ) -> None:
        ctx = self.ctx
        deps = self.services.turn_failure_service()._deps

        self.assertIs(deps.database_manager, ctx.database)
        self.assertIs(deps.chat_repository, self.chats)
        self.assertIs(deps.key_values, ctx.key_values)
        self.assertIs(deps.event_buffer, runtime_events.STATE_EVENT_BUFFER)
        self.assertIs(deps.redactor, ctx.redactor)
        self.assertEqual(deps.repository_root, self.root)
        self.assertEqual(deps.read_only_tools, frozenset({"read_tool"}))

    def test_the_runner_keeps_the_chat_and_recovery_factories_lazy(self) -> None:
        ctx = self.ctx
        runner = self.services.background_job_runner()

        self.assertIs(runner._sessions, self.sessions)
        self.assertIs(runner._streams, coach_streams.CHAT_STREAM_REGISTRY)
        self.assertIs(runner._morning, ctx.coach_local.manual_morning_checkin_service)
        self.assertIs(runner._redactor, ctx.redactor)
        ctx.coach_turns.chat_turn_service.assert_not_called()
        self.assertIs(runner._chat_turn(), ctx.coach_turns.chat_turn_service())
        self.sessions.assert_not_called()

    def test_the_morning_completion_takes_the_quick_actions_and_clock_unresolved(
        self,
    ) -> None:
        ctx = self.ctx
        runner = self.services.background_job_runner()
        with patch.object(turn_wiring, "MorningCoachJobCompletionService") as factory:
            runner._morning_completion()

        factory.assert_called_once_with(
            ctx.database.return_value,
            ctx.key_values,
            ctx.coach_local.quick_actions_service,
            ctx.clock.now,
            runtime_clock.utc_now,
        )


class CoachTurnBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _ctx()
        self.ctx.coach_dialogue_tools = [{"name": "read_tool"}]
        self.chats, self.gate = Mock(name="chats"), Mock(name="conversation_gate")
        self.root = Path("repository-root")
        self.services = turn_wiring.build_coach_turns(
            self.ctx,
            chat_repository=self.chats,
            conversation_gate=self.gate,
            root=self.root,
            read_only_tools=frozenset({"read_tool"}),
        )

    def test_building_resolves_no_owner(self) -> None:
        self.ctx.database.assert_not_called()
        self.ctx.coach_conversation.provision_service.assert_not_called()

    def test_the_chat_turn_keeps_the_structured_turn_lazy(self) -> None:
        ctx = self.ctx
        service = self.services.chat_turn_service()

        self.assertIs(service._database_manager, ctx.database)
        self.assertIs(service._receipts._manager_factory, ctx.database)
        self.assertIs(service._settings, ctx.settings)
        self.assertIs(service._conversations, ctx.coach_conversation.provision_service)
        self.assertIs(service._conversation_gate, self.gate)
        self.assertIs(service._maintenance_gate, runtime_maintenance.MAINTENANCE_GATE)
        ctx.coach_conversation.provision_service.assert_not_called()
        ctx.coach_tool_rounds.service.assert_not_called()

    def test_the_structured_turn_resolves_the_owners_when_it_is_created(self) -> None:
        ctx = self.ctx
        conversation = ctx.coach_conversation
        deps = self.services.structured_turn_service()._deps

        self.assertIs(deps.opening._database_manager, ctx.database.return_value)
        self.assertIs(deps.attachments, conversation.attachment_context_service())
        self.assertIs(deps.conversations, conversation.provision_service())
        self.assertIs(deps.dialogue, conversation.dialogue_read_service())
        self.assertIs(deps.payload, ctx.coach_context.request_payload_service())
        self.assertIs(deps.rounds, ctx.coach_tool_rounds.service())
        self.assertIs(deps.failure, ctx.coach_background_jobs.turn_failure_service())
        self.assertIs(deps.tools, ctx.coach_dialogue_tools)
        self.assertEqual(deps.read_only_tools, frozenset({"read_tool"}))
        self.assertEqual(deps.root, self.root)
        self.assertIs(deps.final_receipt._events, runtime_events.STATE_EVENT_BUFFER)

    def test_the_retry_policy_is_one_instance_for_every_response_service(self) -> None:
        first = self.services.structured_response_service()
        second = self.services.structured_response_service()

        self.assertIs(first._retry_policy, second._retry_policy)
        self.assertIs(
            first._transport, self.ctx.coach_conversation.response_transport()
        )
        self.assertIs(first._retry_policy._logger, self.ctx.logger)

    def test_outcome_and_receipts_read_the_live_manager(self) -> None:
        ctx = self.ctx
        outcome = self.services.outcome_service()

        self.assertIs(outcome._database_manager, ctx.database.return_value)
        self.assertIn("read_tool", outcome._internal_tools)
        self.assertIs(
            self.services.command_receipt_service()._manager_factory, ctx.database
        )


if __name__ == "__main__":
    unittest.main()
