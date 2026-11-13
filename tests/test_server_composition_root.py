"""The real composition root resolves every service of the builder domains (#2069).

It replaces the mock-identity assembly tests: server.py builds the application
context and calls the domain builders on a temporary database, and each
service is resolved through the real wiring. Each builder step adds its
domain here.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from server_test_support import ServerTestCase, server

from backend.backup.database import DatabaseBackupService
from backend.backup.export import PrivacyArchiveExportService
from backend.backup.restore import DatabaseRestoreService
from backend.backup.restore_validation import DatabaseRestoreValidationService
from backend.calendar.external import ExternalCalendarReader
from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.background_job import CoachBackgroundJobRunner
from backend.coach.cancellation import CoachCancellationService
from backend.coach.chat_turn import CoachChatTurnService
from backend.coach.clarification import CoachClarificationService
from backend.coach.context import (
    CoachContextPreviewService,
    CoachQuickActionsService,
    CoachStructuredContextService,
    CoachTrainingContextService,
)
from backend.coach.conversation import (
    CoachAttachmentContextService,
    CoachConversationHistoryService,
    CoachConversationProvisionService,
    CoachConversationResetService,
    CoachMessageService,
)
from backend.coach.dialogue import CoachDialogueReadService
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.job_store import CoachJobStore
from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.library_plan_tools import CoachLibraryPlanToolService
from backend.coach.morning import (
    ManualMorningCheckinService,
    MorningCheckinStateService,
)
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.proposal_execution import CoachProposalExecutionService
from backend.coach.proposal_read import (
    CoachProposalConfirmationService,
    CoachProposalReadService,
)
from backend.coach.read_tools import CoachReadToolService
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.request_payload import CoachRequestPayloadService
from backend.coach.response_transport import CoachResponseTransport
from backend.coach.structured_response import CoachStructuredResponseService
from backend.coach.structured_tool_round import CoachStructuredToolRoundService
from backend.coach.structured_turn import CoachStructuredTurnService
from backend.coach.sync_tools import CoachSyncToolService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.training_patch import CoachTrainingPatchService
from backend.coach.turn_failures import CoachTurnFailureService
from backend.coach.turn_outcome import CoachStructuredOutcomeService
from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import DiagnosticReportService
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.nutrition.catalog import ProductCatalogService
from backend.nutrition.diary import NutritionDiaryService
from backend.nutrition.meal_library import NutritionMealLibraryService
from backend.nutrition.sync import IntervalsNutritionSyncService
from backend.performance.report_service import (
    TrainingProfileSelectionService,
    TrainingReportServices,
)
from backend.planning import changes as planning_changes
from backend.planning.adaptive import AdaptiveReplanApplyService
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.competition_service import CompetitionService
from backend.planning.daily_context_service import DailyPlanningContextService
from backend.planning.library_plan_service import WorkoutLibraryPlanService
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.local_plan_creation_service import (
    LocalTrainingPlanCreationService,
)
from backend.planning.plan_guard_service import PlanGuardService
from backend.planning.planned_unit_load import PlannedUnitEstimator
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.replacement_service import (
    StructuredTrainingPlanReplacementService,
)
from backend.planning.state_service import StructuredTrainingStateService
from backend.planning.training_plan_artifact_service import TrainingPlanArtifactService
from backend.planning.training_plans import TrainingPlanService
from backend.privacy import PrivacyDeleteService
from backend.providers import audio as audio_provider
from backend.providers.claude_models import ClaudeModelResolver
from backend.providers.claude_requests import ClaudeMessagesClient
from backend.providers.garmin import GarminClientFactory
from backend.providers.http import JsonHttpClient
from backend.providers.intervals_client import IntervalsClient
from backend.providers.openai_requests import OpenAIResponsesClient
from backend.providers.openai_stream import OpenAIStreamClient
from backend.providers.wahoo_client import WahooClient
from backend.sync import freshness, job_outcomes, jobs, observation, refresh
from backend.sync.adaptive import IllnessPauseSyncService
from backend.sync.authority import PlanningAuthorityService
from backend.sync.backfill_resume import BackfillChainResumer
from backend.sync.canonical_backfill import CanonicalBackfill
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.competitions import (
    CompetitionSyncReconciler,
    CompetitionSyncService,
)
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.daily import DailySyncMarkerService
from backend.sync.executor import SyncJobExecutor
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.full_resync import FullProviderResyncService
from backend.sync.garmin import (
    GarminFixtureLoader,
    GarminPayloadService,
    GarminSyncStateService,
)
from backend.sync.garmin_activity_details import GarminActivityDetailService
from backend.sync.garmin_change_check import GarminChangeCheck
from backend.sync.garmin_projection_service import GarminProjectionService
from backend.sync.garmin_service import (
    GarminAnalysisRefreshService,
    GarminNutritionRefreshService,
    GarminRemoteReader,
    GarminSyncService,
)
from backend.sync.garmin_wellness_history import GarminWellnessHistoryService
from backend.sync.library import (
    WorkoutLibrarySyncService,
    WorkoutLibrarySyncStateService,
)
from backend.sync.metric_export import MetricExportService
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_repair import PlanRepairManifestService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.planned_calendar import (
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)
from backend.sync.queue import SyncJobQueueService
from backend.sync.reconcile import PlannedUnitSyncStateWriter
from backend.sync.scheduler import (
    DailySyncLoop,
    DailySyncScheduler,
    StartupSyncScheduler,
)
from backend.sync.selected import SelectedWorkoutSyncService
from backend.sync.state import SyncStateRepository
from backend.sync.stream_backfill import StreamBackfillService
from backend.sync.wahoo_activity_details import WahooActivityDetailImport
from backend.sync.wahoo_connection import WahooConnectionService
from backend.sync.wahoo_library_state import WahooLibraryState
from backend.sync.wahoo_plan_push import WahooPlanPushService
from backend.sync.wahoo_sync import WahooSyncService
from backend.sync.wahoo_workout_export import WahooWorkoutExport
from backend.sync.weather import WeatherSyncService
from backend.sync.worker import SyncJobWorker
from backend.sync.workout_export import WorkoutLibraryExportPort
from backend.weather.service import WeatherService


class CompositionRootTests(ServerTestCase):
    def test_history_services_resolve_over_the_current_database(self) -> None:
        history = server.HISTORY

        self.assertIsInstance(history.change_history_service(), ChangeHistoryService)
        self.assertIsInstance(history.undo_service(), HistoryUndoService)

    def test_planning_data_services_resolve_and_are_fresh(self) -> None:
        data = server.PLANNING_DATA

        self.assertIs(server.APP.planning, data)
        for factory, kind in (
            (data.competition, CompetitionService),
            (data.training_plan, TrainingPlanService),
            (data.planned_unit, PlannedUnitService),
            (data.workout_library, WorkoutLibraryService),
            (data.adaptive_apply, AdaptiveReplanApplyService),
        ):
            with self.subTest(kind=kind.__name__):
                self.assertIsInstance(factory(), kind)
                self.assertIsNot(factory(), factory())

    def test_planning_workflows_resolve_through_the_late_owners(self) -> None:
        workflows = server.PLANNING_WORKFLOWS

        self.assertIs(server.APP.planning_workflows, workflows)
        for factory, kind in (
            (workflows.calendar_conflict_service, CalendarConflictService),
            (workflows.workout_library_plan_service, WorkoutLibraryPlanService),
            (
                workflows.local_plan_creation_service,
                LocalTrainingPlanCreationService,
            ),
            (workflows.daily_planning_context_service, DailyPlanningContextService),
            (
                workflows.structured_training_state_service,
                StructuredTrainingStateService,
            ),
            (
                workflows.structured_training_change_validator,
                planning_changes.StructuredTrainingChangeValidator,
            ),
            (
                workflows.structured_training_change_service,
                planning_changes.StructuredTrainingChangeService,
            ),
            (
                workflows.structured_training_plan_replacement_service,
                StructuredTrainingPlanReplacementService,
            ),
            (workflows.adaptive_replan_preview_service, AdaptiveReplanPreviewService),
        ):
            with self.subTest(kind=kind.__name__):
                self.assertIsInstance(factory(), kind)

    def test_training_reports_and_the_plan_guard_resolve_through_the_root(
        self,
    ) -> None:
        performance, guard = server.PERFORMANCE, server.PLAN_GUARD

        self.assertIs(server.APP.performance, performance)
        reports = performance.training_reports()
        self.assertIsInstance(reports, TrainingReportServices)
        self.assertIsNot(reports, performance.training_reports())
        # The session curves stay cached across the fresh report services.
        self.assertIs(
            reports.profiles._curves, performance.training_reports().profiles._curves
        )
        self.assertIsInstance(guard.plan_guard_service(), PlanGuardService)
        self.assertIsInstance(guard.planned_unit_estimator(), PlannedUnitEstimator)
        profile = server.ATHLETE_DATA.profile().get()
        self.assertEqual(profile.get("timezone") or "UTC", reports.timezone())
        self.assertIs(
            server.HTTP_API.analysis_routes._reports, performance.training_reports
        )

    def test_the_public_state_reads_the_session_curves_of_the_report_services(
        self,
    ) -> None:
        shared = server.PERFORMANCE.training_reports().profiles._curves
        with patch.object(
            TrainingProfileSelectionService,
            "curve_records",
            autospec=True,
            return_value=[],
        ) as records:
            public = server.PUBLIC_STATE.performance_state_service()
            lt1_records = public._lt1_session_records
            assert lt1_records is not None
            self.assertEqual([], lt1_records(90))

        records.assert_called_once()
        profiles, days = records.call_args.args
        self.assertIs(shared, profiles._curves)
        self.assertEqual(90, days)

    def test_weather_services_resolve(self) -> None:
        self.assertIsInstance(server.WEATHER.service(), WeatherService)
        self.assertIsInstance(server.WEATHER_SYNC(), WeatherSyncService)

    def test_nutrition_services_resolve(self) -> None:
        nutrition = server.NUTRITION_SERVICES

        self.assertIsInstance(nutrition.diary_service(), NutritionDiaryService)
        self.assertIsInstance(
            nutrition.meal_library_service(), NutritionMealLibraryService
        )
        self.assertIsInstance(
            nutrition.product_catalog_service(), ProductCatalogService
        )
        self.assertIsInstance(
            nutrition.intervals_sync_service(), IntervalsNutritionSyncService
        )
        self.assertIs(nutrition.food_mirror(), nutrition.food_mirror())

    def test_backup_services_resolve_over_the_live_owners(self) -> None:
        backup = server.BACKUP

        self.assertIsInstance(backup.backup_service(), DatabaseBackupService)
        self.assertIsInstance(
            backup.restore_validation_service(), DatabaseRestoreValidationService
        )
        restore = backup.restore_service()
        self.assertIsInstance(restore, DatabaseRestoreService)
        self.assertEqual(restore._dependencies.config.database_path, server.DB_PATH)
        self.assertEqual(restore._dependencies.config.data_dir, server.DATA_DIR)
        self.assertIsInstance(restore._dependencies.sync_jobs, SyncJobQueueService)
        self.assertIsInstance(restore._dependencies.coach_jobs, CoachJobStore)
        self.assertIsInstance(
            restore._dependencies.coach_failures, CoachTurnFailureService
        )

    def test_privacy_services_resolve_without_exporting_or_purging(self) -> None:
        privacy = server.PRIVACY

        export = privacy.archive_export_service()
        self.assertIsInstance(export, PrivacyArchiveExportService)
        self.assertEqual(export._config.data_dir, server.DATA_DIR)
        self.assertEqual(export._config.database_path, server.DB_PATH)
        purge = privacy.delete_service()
        self.assertIsInstance(purge, PrivacyDeleteService)
        dependencies = purge._dependencies
        self.assertIs(dependencies.database_lock, server.DB_LOCK)
        self.assertIs(
            dependencies.maintenance_gate, server.runtime_maintenance.MAINTENANCE_GATE
        )
        self.assertIsInstance(dependencies.log_files, RecentLogEntriesService)
        assert dependencies.recovery_copies is not None
        self.assertEqual(dependencies.recovery_copies._data_dir, server.DATA_DIR)
        for late in (
            dependencies.refresh_credentials,
            dependencies.cancel_garmin_login,
            dependencies.disconnect_wahoo,
            dependencies.cancel_coach_turns,
        ):
            self.assertTrue(callable(late))
        with dependencies.diagnostics_suspended():
            pass

    def test_diagnostics_services_resolve_over_the_live_owners(self) -> None:
        diagnostics = server.DIAGNOSTICS

        logs = diagnostics.recent_log_entries_service()
        self.assertIsInstance(logs, RecentLogEntriesService)
        self.assertEqual(logs._log_path, server.LOG_PATH)
        self.assertIsInstance(
            diagnostics.coach_history_service(), CoachDiagnosticHistoryService
        )
        report = diagnostics.report_service()
        self.assertIsInstance(report, DiagnosticReportService)
        self.assertIn("logs", report.report())

    def test_provider_transports_build_their_clients_over_the_live_owners(
        self,
    ) -> None:
        # Only constructs clients; no remote endpoint is called.
        provider = server.PROVIDER_TRANSPORT
        http_client = provider.json_http_client()
        self.assertIsInstance(http_client, JsonHttpClient)
        self.assertIs(provider.json_http_client(), http_client)
        self.assertIs(server.APP.provider_transport, provider)
        self.assertIsInstance(provider.intervals_client(), IntervalsClient)
        explicit = replace(server.CONFIG, intervals_api_key="test-key")
        self.assertIs(provider.intervals_client(explicit).config, explicit)

        model = server.MODEL_TRANSPORT
        self.assertIs(server.APP.model_transport, model)
        self.assertIsInstance(model.openai_responses_client(), OpenAIResponsesClient)
        self.assertIsInstance(model.openai_stream_client(), OpenAIStreamClient)
        self.assertIsInstance(model.claude_client(), ClaudeMessagesClient)
        self.assertIsInstance(
            model.audio_transcription_client(), audio_provider.AudioTranscriptionClient
        )
        self.assertIsInstance(model.claude_models(), ClaudeModelResolver)
        self.assertEqual(
            model.openai_stream_client().config.timeout,
            server.OPENAI_RESPONSE_TIMEOUT_SECONDS,
        )
        self.assertTrue(callable(model.complete) and callable(model.stream))

    def test_sync_services_resolve_through_the_root(self) -> None:
        persistence, provider = server.SYNC_PERSISTENCE, server.PROVIDER_SYNC
        queue, commands = server.SYNC_JOB_QUEUE, server.SYNC_COMMANDS

        self.assertIs(server.APP.provider_sync, provider)
        self.assertIs(server.APP.sync_job_queue, queue)
        self.assertIsInstance(persistence.state_repository(), SyncStateRepository)
        self.assertIsInstance(persistence.daily_markers(), DailySyncMarkerService)
        # One tracker is shared across calls; the observer wraps it.
        tracker = provider.refresh_tracker()
        self.assertIsInstance(tracker, refresh.ProviderRefreshTracker)
        self.assertIs(tracker, provider.refresh_tracker())
        self.assertIsInstance(
            provider.operation_observer(), observation.SyncOperationObserver
        )
        self.assertIsInstance(
            provider.freshness_service(), freshness.ProviderFreshnessService
        )
        self.assertIsInstance(queue.store(), jobs.SyncJobStore)
        self.assertIsInstance(queue.service(), SyncJobQueueService)
        self.assertIsInstance(
            queue.outcome_service(), job_outcomes.SyncJobOutcomeService
        )
        self.assertIsInstance(server.SYNC_WORKERS.create(), SyncJobWorker)
        for factory, kind in (
            (commands.illness_pause, IllnessPauseSyncService),
            (commands.provider_refresh, ProviderRefreshCommandService),
            (commands.conflicts, SyncConflictCommandService),
            (commands.plan_push, PlanPushCommandService),
            (commands.authority, PlanningAuthorityService),
            (commands.structured_plan_sync, StructuredPlanSyncService),
            (commands.repair_manifest, PlanRepairManifestService),
        ):
            with self.subTest(kind=kind.__name__):
                self.assertIsInstance(factory(), kind)
                self.assertIsNot(factory(), factory())

    def test_garmin_services_resolve_through_the_root(self) -> None:
        garmin = server.GARMIN_ASSEMBLY

        self.assertIs(server.APP.garmin, garmin)
        for factory, kind in (
            (garmin.fixture_loader, GarminFixtureLoader),
            (garmin.client_factory, GarminClientFactory),
            (garmin.payload_service, GarminPayloadService),
            (garmin.sync_state_service, GarminSyncStateService),
            (garmin.remote_reader, GarminRemoteReader),
            (garmin.sync_service, GarminSyncService),
            (garmin.activity_detail_service, GarminActivityDetailService),
            (garmin.nutrition_refresh_service, GarminNutritionRefreshService),
            (garmin.wellness_history_service, GarminWellnessHistoryService),
            (garmin.stream_backfill_service, StreamBackfillService),
            (garmin.analysis_refresh_service, GarminAnalysisRefreshService),
            (garmin.projection_service, GarminProjectionService),
        ):
            with self.subTest(kind=kind.__name__):
                self.assertIsInstance(factory(), kind)
                self.assertIsNot(factory(), factory())
        self.assertTrue(callable(garmin.strength_push_service()._configured))
        self.assertIsInstance(garmin.sdk_write_ready(), bool)
        self.assertIsNotNone(garmin.body_export(server.ATHLETE_DATA.profile()))
        self.assertIsInstance(garmin.change_check(), GarminChangeCheck)
        self.assertIs(garmin.change_check(), garmin.change_check())

    def test_wahoo_services_resolve_through_the_root(self) -> None:
        connection, wahoo = server.WAHOO_CONNECTION, server.WAHOO_SYNC

        # The connection, sync, detail and plan-push services are shared.
        for shared, kind in (
            (connection.service, WahooConnectionService),
            (wahoo.sync_service, WahooSyncService),
            (wahoo.activity_detail_import, WahooActivityDetailImport),
            (wahoo.plan_push_service, WahooPlanPushService),
        ):
            with self.subTest(kind=kind.__name__):
                self.assertIsInstance(shared(), kind)
                self.assertIs(shared(), shared())
        for fresh, made in (
            (wahoo.client, WahooClient),
            (wahoo.stream_backfill_service, StreamBackfillService),
            (wahoo.workout_export, WahooWorkoutExport),
            (wahoo.library_state, WahooLibraryState),
        ):
            with self.subTest(kind=made.__name__):
                self.assertIsInstance(fresh(), made)
                self.assertIsNot(fresh(), fresh())
        self.assertTrue(callable(wahoo.fit_download()))

    def test_output_flow_services_resolve_through_the_root(self) -> None:
        server_flows = (
            (server.PLANNED_UNIT_SYNC.state_writer, PlannedUnitSyncStateWriter),
            (server.PLANNED_CALENDAR_SYNC.sync_service, PlannedCalendarSyncService),
            (
                server.PLANNED_CALENDAR_SYNC.repair_service,
                PlannedCalendarRepairService,
            ),
            (
                server.WORKOUT_LIBRARY_SYNC.sync_state_service,
                WorkoutLibrarySyncStateService,
            ),
            (server.WORKOUT_LIBRARY_SYNC.sync_service, WorkoutLibrarySyncService),
            (server.SELECTED_WORKOUT_SYNC.service, SelectedWorkoutSyncService),
            (server.EXTERNAL_CALENDAR.reader, ExternalCalendarReader),
            (server.EXTERNAL_CALENDAR.sync_service, ExternalCalendarSyncService),
        )

        self.assertIs(server.APP.workout_library_sync, server.WORKOUT_LIBRARY_SYNC)
        self.assertIs(server.APP.external_calendar, server.EXTERNAL_CALENDAR)
        self.assertIs(server.APP.wahoo, server.WAHOO_SYNC)
        self.assertIs(server.APP.sync_persistence, server.SYNC_PERSISTENCE)
        for factory, kind in server_flows:
            with self.subTest(kind=kind.__name__):
                self.assertIsInstance(factory(), kind)
                self.assertIsNot(factory(), factory())
        self.assertIsInstance(
            server.WORKOUT_LIBRARY_SYNC.export_port(), WorkoutLibraryExportPort
        )
        self.assertIsInstance(server.METRIC_EXPORT, MetricExportService)

    def test_execution_backfill_and_resync_services_resolve_through_the_root(
        self,
    ) -> None:
        execution, schedulers = server.SYNC_JOB_EXECUTION, server.SYNC_SCHEDULERS
        resync, backfill = server.PROVIDER_RESYNC, server.CANONICAL_BACKFILL

        self.assertIsInstance(execution.executor(), SyncJobExecutor)
        self.assertIsNot(execution.executor(), execution.executor())
        for factory, kind in (
            (schedulers.daily_scheduler, DailySyncScheduler),
            (schedulers.startup_scheduler, StartupSyncScheduler),
            (schedulers.backfill_resumer, BackfillChainResumer),
            (schedulers.daily_loop, DailySyncLoop),
            (resync.competition_reconciler, CompetitionSyncReconciler),
            (resync.competition_sync_service, CompetitionSyncService),
            (resync.full_resync_service, FullProviderResyncService),
        ):
            with self.subTest(kind=kind.__name__):
                self.assertIsInstance(factory(), kind)
                self.assertIsNot(factory(), factory())
        # The run registry outlives each full resync service.
        self.assertIs(
            resync.full_resync_service()._runs, resync.full_resync_service()._runs
        )
        self.assertIs(server.APP.canonical_backfill, backfill)
        self.assertIsInstance(backfill.worker, CanonicalBackfillWorker)
        self.assertIsInstance(backfill.status_reader, CanonicalBackfill)
        self.assertEqual(
            set(server.DEFAULT_PROVIDER_REGISTRY.ids()), set(server.PROVIDER_CONFIGURED)
        )
        for check in server.PROVIDER_CONFIGURED.values():
            self.assertIsInstance(check(), bool)

    def test_coach_services_resolve_through_the_root(self) -> None:
        owners = {
            "coach_conversation": server.COACH_CONVERSATION,
            "coach_local": server.COACH_LOCAL,
            "coach_context": server.COACH_CONTEXT,
            "coach_read_tools": server.COACH_READ_TOOLS,
            "coach_proposals": server.COACH_PROPOSALS,
            "coach_planning_tools": server.COACH_PLANNING_TOOLS,
            "coach_command_tools": server.COACH_COMMAND_TOOLS,
            "coach_tool_dispatch": server.COACH_TOOL_DISPATCH,
            "coach_tool_rounds": server.COACH_TOOL_ROUNDS,
            "coach_background_jobs": server.COACH_BACKGROUND_JOBS,
            "coach_turns": server.COACH_TURNS,
        }
        for name, owner in owners.items():
            with self.subTest(owner=name):
                self.assertIs(getattr(server.APP, name), owner)
        self.assertIs(server.APP.coach_dialogue_tools, server.COACH_DIALOGUE_TOOLS)
        conversation, local, context = (
            server.APP.coach_conversation,
            server.COACH_LOCAL,
            server.COACH_CONTEXT,
        )
        proposals, planning = server.COACH_PROPOSALS, server.COACH_PLANNING_TOOLS
        commands, jobs = server.COACH_COMMAND_TOOLS, server.COACH_BACKGROUND_JOBS
        turns = server.COACH_TURNS
        for factory, kind in (
            (conversation.provision_service, CoachConversationProvisionService),
            (conversation.reset_service, CoachConversationResetService),
            (conversation.message_service, CoachMessageService),
            (conversation.history_service, CoachConversationHistoryService),
            (conversation.dialogue_read_service, CoachDialogueReadService),
            (conversation.attachment_context_service, CoachAttachmentContextService),
            (conversation.response_transport, CoachResponseTransport),
            (local.quick_actions_service, CoachQuickActionsService),
            (local.dialogue_action_service, CoachDialogueActionService),
            (local.clarification_service, CoachClarificationService),
            (local.manual_morning_checkin_service, ManualMorningCheckinService),
            (local.morning_checkin_state_service, MorningCheckinStateService),
            (context.structured_context_service, CoachStructuredContextService),
            (context.training_context_service, CoachTrainingContextService),
            (context.request_payload_service, CoachRequestPayloadService),
            (context.preview_service, CoachContextPreviewService),
            (server.COACH_READ_TOOLS.read_service, CoachReadToolService),
            (proposals.read_service, CoachProposalReadService),
            (proposals.creation_service, CoachProposalCreationService),
            (proposals.confirmation_service, CoachProposalConfirmationService),
            (proposals.execution_service, CoachProposalExecutionService),
            (planning.training_plan_artifact_service, TrainingPlanArtifactService),
            (planning.library_plan_tool_service, CoachLibraryPlanToolService),
            (planning.training_patch_service, CoachTrainingPatchService),
            (planning.adaptive_apply_service, CoachAdaptiveApplyService),
            (commands.sync_tool_service, CoachSyncToolService),
            (commands.athlete_record_tool_service, CoachAthleteRecordToolService),
            (commands.profile_update_service, CoachProfileUpdateService),
            (server.COACH_TOOL_ROUNDS.service, CoachStructuredToolRoundService),
            (jobs.job_store, CoachJobStore),
            (jobs.turn_failure_service, CoachTurnFailureService),
            (jobs.job_submission_service, CoachJobSubmissionService),
            (jobs.cancellation_service, CoachCancellationService),
            (jobs.background_job_runner, CoachBackgroundJobRunner),
            (turns.command_receipt_service, CoachCommandReceiptService),
            (turns.outcome_service, CoachStructuredOutcomeService),
            (turns.structured_response_service, CoachStructuredResponseService),
            (turns.structured_turn_service, CoachStructuredTurnService),
            (turns.chat_turn_service, CoachChatTurnService),
        ):
            with self.subTest(kind=kind.__name__):
                self.assertIsInstance(factory(), kind)
                self.assertIsNot(factory(), factory())
        # The dispatcher is stateless: built once, on first use.
        dispatch = server.COACH_TOOL_DISPATCH.service()
        self.assertIsInstance(dispatch, CoachToolDispatchService)
        self.assertIs(dispatch, server.COACH_TOOL_DISPATCH.service())

    def test_the_redactor_reads_the_nutrition_secrets(self) -> None:
        # The log redactor looks the nutrition services up by name.
        services = SimpleNamespace(secret_values=lambda: ("yazio-token",))
        with patch.object(server, "NUTRITION_SERVICES", services):
            self.assertIn("yazio-token", server._nutrition_secret_values())

    def test_the_context_reads_the_live_configuration_and_database(self) -> None:
        replaced = replace(server.CONFIG, calendar_ical_url="https://example.invalid")
        with patch.object(server, "CONFIG", replaced):
            self.assertIs(replaced, server.APP.config())
        self.assertIs(server.database_manager(), server.APP.database())


if __name__ == "__main__":
    unittest.main()
