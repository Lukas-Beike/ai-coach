"""Static architecture guards for the server-monolith extraction.

The checks in this module intentionally parse source files instead of importing
the application.  Importing ``server`` initializes configuration and other
runtime state, which is outside the scope of an architecture check.
"""

from __future__ import annotations

import ast
import unittest
from collections.abc import Iterable
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# Container CI mounts tests and server.py under /review while the application
# package remains at /app/backend. Keep static guards pointed at real source.
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if not BACKEND_ROOT.is_dir():
    BACKEND_ROOT = Path.cwd() / "backend"
SERVER_PATH = REPOSITORY_ROOT / "server.py"


# This is deliberately explicit.  These small, dependency-light helpers are
# backend-owned implementations, not server callbacks or compatibility
# wrappers, and must not be reintroduced in server.py.
MOVED_SYMBOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("backend.coach.tool_failures", ("CoachStructuredToolFailureService",)),
    ("backend.coach.tool_execution_service", ("CoachStructuredToolExecutionService",)),
    ("backend.coach.tool_preparation", ("CoachStructuredToolPreparationService",)),
    ("backend.coach.tool_replay", ("CoachStructuredToolReplayService",)),
    ("backend.coach.turn_outcome", ("CoachStructuredOutcomeService",)),
    ("backend.coach.tool_call_metadata", ("structured_tool_call_metadata",)),
    ("backend.coach.read_tools", ("CoachReadToolService",)),
    ("backend.coach.tool_dispatch", ("CoachToolDispatchService",)),
    ("backend.coach.turn_failures", ("CoachTurnFailureService", "coach_error_metadata")),
    ("backend.coach.job_submission", ("CoachJobSubmissionService",)),
    ("backend.coach.athlete_record_tools", ("CoachAthleteRecordToolService",)),
    ("backend.coach.library_plan_tools", ("CoachLibraryPlanToolService",)),
    ("backend.coach.plan_artifact_tools", ("CoachPlanArtifactToolService",)),
    ("backend.coach.planning_change_tools", ("CoachPlanningChangeToolService",)),
    ("backend.coach.planning_action_tools", ("CoachPlanningActionToolService",)),
    ("backend.coach.dialogue_plan_scope", ("CoachDialoguePlanScopeService",)),
    ("backend.coach.dialogue_action", ("CoachDialogueActionService",)),
    ("backend.coach.clarification", ("CoachClarificationService",)),
    ("backend.coach.training_patch", ("CoachTrainingPatchService",)),
    ("backend.coach.planning_commands", ("CoachPlanningCommandService",)),
    ("backend.coach.cancellation", ("CoachCancellationService",)),
    ("backend.coach.streams", ("ChatStreamRegistry",)),
    ("backend.coach.job_store", ("CoachJobStore",)),
    ("backend.http_api.auth", ("SessionAuthService",)),
    ("backend.http_api.export_streams", ("ExportStreamTransport",)),
    ("backend.coach.conversation", ("CoachConversationResetService",)),
    ("backend.coach.prompt", ("COACH_PROMPT",)),
    ("backend.http_api.readiness", ("ReadinessService",)),
    (
        "backend.http_api.public_performance",
        ("PublicPerformanceStateService", "PublicFeedbackStateService"),
    ),
    ("backend.http_api.public_plan", ("PublicPlanStateService",)),
    ("backend.http_api.library_page", ("LibraryPageService", "paged_library")),
    (
        "backend.coach.proposals",
        (
            "CoachProposalReadService",
            "CoachProposalCreationService",
            "CoachProposalConfirmationService",
            "CoachProposalExecutionService",
            "COACH_ACTION_TTL_SECONDS",
            "COACH_ACTION_TYPES",
            "coach_action_hash",
            "coach_action_view",
            "prune_expired_coach_proposals",
            "_coach_action_hash",
            "_coach_action_view",
            "current_coach_proposals",
            "confirm_coach_action_preview",
            "validated_coach_action_preview_input",
            "create_coach_action_preview",
            "execute_coach_action",
            "_execute_coach_action",
        ),
    ),
    ("backend.coach.receipt_reads", ("CoachCommandReceiptService",)),
    ("backend.coach.request_payload", ("CoachRequestPayloadService",)),
    (
        "backend.coach.context",
        (
            "CoachStructuredContextService",
            "CoachTrainingContextService",
            "CoachContextPreviewService",
            "build_training_context",
            "context_preview",
            "structured_athlete_context",
            "CoachIntervalsContextService",
            "future_coach_planned_workouts",
            "coach_intervals_context",
            "compact_coach_activity",
            "compact_coach_planned_event",
            "coach_workout_library",
            "coach_quick_actions_state",
            "_compact_coach_library_item",
            "_balanced_coach_library_items",
            "compact_coach_local_planned_workout",
            "compact_coach_local_planned_workouts",
            "coach_context_json_size",
            "bounded_coach_context_value",
            "bounded_coach_context_sections",
            "coach_context_projection_meta",
        ),
    ),
    (
        "backend.coach.conversation",
        (
            "GeminiConversationHistoryService",
            "GeminiLocalChatHistoryService",
            "GeminiRequestPayloadService",
            "GeminiResponseNormalizationService",
            "CoachMessageService",
            "add_message",
            "list_messages",
            "_gemini_content_has_function_response",
            "_gemini_history_exchange_boundary",
            "_trim_gemini_history",
            "_gemini_history_parts_without_raw_media",
            "_gemini_inline_media_from_history",
            "_gemini_history",
            "_save_gemini_history",
            "repair_incomplete_gemini_tool_history",
            "_gemini_local_chat_history",
            "_gemini_request_history",
            "_gemini_last_user_text",
            "_gemini_call_names",
            "_gemini_request_payload",
            "_gemini_responses_result",
        ),
    ),
    (
        "backend.coach.outcomes",
        (
            "unresolved_coach_steps",
            "_unresolved_coach_steps",
            "_alternative_planning_steps_repaired",
            "_profile_repair_fields",
            "_profile_steps_repaired",
            "_matching_coach_steps_repaired",
            "_coach_steps_repaired",
        ),
    ),
    (
        "backend.coach.authorization",
        ("coach_execution_scope", "coach_session_key", "require_coach_scope", "structured_action_payload", "_require_coach_scope", "_coach_scope_values"),
    ),
    (
        "backend.coach.training_template_tools",
        ("TrainingTemplateToolService",),
    ),
    (
        "backend.coach.attachments",
        ("gemini_selected_raw_attachments", "gemini_history_parts", "_gemini_selected_raw_attachments", "_gemini_history_parts"),
    ),
    (
        "backend.planning.artifacts",
        (
            "structured_artifact_payload",
            "validate_structured_plan_limits",
            "_structured_artifact_payload",
            "_validate_structured_plan_limits",
        ),
    ),
    (
        "backend.planning.changes",
        (
            "StructuredTrainingChangeService",
            "StructuredTrainingChangeValidator",
            "StructuredTrainingPlanResolver",
            "PlanningChangeDependencies",
            "apply_structured_changes",
            "apply_structured_changes_in_db",
            "validated_training_date",
            "prepare_structured_training_change",
            "prepare_structured_training_changes",
            "_record_created_training_change",
            "_record_existing_training_change",
            "_validate_training_change_dates",
            "_validate_training_change_batch",
            "_validate_structured_training_revision",
            "_validate_structured_training_change_hash",
            "_validate_structured_training_change_hashes",
            "_validate_structured_training_change_revisions",
            "_validated_training_date",
            "_prepare_structured_training_change",
            "_prepare_structured_training_changes",
            "_structured_training_membership_update",
            "_structured_training_change_moves_bounds",
            "_collect_structured_training_memberships",
            "_derived_structured_training_plan",
            "_apply_authorized_structured_training_plan",
            "_resolve_structured_training_plan_reference",
            "_validate_structured_training_create_plan_ids",
            "_derive_structured_training_plan",
            "_apply_structured_training_change_rows",
            "_planning_change_dependencies",
            "_apply_structured_training_changes",
            "_apply_structured_training_changes_in_db",
        ),
    ),
    (
        "backend.planning.replacement",
        (
            "prepare_structured_plan_replacement",
            "validate_replacement_workouts",
            "_prepare_structured_plan_replacement",
            "_validate_replacement_workouts",
        ),
    ),
    (
        "backend.change_history",
        (
            "audit_projection_fields",
            "_audit_payload_projection",
            "audit_projection",
            "audit_hash",
            "audit_diff",
            "cleanup",
            "reserve_capacity",
            "record_change",
            "public_view",
        ),
    ),
    (
        "backend.errors",
        (
            "AppError",
            "ClientDisconnected",
            "provider_error",
            "public_app_error_status",
            "INTERVALS_API_KEY_ERROR",
            "OPENAI_API_KEY_ERROR",
            "GEMINI_API_KEY_ERROR",
            "NOT_FOUND_ERROR",
            "INTERNAL_SERVER_ERROR",
            "COMPETITION_NOT_FOUND_ERROR",
            "COACH_ABORTED_ERROR",
            "STRUCTURED_AUTHORIZATION_ERROR",
            "INVALID_PLANNING_ID_ERROR",
            "CORRUPT_PLANNING_ERROR",
            "INVALID_LIBRARY_ID_ERROR",
            "CORRUPT_LIBRARY_ERROR",
            "INVALID_PLANNING_DATE_ERROR",
            "STALE_PLANNING_REVISION_ERROR",
            "UNSUPPORTED_BYDAY_ERROR",
            "PLANNED_CALENDAR_RECHECK_ERROR",
        ),
    ),
    (
        "backend.athlete.profile",
        (
            "DEFAULT_TIMEZONE",
            "DEFAULT_PROFILE",
            "timezone_name",
            "normalize_profile",
            "ProfileService",
        ),
    ),
    (
        "backend.athlete.context",
        (
            "AthleteContextService",
            "_validated_athlete_context",
            "_record_removed_competition_tombstones",
            "_save_athlete_competition",
            "_delete_removed_athlete_competitions",
            "save_athlete_context",
        ),
    ),
    (
        "backend.planning.competitions",
        (
            "COMPETITION_TEXT_LIMITS",
            "competition_start",
            "competition_moving_time",
            "competition_distance",
            "competition_target",
            "competition_category_and_priority",
            "competition_normalized_id",
            "competition_normalized_text_fields",
            "normalize_competition",
            "COMPETITION_EXTERNAL_PREFIX",
            "COMPETITION_SPORTS",
            "supported_competition_sport",
            "intervals_competition_sport",
            "competition_external_id",
            "competition_event_optional_payload",
            "competition_event_payload",
            "remote_competition_date",
            "remote_competition_moving_time",
            "remote_competition_distance",
            "remote_competition_data",
            "competition_conflict_payload",
            "is_remote_competition_event",
            "competition_sync_key",
            "competition_remote_indexes",
            "_competition_remote_indexes",
            "competition_remote_match",
            "_competition_remote_match",
            "competition_conflict_action",
            "_competition_conflict_action",
            "competition_dirty_row_action",
            "_competition_dirty_row_action",
            "competition_delete_identifiers",
            "_competition_delete_identifiers",
            "competition_remote_signature",
            "_competition_remote_signature",
            "competition_plan_summary",
            "_competition_plan_summary",
            "competition_sync_plan",
            "_competition_sync_plan",
        ),
    ),
    (
        "backend.planning.competition_service",
        (
            "CompetitionService",
            "_competition_id",
            "_coach_payload",
            "_merge_update",
            "list_competitions",
            "coach_competition_payload",
            "_normalise_coach_competition_id",
            "COACH_COMPETITION_REQUIRED_FIELDS",
            "COACH_COMPETITION_OPTIONAL_FIELDS",
            "_existing_coach_competition",
            "_merge_coach_competition_update",
            "_normalized_coach_competition",
            "_insert_coach_competition",
            "_update_coach_competition",
            "_save_normalized_coach_competition",
            "save_coach_competition",
            "delete_coach_competition",
            "resolve_competition_conflict",
        ),
    ),
    (
        "backend.planning.adaptive",
        (
            "AdaptiveReplanApplyService",
            "AdaptiveDependencies",
            "apply_adaptive_changes",
            "workout_is_hard",
            "_adaptive_recovery_description",
            "adaptive_recovery_description",
            "adaptive_recovery_replacement",
            "private_calendar_adjustment_context",
            "_adaptive_quick_action_blockers",
            "adaptive_quick_action_blockers",
            "adaptive_workout_fingerprint",
            "illness_pause_forecast",
            "illness_pause_replacement",
            "illness_calendar_events",
            "_planning_transaction",
            "_illness_checkin_values",
            "_upsert_illness_checkin",
            "_fill_illness_checkins",
            "_adaptive_change_stale_reason",
            "_apply_adaptive_change",
            "_apply_adaptive_changes",
            "_adaptive_replan_status",
        ),
    ),
    (
        "backend.planning.season",
        (
            "season_plan_summary",
            "planning_state",
        ),
    ),
    (
        "backend.planning.context",
        (
            "selected",
            "compact_sport_settings",
            "compact_wellness_sport_info",
            "compact_snapshot",
            "local_calendar_library_entries",
        ),
    ),
    (
        "backend.planning.calendar",
        (
            "_naive_calendar_datetime",
            "_calendar_duration_minutes",
            "_calendar_interval_end",
            "_calendar_interval",
            "_calendar_items_conflict",
            "_calendar_conflict_record",
            "calendar_conflicts_for_items",
            "_calendar_conflicts_for_items",
        ),
    ),
    (
        "backend.planning.adaptive_preview_service",
        (
            "AdaptiveReplanPreviewService",
            "latest_replan_preview",
            "current_adaptive_replan_status",
            "latest_illness_pause_state",
            "_adaptive_preview_calendar_context",
            "_adaptive_preview_feedback_signals",
            "_adaptive_preview_approve_existing_pause",
            "_adaptive_preview_environment",
            "_adaptive_preview_calendar_limits",
            "_adaptive_preview_reasons",
            "_adaptive_preview_change_state",
            "_adaptive_preview_replacement",
            "_adaptive_preview_needs_change",
            "_adaptive_preview_change_result",
            "_adaptive_preview_change",
            "adaptive_replan_preview",
        ),
    ),
    (
        "backend.planning.daily_context_service",
        (
            "DailyPlanningContextService",
            "daily_planning_context",
        ),
    ),
    (
        "backend.planning.local_plan_creation_service",
        (
            "LocalTrainingPlanCreationService",
            "_create_training_plan_record",
            "_planned_workout_for_storage",
            "_save_local_plan_entries",
            "_save_workout_library_entries_in_db",
            "save_workout_library_entries",
            "_validate_plan_calendar",
        ),
    ),
    (
        "backend.planning.training_plan_artifact_service",
        (
            "TrainingPlanArtifactService",
            "_stage_coach_artifact",
            "_stage_structured_training_plan",
            "_commit_structured_training_plan",
            "_persist_committed_training_plan",
            "_validate_committed_training_plan",
        ),
    ),
    (
        "backend.planning.calendar_read_model",
        ("project_planning_calendar",),
    ),
    (
        "backend.planning.replacement_service",
        (
            "StructuredTrainingPlanReplacementService",
            "_replacement_existing_state",
            "_replacement_entries",
            "_validate_replacement_calendar",
            "_archive_replacement_entries",
            "_archive_superseded_training_plans",
            "_create_replacement_plan",
            "_copy_replacement_constraints",
            "_create_replacement_units",
            "_replace_structured_training_plan",
        ),
    ),
    (
        "backend.planning.calendar_service",
        (
            "CalendarConflictService",
            "_calendar_conflict_sources",
            "calendar_conflicts",
        ),
    ),
    (
        "backend.http_api.pagination",
        (
            "API_PAGE_DEFAULT",
            "API_PAGE_MAX",
            "api_page_limit",
            "encode_page_cursor",
            "decode_page_cursor",
        ),
    ),
    (
        "backend.planning.state_service",
        (
            "STRUCTURED_TRAINING_STATE_PAGE_LIMIT",
            "StructuredTrainingStateService",
            "_structured_training_state_after_key",
            "_structured_training_state_snapshot",
            "_structured_training_target_ref",
            "_structured_training_state_page",
            "_structured_training_state",
        ),
    ),
    (
        "backend.planning.planned_unit_service",
        (
            "PlannedUnitService",
            "_insert_planned_unit",
            "_persist_local_planned_unit",
            "create_local_planned_unit",
            "list_planned_units",
            "_load_local_planned_workout",
            "_delete_local_planned_workout",
            "_save_local_planned_workout_update",
            "_update_local_planned_workout_in_db",
            "update_local_planned_workout",
            "_open_planned_unit_conflict",
            "_keep_local_planned_unit_conflict",
            "_adopt_remote_deletion",
            "_adopt_remote_planned_unit",
            "resolve_planned_unit_conflict",
            "list_local_planned_workouts",
            "list_dated_local_planned_workouts",
            "list_coach_planned_workouts",
        ),
    ),
    (
        "backend.planning.library_service",
        (
            "WorkoutLibraryService",
            "INSERT_LIBRARY_SQL",
            "create_local_workout_library_entry",
            "create_local_library_template",
            "list_workout_library",
            "_list_workout_library_in_db",
            "_stored_workout_library_entry",
            "_delete_local_workout_library_entry",
            "update_workout_library_entry",
        ),
    ),
    (
        "backend.history.service",
        (
            "ChangeHistoryService",
            "list_change_history",
            "_history_current",
            "_history_current_record",
            "_history_target",
        ),
    ),
    (
        "backend.history.undo_service",
        (
            "HistoryUndoService",
            "_history_preview",
            "_undo_history_state",
            "_undo_profile_change",
            "_undo_workout_library_change",
            "_undo_competition_change",
            "_planned_unit_undo_state",
            "_validate_planned_unit_undo_date",
            "_undo_existing_planned_unit",
            "_undo_planned_unit_change",
            "_undo_training_plan_change",
            "UNDO_ENTITY_HANDLERS",
            "_apply_change_undo",
        ),
    ),
    (
        "backend.planning.library_plan_service",
        (
            "WorkoutLibraryPlanService",
            "_validate_library_plan_entries",
            "_library_plan_request",
            "_library_plan_requests",
            "_library_plan_conflicts",
            "_raise_library_plan_conflicts",
            "_apply_library_plan_request",
            "apply_workout_library_plan",
        ),
    ),
    (
        "backend.planning.library",
        (
            "LIBRARY_WORKOUT_FIELDS",
            "_library_workout_local_id",
            "_library_workout_external_id",
            "_library_workout_ids",
            "_library_workout_projection",
            "_normalize_library_workout_text_fields",
            "_normalize_library_workout_duration",
            "normalize_library_workout",
            "workout_library_type",
            "normalized_workout_text",
            "library_workout_matches",
            "library_workout_duration_minutes",
            "compatible_workout_duration",
            "_similar_library_workout_inputs",
            "_validated_library_candidate",
            "_similar_library_candidate_score",
            "find_similar_library_workout",
            "PAYLOAD_HASH_PATTERN",
            "LIBRARY_BULK_MAX_ENTRIES",
            "_library_bulk_entry_id",
            "_library_bulk_entry_date",
            "_library_bulk_entry_hash",
            "_library_bulk_request_entry",
            "_library_bulk_request_entries",
            "library_bulk_request_entries",
            "_library_payload_hash",
            "library_payload_hash",
            "workout_library_entry_id",
            "workout_library_update_candidate",
            "_library_workout_as_number",
            "_reconcile_updated_library_workout_content",
            "_preserve_library_workout_metadata",
            "updated_workout_library_entry",
        ),
    ),
    (
        "backend.planning.planned_units",
        (
            "_planned_unit_payload_hash",
            "planned_unit_payload_hash",
            "_planned_unit_metadata",
            "normalize_planned_unit",
            "_planned_workout_update_request",
            "planned_workout_update_request",
            "_planned_workout_update_candidate",
            "planned_workout_update_candidate",
            "prepare_planned_workout_date",
            "planned_conflict_resolution_request",
            "planned_conflict_payload",
            "_reconcile_updated_planned_workout_content",
            "_preserve_local_planned_workout_metadata",
            "_normalized_planned_workout_update",
            "normalized_planned_workout_update",
            "_remote_planned_unit_id",
            "_remote_planned_unit_date",
            "_remote_planned_unit_duration",
            "_remote_planned_unit_payload",
            "remote_planned_unit_payload",
            "_remote_planned_unit_existing_state",
            "remote_planned_unit_existing_state",
            "_validate_planned_workout_date",
            "_planned_conflict_resolution_request",
            "_planned_conflict_payload",
        ),
    ),
    (
        "backend.planning.revision",
        (
            "PlanningRevisionService",
            "_PLANNING_STATE_RESET_PENDING",
            "_bump_planning_revision",
        ),
    ),
    (
        "backend.planning.training_plans",
        (
            "TrainingPlanService",
            "COACH_PLAN_CONSTRAINTS_PREFIX",
            "TRAINING_PLAN_STATUS_ALIASES",
            "TRAINING_PLAN_STATUSES",
            "_member_dates",
            "_candidate",
            "list_training_plans",
            "_normalise_training_plan_id",
            "update_training_plan",
            "update_plan_bounds",
            "update_plan_metadata",
        ),
    ),
    (
        "backend.planning.workouts",
        (
            "COACH_EVENT_EXTERNAL_PREFIX",
            "INTERVALS_WORKOUT_SPORTS",
            "INTERVALS_WORKOUT_TYPES",
            "INTERVALS_ENDURANCE_WORKOUT_TYPES",
            "WORKOUT_STEP_QUANTITY",
            "WORKOUT_STEP_QUANTITY_UNITS",
            "WORKOUT_STEP_TIME_UNITS",
            "intervals_workout_sport",
            "_workout_step_amounts",
            "_raise_ambiguous_workout_step",
            "_is_composite_duration",
            "_validate_endurance_workout_steps",
            "_structured_workout_duration",
            "_validate_workout_duration_match",
            "validate_workout_description",
            "workout_event_payload",
            "validate_intervals_workout_result",
            "normalize_workout",
        ),
    ),
    (
        "backend.weather.cache",
        (
            "CACHE_KEY",
            "FAILURE_KEY",
            "HISTORY_KEY",
            "WeatherCacheState",
            "cache_state",
            "retry_wait",
            "failure_record",
            "unavailable_state",
            "ready_state",
            "invalidate_for_location_change",
            "_WeatherCacheState",
            "_weather_cache_state",
            "_weather_retry_wait",
            "_weather_unavailable_state",
            "_weather_ready_state",
        ),
    ),
    (
        "backend.weather.history",
        (
            "decode_history",
            "remember_forecasts",
            "calendar_state",
            "add_to_planned",
            "_saved_daily_history",
            "_remember_calendar_weather",
            "_calendar_weather_state",
        ),
    ),
    (
        "backend.weather.service",
        (
            "WeatherService",
            "WEATHER_LOCK",
            "_record_weather_refresh_failure",
            "_refresh_weather_state",
            "weather_state",
        ),
    ),
    (
        "backend.athlete.checkins",
        (
            "CHECKIN_SCORE_FIELDS",
            "CHECKIN_TEXT_LIMITS",
            "CheckinService",
            "bounded_minutes",
            "bounded_score",
            "normalize_checkin",
        ),
    ),
    (
        "backend.activities.identity",
        ("activity_datetime", "activity_kind", "intervals_activity_device_source"),
    ),
    (
        "backend.activities.calendar_projection",
        (
            "CALENDAR_ACTIVITY_FIELDS",
            "_activity_metric",
            "activity_metric",
            "calendar_activity_payload",
            "calendar_activity_identity",
            "_workout_duration",
            "_workout_load",
            "_workout_compliance_basis",
            "_workout_compliance_percentage",
            "workout_compliance",
            "_planning_compliance_rows",
            "_weekly_compliance_values",
            "_weekly_compliance_row",
            "planning_compliance_state",
            "training_calendar_items",
        ),
    ),
    (
        "backend.activities.detail_projection",
        (
            "COACH_ACTIVITY_DETAIL_FIELDS",
            "COACH_ACTIVITY_DETAIL_STREAM_FIELDS",
            "COACH_ACTIVITY_DETAIL_LAP_FIELDS",
            "COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS",
            "COACH_ACTIVITY_DETAIL_MAX_LAPS",
            "_analysis_scalar",
            "_downsample_series",
            "_analysis_laps",
            "detailed_coach_activity",
            "detailed_activity",
        ),
    ),
    (
        "backend.activities.duplicates",
        (
            "deduplicate_api_records",
            "_garmin_duplicate_measurements",
            "_garmin_activity_matches",
            "garmin_activity_duplicates_intervals",
            "filter_garmin_activities",
            "intervals_cycling_activities_match",
            "_latest_activity_id",
            "_wahoo_garmin_pairs",
            "_wahoo_garmin_duplicate_view",
            "latest_wahoo_garmin_duplicate",
            "duplicate_delete_action",
            "validate_duplicate_delete",
            "remove_activity_from_snapshot",
            "duplicate_activity_delete_preview",
            "assert_duplicate_action_preview_is_current",
            "_remove_intervals_activity_from_local_snapshot",
            "delete_duplicate_intervals_activity",
        ),
    ),
    (
        "backend.activities.duplicate_service",
        ("DuplicateActivityService",),
    ),
    (
        "backend.activities.matching",
        (
            "is_planned_workout_event",
            "record_date",
            "_planned_workout_rows",
            "_activities_by_paired_event_id",
            "_paired_activity_match",
            "_unpaired_activity_match",
            "match_planned_workouts",
        ),
    ),
    (
        "backend.activities.read_service",
        (
            "ALL_DAYS",
            "PAGE_DEFAULT",
            "PAGE_MAX",
            "_first_present",
            "_page_key",
            "_encode_cursor",
            "_decode_cursor",
            "_page_limit",
            "ActivityReadService",
            "activity_page_key",
            "paged_activities",
            "list_recent_activities",
            "get_activity_details",
        ),
    ),
    (
        "backend.providers.weather",
        (
            "WEATHER_ICON_D2_DAYS",
            "NRW_LATITUDE_BOUNDS",
            "NRW_LONGITUDE_BOUNDS",
            "WeatherClient",
            "_weather_geocoded_location",
            "_weather_fetch_icon_d2",
            "_fetch_weather_forecast",
        ),
    ),
    (
        "backend.performance.morning_battery",
        (
            "timestamp",
            "_first_present",
            "_sleep_interval",
            "sleep_bounds",
            "_number",
            "body_battery_samples",
            "morning_body_battery_record",
            "cached_result",
            "_garmin_timestamp",
            "_garmin_sleep_interval",
            "_garmin_nested_sleep_records",
            "_garmin_sleep_bounds",
            "_garmin_body_battery_sample",
            "_garmin_body_battery_samples",
            "_morning_body_battery_record",
            "_morning_body_battery_cached_result",
        ),
    ),
    (
        "backend.performance.morning_battery_service",
        (
            "MorningBodyBatteryService",
            "_garmin_morning_body_battery",
            "_persist_morning_body_battery",
            "_sync_morning_body_battery_locked",
            "sync_garmin_morning_body_battery",
            "refresh_morning_body_battery",
        ),
    ),
    (
        "backend.providers.garmin_morning",
        (
            "fetch_morning_body_battery",
            "merge_garmin_records",
            "_morning_body_battery_remote_payload",
            "_merge_garmin_records",
        ),
    ),
    (
        "backend.calendar.canonical",
        (
            "_canonical_remote_indexes",
            "_canonical_linked_remote",
            "_canonical_local_event_identity",
            "_canonical_local_event",
            "_canonical_remote_event",
            "_canonical_planned_workout_sort_key",
            "_canonical_local_events",
            "_canonical_unjoined_remote_events",
            "canonical_planned_workouts",
        ),
    ),
    (
        "backend.calendar.local",
        (
            "_local_calendar_competition",
            "_local_calendar_external_event",
            "_local_calendar_sort_key",
            "local_calendar_events",
        ),
    ),
    (
        "backend.calendar.public_events",
        (
            "list_sources",
            "list_candidates",
            "state",
            "list_public_calendar_sources",
            "list_public_event_candidates",
            "public_calendar_state",
        ),
    ),
    (
        "backend.calendar.external",
        (
            "ExternalCalendarReader",
            "list_events",
            "state",
            "list_external_calendar_events",
            "external_calendar_state",
        ),
    ),
    (
        "backend.planning.context",
        (
            "PLANNING_CONTEXT_CHECKIN_FIELDS",
            "PLANNING_CONTEXT_WEATHER_FIELDS",
            "PLANNING_CONTEXT_APPOINTMENT_FIELDS",
            "external_calendar_event_dates",
            "_planning_context_date",
            "_planning_context_day",
            "_add_planned_context",
            "_add_checkin_context",
            "_add_calendar_context",
            "_add_feedback_context",
            "_add_weather_context",
            "_add_planning_context_signals",
            "_finalize_planning_context",
        ),
    ),
    (
        "backend.performance.planning_recovery",
        (
            "_add_planning_recovery_value",
            "_planning_sleep_hours",
            "_add_intervals_planning_recovery",
            "_add_garmin_planning_recovery_record",
            "_add_garmin_planning_recovery",
            "_add_morning_battery_recovery",
            "_planning_recovery_by_date",
        ),
    ),
    (
        "backend.activities.grouping",
        (
            "_cycling_event_candidates",
            "_cycling_event_interval",
            "_cycling_intervals_share_group",
            "_cycling_event_edges",
            "_cycling_event_group",
            "parallel_cycling_event_groups",
        ),
    ),
    (
        "backend.activities.feedback",
        (
            "ACTIVITY_FEEDBACK_TEXT_LIMITS",
            "ActivityFeedbackService",
            "normalize_activity_feedback",
        ),
    ),
    (
        "backend.weather.recommendations",
        (
            "is_outdoor_activity",
            "is_cycling_activity",
            "_weather_training_windows",
            "_weather_interval_summary",
            "_weather_window_score",
            "_weather_interval_is_usable",
            "_weather_candidate_windows",
            "weather_recommendation",
            "weather_recommendations",
        ),
    ),
    (
        "backend.weather.adaptive",
        (
            "WEATHER_ADAPTIVE_DAYS",
            "WEATHER_ADAPTIVE_LONG_RIDE_MINUTES",
            "_weather_adaptive_duration_minutes",
            "_weather_adaptive_forecast",
            "_weather_adaptive_precipitation",
            "_weather_adaptive_details",
            "weather_adaptive_reason",
        ),
    ),
    (
        "backend.weather.forecast",
        (
            "_overlay_weather_values",
            "merge_weather_forecasts",
            "weather_forecast_params",
            "weather_forecast_is_complete",
        ),
    ),
    (
        "backend.performance.garmin_observations",
        (
            "garmin_record_observation_date",
            "garmin_nested_records",
            "garmin_source_observed_at",
            "garmin_sleep_observation_date",
            "garmin_sleep_ready_for_checkin",
        ),
    ),
    (
        "backend.performance.activity_validation",
        (
            "activity_pace_seconds_per_km",
            "latest_activity_for_validation",
            "bounded_activity_metric",
            "activity_intensity",
            "activity_validation_evidence",
            "activity_direct_estimates",
            "bounded_performance_metric",
            "cycling_activity_validation_details",
            "activity_validation_details",
            "activity_performance_validation",
            "activity_sport",
        ),
    ),
    (
        "backend.performance.load",
        (
            "_activity_rollup_date",
            "_activity_rollup_number",
            "_activity_rollup_totals",
            "activity_rollup",
            "_atl_wellness_rows",
            "_activity_load_by_date",
            "_atl_series_from_rows",
            "actual_atl_series",
        ),
    ),
    (
        "backend.performance.load_context",
        ("_performance_load_context", "performance_load_context"),
    ),
    (
        "backend.performance.current_metrics",
        (
            "sport_setting",
            "sport_info_setting",
            "intervals_eftp_value",
            "intervals_max_hr_metric",
            "threshold_pace_seconds",
            "zone2_pace_seconds",
            "height_in_cm",
            "_performance_snapshot_inputs",
            "_latest_ride_activity",
            "_first_performance_source",
            "_performance_body_metrics",
            "_preferred_performance_metric",
            "_performance_threshold_metrics",
            "_performance_vo2_and_prediction_metrics",
            "api_performance_metrics",
            "current_performance_metrics",
        ),
    ),
    (
        "backend.performance.comparisons",
        (
            "VO2MAX_UNIT",
            "performance_trend_average",
            "_performance_trend",
            "_performance_comparisons",
            "performance_comparisons",
        ),
    ),
    (
        "backend.performance.context",
        ("current_performance_context",),
    ),
    (
        "backend.performance.garmin_metrics",
        (
            "GARMIN_PERFORMANCE_SOURCE",
            "GARMIN_RUN_PREDICTION_SOURCE",
            "_garmin_key",
            "_garmin_numeric",
            "_garmin_vo2_value",
            "_garmin_colon_duration_seconds",
            "_garmin_duration_seconds",
            "garmin_duration_seconds",
            "_garmin_race_slot",
            "_garmin_race_time",
            "_collect_garmin_numeric_values",
            "_garmin_last_numeric",
            "_garmin_last_value",
            "_garmin_bounded_metric",
            "garmin_bounded_metric",
            "_garmin_pace_seconds",
            "_garmin_mapping_nodes",
            "_garmin_sport_category",
            "garmin_profile_max_hr",
            "_garmin_collect_vo2_values",
            "_garmin_vo2_metrics",
            "_garmin_store_race_value",
            "_garmin_store_direct_race_value",
            "_garmin_collect_race_predictions",
            "_garmin_race_predictions",
            "_garmin_threshold_metrics",
            "_garmin_activity_max_hr_samples",
            "_garmin_max_hr_samples",
            "_garmin_performance_units",
            "_garmin_performance_source_keys",
            "_garmin_activity_observed_at",
            "_garmin_performance_freshness",
            "garmin_performance_metrics",
            "garmin_performance_context",
        ),
    ),
    (
        "backend.performance.history",
        ("append_garmin_performance_history",),
    ),
    (
        "backend.performance.daily_health",
        (
            "GARMIN_DAILY_HEALTH_FIELDS",
            "_garmin_daily_health_by_date",
            "garmin_daily_health_by_date",
            "garmin_daily_health_metrics",
        ),
    ),
    (
        "backend.performance.eftp",
        (
            "_sport_info_setting",
            "_wellness_eftp_value",
            "_activity_eftp_value",
            "eftp_30_day_average",
        ),
    ),
    (
        "backend.performance.wellness",
        (
            "wellness_average",
            "comparison_value",
            "wellness_form_value",
            "readiness_score_value",
            "wellness_form_average",
        ),
    ),
    (
        "backend.performance.max_hr",
        ("garmin_activity_max_hr", "merge_garmin_max_hr"),
    ),
    (
        "backend.performance.freshness",
        ("measurement_age", "garmin_source_freshness", "garmin_metric_freshness"),
    ),
    (
        "backend.performance.garmin_projection",
        (
            "GARMIN_CONTEXT_FIELDS",
            "GARMIN_RECOVERY_FIELDS",
            "compact_garmin_context",
            "latest_garmin_record",
            "compact_garmin_recovery",
        ),
    ),
    (
        "backend.performance.garmin_weight",
        (
            "_garmin_weight_kg",
            "_garmin_record_date",
            "_collect_garmin_weight_records",
            "garmin_weight_records",
            "garmin_weight_metric",
            "garmin_weight_average",
        ),
    ),
    (
        "backend.performance.recovery",
        (
            "_dated_garmin_recovery_records",
            "dated_garmin_recovery_records",
            "garmin_recovery_metric",
            "garmin_recovery_average",
        ),
    ),
    (
        "backend.performance.recovery_context",
        (
            "_garmin_sleep_recovery",
            "_intervals_sleep_recovery",
            "_performance_sleep_recovery",
            "_performance_recovery_metric",
            "_performance_readiness",
            "_performance_recovery_context",
            "performance_recovery_context",
        ),
    ),
    (
        "backend.performance.trends",
        ("garmin_history_average", "intervals_performance_average"),
    ),
    (
        "backend.weather.projection",
        (
            "WEATHER_FORECAST_DAYS",
            "WEATHER_CONDITIONS",
            "WEATHER_ICONS",
            "_weather_number",
            "weather_number",
            "_weather_icon",
            "weather_icon",
            "_weather_array_value",
            "_weather_daily_peak_time",
            "_weather_daily_sun_time",
            "_weather_daily_row",
            "_weather_daily_summary",
            "daily_summary",
            "_weather_hourly_rows",
            "hourly_rows",
        ),
    ),
    ("backend.runtime.events", ("StateEventBuffer", "STATE_EVENT_BUFFER")),
    (
        "backend.runtime.maintenance",
        (
            "MaintenanceGate",
            "MAINTENANCE_GATE",
            "maintenance_operation",
            "claimed_maintenance_operation",
        ),
    ),
    (
        "backend.settings",
        (
            "SettingsService",
            "MODEL_OPTIONS",
            "GEMINI_MODEL_OPTIONS",
            "THINKING_LEVEL_OPTIONS",
            "CALENDAR_DISPLAY_DEFAULTS",
            "CALENDAR_DISPLAY_MAX_WEEKS",
            "available_ai_providers",
            "selected_ai_provider",
            "save_ai_provider",
            "available_model_options",
            "selected_model",
            "save_model",
            "available_thinking_level_options",
            "selected_thinking_level",
            "save_thinking_level",
            "calendar_display_settings",
            "save_calendar_display_settings",
        ),
    ),
    (
        "backend.observability",
        (
            "Redactor",
            "JsonLogFormatter",
            "DiagnosticCapture",
            "configure_logging",
            "initialise_logging",
            "external_result_context",
            "safe_provider_path",
            "safe_response_headers",
            "safe_url_netloc",
            "safe_diagnostic_context",
            "safe_diagnostic_error",
            "diagnostic_mapping_shape",
            "diagnostic_sequence_shape",
            "diagnostic_response_shape",
            "diagnostic_capture_response",
            "redact_text",
            "sanitize_log_value",
        ),
    ),
    (
        "backend.config",
        ("load_local_env", "security_configuration_error", "save_persistent_settings"),
    ),
    (
        "backend.providers.http",
        (
            "ProviderHTTPError",
            "ProviderInvalidResponse",
            "ProviderRequestCancelled",
            "ProviderResponseTooLarge",
            "JsonResponse",
            "JsonHttpClient",
            "request_body",
            "json_request_parts",
            "open_interruptibly",
            "read_response",
            "request_json",
            "read_error_body",
            "error_detail",
            "external_call",
            "multipart_form_data",
        ),
    ),
    (
        "backend.providers.audio",
        ("VOICE_AUDIO_TYPES", "normalized_audio_type", "audio_suffix", "AudioTranscriptionClient"),
    ),
    ("backend.providers.intervals", ("IntervalsApiClient",)),
    (
        "backend.providers.openai",
        (
            "OPENAI_RATE_LIMIT_HEADERS",
            "OpenAIResponsesClient",
            "OpenAIStreamConfig",
            "OpenAIStreamTelemetry",
            "OpenAIStreamClient",
            "response_id",
            "poll_background_response",
            "request_with_conversation_retry",
            "responses_payload",
            "consume_sse_event",
            "StreamReadResult",
            "StreamReadState",
            "read_stream_response",
            "request_stream_response",
            "endpoint",
            "OpenAIResponseFailure",
            "validate_response",
            "retry_after_seconds",
            "error_diagnostic_details",
            "error_details",
            "safe_log_reason",
            "rate_limit_snapshot",
        ),
    ),
    (
        "backend.providers.gemini",
        (
            "GeminiJsonClient",
            "GeminiStreamClient",
            "StreamAccumulator",
            "StreamReadResult",
            "read_stream_response",
            "response_text",
            "function_tools",
            "input_parts",
            "request_payload",
            "error_details",
            "_provider_error_payload",
            "_gemini_error_tokens",
            "_gemini_error_reason",
        ),
    ),
    (
        "backend.providers.usage",
        ("daily_summary", "usage_counts", "recorded_usage"),
    ),
    ("backend.providers.state", ("ProviderStateService",)),
    (
        "backend.providers.calendar",
        (
            "MAX_EXTERNAL_CALENDAR_BYTES",
            "CALENDAR_FETCH_TIMEOUT_SECONDS",
            "CALENDAR_CONNECTION_TIMEOUT_SECONDS",
            "EXTERNAL_CALENDAR_WINDOW_DAYS",
            "ICAL_MAX_RECURRENCE_COUNT",
            "ICAL_MAX_RECURRENCE_PERIODS",
            "parse_ics_value",
            "parse_ics_date",
            "unfold_ical",
            "ical_duration",
            "ical_training_impact",
            "ical_training_relevant",
            "ical_no_intensity",
            "ical_short_only",
            "parse_ical_calendar",
            "external_calendar_url",
            "fetch_calendar_feed",
            "_resolve_calendar_addresses",
            "_calendar_url_parts",
            "_calendar_feed_request",
            "_calendar_fetch_remaining",
            "_fetch_calendar_address",
            "_calendar_fetch_failure_log",
            "_ical_temporal_value",
            "_ical_rule_values",
            "_ical_rule_integer",
            "_ical_rule_bydays",
            "_ical_rrule",
            "_ical_shift_local",
            "_ical_matches_byday",
            "_ical_matches_date_filters",
            "_ical_period_dates",
            "_ical_apply_bysetpos",
            "_ical_add_start",
            "_ical_daily",
            "_ical_weekly",
            "_ical_period",
            "_ical_recurrence_starts",
            "_ical_duration",
            "_ical_overlaps",
            "_ical_instances",
            "_ical_property_parameters",
            "_ical_store_property",
            "_ical_parsed_events",
            "_ical_window",
        ),
    ),
    ("backend.http_api.responses", ("json_bytes",)),
    (
        "backend.http_api.public_state",
        ("PublicStateDependencies", "PublicStateService"),
    ),
    (
        "backend.http_api.static_assets",
        (
            "StaticAssetResponse",
            "StaticAssetService",
            "ASSET_INDEX_HTML",
            "ASSET_API_JS",
            "ASSET_APP_JS",
            "ASSET_NAVIGATION_JS",
            "ASSET_STATE_JS",
            "ASSET_VIEWS_JS",
            "ASSET_FORMS_JS",
            "ASSET_COMPONENTS_JS",
            "ASSET_STYLES_CSS",
            "ASSET_SERVICE_WORKER_JS",
            "ASSET_MANIFEST",
            "ASSET_LOGO",
            "ASSET_ICON",
            "STATIC_TARGETS",
            "VERSIONED_STATIC_ASSETS",
            "STATIC_REVALIDATE_ASSETS",
            "STATIC_IMMUTABLE_MAX_AGE",
        ),
    ),
    (
        "backend.http_api.rate_limit",
        (
            "RateLimiter",
            "RATE_LIMIT_CLEANUP_INTERVAL_SECONDS",
            "RATE_LIMIT_CLEANUP_BATCH_SIZE",
            "RATE_LIMIT_BUCKET_MAX_AGE_SECONDS",
        ),
    ),
    ("backend.sync.windows", ("split_date_windows",)),
    (
        "backend.sync.daily",
        ("DailySyncMarkerService", "daily_sync_due", "mark_daily_sync"),
    ),
    (
        "backend.sync.garmin",
        (
            "GarminFixtureLoader",
            "GarminPayloadService",
            "GarminSyncStateService",
            "GARMIN_COLLECTION_SOURCES",
            "GARMIN_METRIC_SOURCES",
            "GARMIN_CAPABILITY_FAILURE_LIMIT",
            "GARMIN_CAPABILITY_PAUSE_SECONDS",
            "normalize_fixture_sleep_dates",
            "merge_sources",
            "_merge_garmin_source",
            "collection_complete",
        ),
    ),
    (
        "backend.sync.garmin_service",
        (
            "GarminRemoteReader",
            "GarminSyncService",
            "GARMIN_SYNC_LOCK",
            "shared_garmin_sync_lock",
        ),
    ),
    (
        "backend.sync.garmin_projection_service",
        ("GarminProjectionService", "garmin_public_state", "garmin_coach_context"),
    ),
    (
        "backend.sync.full_resync",
        ("FullProviderResyncService", "PROVIDER_RESYNC_KEYS"),
    ),
    (
        "backend.sync.external_calendar",
        (
            "ExternalCalendarSyncService",
            "EXTERNAL_CALENDAR_SYNC_LOCK",
            "shared_external_calendar_sync_lock",
        ),
    ),
    (
        "backend.sync.intervals",
        (
            "IntervalsSnapshotReader",
            "IntervalsSnapshotService",
            "IntervalsSyncWorkflow",
            "IntervalsSyncStatus",
            "IntervalsSyncJournal",
            "IntervalsSyncRuntime",
            "IntervalsSyncService",
        ),
    ),
    ("backend.sync.queue", ("SyncJobQueueService",)),
    ("backend.sync.job_outcomes", ("SyncJobOutcomeService",)),
    ("backend.sync.executor", ("SyncJobExecutor",)),
    (
        "backend.sync.worker",
        ("SyncJobWorker", "shared_sync_job_wake_event"),
    ),
    (
        "backend.http_api.state_versions",
        ("StateVersionService", "state_versions"),
    ),
    (
        "backend.sync.status",
        (
            "SyncPublicStateService",
            "sync_public_state",
            "sync_status_state",
            "sync_browser_state",
        ),
    ),
    (
        "backend.sync.observation",
        (
            "SyncOperationObserver",
            "OperationScope",
            "operation_context",
            "operation_trigger",
            "operation_error_code",
            "operation_result_count",
            "refresh_status",
            "log_operation_event",
            "observed_sync",
        ),
    ),
    (
        "backend.sync.selected",
        (
            "SelectedWorkoutSyncService",
            "_sync_local_workout_calendar_entry",
            "sync_local_workout_library_entry",
            "_sync_selected_workout_library",
            "_selected_library_sync_row",
            "_library_sync_error",
            "_sync_selected_planned_library_entry",
            "_sync_existing_library_calendar_entry",
            "_sync_pending_library_entry",
            "_sync_selected_library_entry",
            "_verify_selected_library_repair",
            "_sync_selected_workout_library_unlocked",
        ),
    ),
    (
        "backend.sync.performance",
        (
            "PerformanceRefreshFollowupService",
            "PerformanceRefreshService",
            "PERFORMANCE_LOCK",
            "refresh_current_performance",
        ),
    ),
    ("backend.sync.weather", ("WeatherSyncService",)),
    (
        "backend.sync.adaptive",
        ("AdaptivePreviewFollowupService", "IllnessPauseSyncService", "check_adaptive_replan", "sync_illness_pause_to_intervals", "_adaptive_replan_result", "apply_adaptive_replan"),
    ),
    (
        "backend.sync.commands",
        ("ProviderRefreshCommandService", "_start_structured_provider_refresh", "_run_structured_intervals_refresh", "_retry_structured_intervals_refresh", "_queue_structured_performance_refresh"),
    ),
    (
        "backend.sync.conflict_commands",
        ("SyncConflictCommandService", "_resolve_structured_sync_conflict"),
    ),
    (
        "backend.sync.plan_commands",
        ("PlanPushCommandService", "_enqueue_coach_plan_push"),
    ),
    (
        "backend.sync.plan_selection",
        (
            "StructuredPlanSyncService",
            "_sync_structured_plan_without_entries",
            "_validate_selected_plan_sync_entries",
            "_persist_selected_plan_sync_entries",
            "_sync_structured_plan_entries",
        ),
    ),
    (
        "backend.sync.plan_repair",
        (
            "PlanRepairManifestService",
            "_repair_manifest_rows",
            "_repair_manifest_entries",
            "_validate_repair_manifest_selection",
            "_validate_repair_manifest_workouts",
            "_refresh_repair_manifest_hashes",
            "_coach_repair_manifest",
        ),
    ),
    (
        "backend.sync.authority",
        ("PlanningAuthorityService", "pending_plan_push_entries", "mark_planning_authoritative", "mark_competitions_authoritative"),
    ),
    ("backend.sync.freshness", ("provider_freshness_state",)),
    (
        "backend.sync.refresh",
        (
            "ProviderRefreshTracker",
            "_provider_refresh_cleanup",
            "_provider_refresh_start",
            "_provider_refresh_finish",
            "_provider_refresh_error_code",
        ),
    ),
    (
        "backend.sync.intervals_state",
        (
            "calendar_window",
            "connection_state",
            "decode_pagination",
            "_intervals_calendar_window",
            "_intervals_connection_state",
            "intervals_public_state",
        ),
    ),
    ("backend.db.schema", ("database_table_names",)),
    ("backend.db.bootstrap", ("initialize_application_database",)),
    ("backend.http_api.bootstrap_state", ("PublicBootstrapService", "bootstrap_provider_states")),
    ("backend.http_api.state_events_transport", ("StateEventTransport",)),
    ("backend.backup.restore", ("DatabaseRestoreService",)),
)

FORBIDDEN_SERVER_SYMBOLS = (
    "_structured_tool_call_failure",
    "_execute_structured_coach_tool",
    "_prepare_structured_plan_sync",
    "_prepare_structured_tool_execution",
    "_cached_structured_tool_call",
    "output_text",
    "_mark_resolved_coach_receipts",
    "_coach_effects",
    "_structured_coach_outcome_text",
    "_persist_structured_coach_pending_request",
    "_structured_coach_outcome_status",
    "_structured_coach_outcome",
    "_structured_tool_call_metadata",
    "restore_database_backup",
    "_replace_database_with_restore",
    "_resume_after_database_restore",
    "_restore_database_backup",
    "_structured_bounded_integer",
    "_structured_coach_read_result",
    "_structured_coach_training_template_result",
    "public_state",
    "stream_database_backup",
    "stream_privacy_export",
    "SESSION_LOCK",
    "SESSION_LAST_CLEANUP_MONOTONIC",
    "authenticated_session",
    "login_user",
    "logout_user",
    "require_auth",
    "require_csrf",
    "cleanup_expired_sessions",
    "session_cookie_headers",
    "_restore_coach_session_csrf_hash",
    "public_performance_state",
    "public_feedback_state",
    "public_bootstrap",
    "bootstrap_provider_states",
    "_delete_reset_coach_conversation",
    "_cancel_reset_coach_commands",
    "_structured_coach_apply_library_plan_result",
    "_structured_coach_plan_artifact_result",
    "_replace_structured_coach_training_plan",
    "_validate_structured_training_change_scopes",
    "_apply_structured_coach_training_changes",
    "_check_dialogue_plan_date",
    "_validate_dialogue_plan_changes",
    "_validate_dialogue_plan_artifact",
    "_validate_dialogue_plan_scope",
    "_dialogue_retry_metadata",
    "_validate_dialogue_request_target",
    "_validate_dialogue_scope_objects",
    "_validate_dialogue_repair_scope",
    "_apply_dialogue_operation_scope",
    "_dialogue_action",
    "_save_coach_question",
    "_validate_training_patch_schedule",
    "_store_training_patch_constraints",
    "_apply_training_patch",
    "_append_template_command_scope",
    "_append_planning_command_scope",
    "_planning_command_intent",
    "_prepare_commit_planning_command",
    "_prepare_planning_command",
    "_claim_planning_command",
    "_execute_claimed_planning_command",
    "execute_planning_command",
    "_structured_coach_misc_tool_result",
    "_structured_coach_plan_tool_result",
    "_structured_coach_tool_result",
    "_reset_local_coach_chat_state",
    "_request_coach_operation_cancellation",
    "_clear_coach_conversation_state",
    "reset_coach_chat",
    "_configure_cipher",
    "_temporary_restore_database",
    "_validate_restore_connection",
    "_validate_restore_database",
    "_coach_session_key",
    "coach_command_receipt",
    "_require_command_owner",
    "_active_background_coach_job",
    "_coach_error_metadata",
    "_structured_command_failure_steps",
    "_structured_command_failure_base_response",
    "_structured_command_failure_effect_text",
    "_structured_command_failure_response",
    "_persist_structured_command_failure_pending_request",
    "_persist_structured_command_failure",
    "_structured_coach_request_payload",
    "_background_coach_request",
    "_background_coach_provider_settings",
    "_existing_background_coach_job_response",
    "_persist_background_coach_job",
    "enqueue_background_coach_job",
    "RATE_LIMIT_LOCK",
    "RATE_LIMITS",
    "RATE_LIMIT_CLEANUP_INTERVAL_SECONDS",
    "RATE_LIMIT_CLEANUP_BATCH_SIZE",
    "RATE_LIMIT_BUCKET_MAX_AGE_SECONDS",
    "RATE_LIMIT_LAST_CLEANUP_MONOTONIC",
    "allow_rate",
    "CHAT_STREAM_LOCK",
    "CHAT_STREAMS",
    "COACH_JOB_CANCEL_EVENTS",
    "register_chat_stream",
    "publish_chat_stream_event",
    "chat_stream_events",
    "unregister_chat_stream",
    "_claim_background_coach_job",
    "_requeue_background_coach_job",
    "resume_interrupted_coach_jobs",
    "_background_coach_message",
    "_coach_command_receipt",
    "_merge_coach_command_receipt",
    "_close_chat_provider_response",
    "_cancel_background_chat_job",
    "cancel_chat_stream",
    "readiness_state",
    "_enqueue_coach_plan_push",
    "_resolve_structured_sync_conflict",
    "check_adaptive_replan",
    "_start_structured_provider_refresh",
    "_run_structured_intervals_refresh",
    "_retry_structured_intervals_refresh",
    "_queue_structured_performance_refresh",
    "_structured_coach_checkin_result",
    "_structured_coach_activity_feedback_result",
    "_structured_coach_delete_activity_feedback_result",
    "_structured_coach_save_competition_result",
    "_structured_coach_delete_competition_result",
    "ATHLETE_RECORD_HANDLERS",
    "_structured_coach_athlete_record_result",
    "sync_illness_pause_to_intervals",
    "_adaptive_replan_result",
    "apply_adaptive_replan",
    "_pending_plan_push_entries",
    "_local_planning_authoritative_rows",
    "_mark_local_planning_row_authoritative",
    "_mark_local_planning_authoritative",
    "_mark_local_competitions_authoritative",
    "garmin_fixture_path",
    "load_garmin_fixture",
    "_normalize_fixture_sleep_dates",
    "_fixture_sleep_dates",
    "_shift_fixture_sleep_dates",
    "_merge_garmin_source",
    "merge_garmin_sources",
    "garmin_collection_complete",
    "_store_intervals_snapshot",
    "_seed_intervals_workout_library",
    "_record_intervals_sync_window",
    "set_sync_operation_state",
    "_completed_intervals_sync_result",
    "_wait_for_existing_intervals_sync",
    "_execute_intervals_sync",
    "_record_intervals_sync_failure",
    "_finish_intervals_sync",
    "sync_intervals",
    "persist_garmin_error",
    "_garmin_capability_state",
    "_garmin_capability_allowed",
    "_garmin_capability_failure",
    "_garmin_capability_success",
    "_garmin_error_entries",
    "_garmin_core_error_entries",
    "_set_garmin_error_entries",
    "_persist_garmin_sync_payload",
    "garmin_snapshot",
    "garmin_configured",
    "_sync_garmin_fixture_locked",
    "_garmin_remote_collection_options",
    "_sync_garmin_remote_locked",
    "_wait_for_existing_garmin_sync",
    "sync_garmin",
    "garmin_public_state",
    "garmin_coach_context",
    "annotate_garmin_activity_matches",
    "GARMIN_LOCK",
    "sync_weather",
    "sync_external_calendar",
    "EXTERNAL_CALENDAR_LOCK",
    "sync_competitions",
    "_claim_sync_job",
    "_historical_sync_window",
    "_historical_next_end",
    "_execute_intervals_sync_job",
    "_execute_garmin_sync_job",
    "_execute_intervals_specific_job",
    "_execute_sync_job",
    "_queue_next_historical_backfill",
    "_run_claimed_sync_job",
    "_sync_job_worker_loop",
    "start_sync_job_worker",
    "SYNC_JOB_WORKER_LOCK",
    "SYNC_JOB_WAKE",
    "SYNC_JOB_STOP",
    "state_versions",
    "sync_public_state",
    "sync_status_state",
    "sync_browser_state",
    "provider_resync_state",
    "_validate_full_provider_resync",
    "_full_provider_resync_details",
    "_run_full_provider_resync",
    "_start_full_provider_resync",
    "_complete_full_provider_resync",
    "_record_full_provider_resync_failure",
    "_finish_full_provider_resync",
    "full_provider_resync",
    "sync_job_state",
    "sync_jobs_state",
    "_sync_job_active",
    "_publish_created_sync_job",
    "enqueue_sync_job",
    "resume_interrupted_sync_jobs",
    "resolve_sync_job",
    "_publish_sync_job_snapshot",
    "_sync_job_update",
    "_sync_job_update_from_result",
    "_sync_job_fallback_status",
    "_requeue_claimed_sync_job",
    "_record_claimed_sync_job_failure",
    "_enqueue_automatic_performance_refresh",
    "_performance_refresh_failed",
    "_performance_refresh_poll_state",
    "_wait_for_performance_refresh",
    "OPERATION_CLEANUP_REASONS",
    "operation_trigger",
    "operation_error_code",
    "operation_result_count",
    "log_operation_event",
    "observed_operation",
    "observed_sync",
    "_local_calendar_library_entries",
    "list_checkins",
    "save_checkin",
    "save_coach_checkin",
    "local_feedback_context",
    "list_activity_feedback",
    "save_activity_feedback",
    "save_coach_activity_feedback",
    "activity_feedback_context",
    "activities_with_feedback",
    "_retry_after_seconds",
    "openai_error_diagnostic_details",
    "openai_error_details",
    "safe_openai_log_reason",
    "record_openai_rate_limits",
    "gemini_error_details",
    "_gemini_text",
    "_gemini_tools",
    "openai_endpoint",
    "_openai_response_id",
    "multipart_form_data",
    "normalized_audio_type",
    "VOICE_AUDIO_TYPES",
    "external_calendar_url",
    "fetch_calendar_feed",
    "_resolve_calendar_addresses",
    "_calendar_feed_request",
    "_calendar_fetch_remaining",
    "_fetch_calendar_address",
    "_calendar_fetch_failure_log",
    "_urlopen_interruptibly",
    "_read_http_response",
    "_read_openai_stream_response",
    "record_openai_status",
    "record_openai_success",
    "_persist_openai_rate_limits",
    "_openai_usage_summary_unlocked",
    "openai_usage_summary",
    "_record_openai_usage_unlocked",
    "record_openai_usage",
    "_provider_usage_summary",
    "gemini_usage_summary",
    "_record_gemini_status",
    "_record_gemini_usage",
    "_safe_response_headers",
    "external_call",
    "_validate_openai_response",
    "_provider_error_body",
    "_provider_error_text",
    "_intervals_error_detail",
    "_safe_interval_error_detail",
    "upstream_http_error_message",
    "_log_http_request_started",
    "_http_success_result",
    "_capture_http_failure",
    "_handle_http_error",
    "_handle_http_network_error",
    "_handle_http_app_error",
    "_handle_http_client_error",
    "http_json",
    "openai_request",
    "retrieve_openai_response",
    "cancel_openai_response",
    "gemini_raw_request",
    "openai_stream_request",
    "_log_openai_stream_failure",
    "_capture_openai_stream_failure",
    "_handle_openai_stream_app_error",
    "_handle_openai_stream_disconnect",
    "_handle_openai_stream_http_error",
    "_handle_openai_stream_timeout",
    "_handle_openai_stream_network_error",
)


def _python_files(root: Path) -> Iterable[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_entrypoint_module(value: str | None) -> bool:
    return value in {"server", "__main__"} or bool(value and value.startswith("server."))


def _import_aliases(tree: ast.AST) -> tuple[set[str], set[str], set[str], set[str]]:
    """Return reliable aliases for sys.modules and dynamic import APIs."""
    sys_names = {"sys"}
    importlib_names = {"importlib"}
    import_functions = {"__import__"}
    sys_modules_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == "sys":
                    sys_names.add(bound_name)
                elif alias.name == "importlib":
                    importlib_names.add(bound_name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if node.module == "sys" and alias.name == "modules":
                    sys_modules_names.add(bound_name)
                elif (
                    node.module == "importlib" and alias.name in {"import_module", "__import__"}
                ) or (node.module == "builtins" and alias.name == "__import__"):
                    import_functions.add(bound_name)
    return sys_names, importlib_names, import_functions, sys_modules_names


def _is_sys_modules(node: ast.AST, sys_names: set[str], sys_modules_names: set[str]) -> bool:
    dotted = _dotted_name(node)
    return dotted in {f"{name}.modules" for name in sys_names} or dotted in sys_modules_names


def _entrypoint_namespace_expression(
    node: ast.AST,
    sys_names: set[str],
    sys_modules_names: set[str],
) -> bool:
    if isinstance(node, ast.Subscript) and _is_sys_modules(node.value, sys_names, sys_modules_names):
        return _is_entrypoint_module(_literal_string(node.slice))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and _is_sys_modules(node.func.value, sys_names, sys_modules_names)
        and node.func.attr in {"get", "setdefault", "pop", "__getitem__"}
    ):
        return _is_entrypoint_module(_literal_string(node.args[0]) if node.args else None)
    return False


def _server_import_violations(path: Path, tree: ast.AST) -> list[str]:
    violations: list[str] = []
    sys_names, importlib_names, import_functions, sys_modules_names = _import_aliases(tree)
    entrypoint_bindings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _entrypoint_namespace_expression(
            node.value, sys_names, sys_modules_names
        ):
            entrypoint_bindings.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and _entrypoint_namespace_expression(
            node.value, sys_names, sys_modules_names
        ) and isinstance(node.target, ast.Name):
            entrypoint_bindings.add(node.target.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_entrypoint_module(alias.name):
                    violations.append(
                        f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: import {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and _is_entrypoint_module(node.module):
            violations.append(
                f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: from {node.module} import ..."
            )
        elif isinstance(node, ast.Call):
            function = _dotted_name(node.func)
            imported_name = _literal_string(node.args[0]) if node.args else None
            dynamic_import_names = import_functions | {
                f"{name}.import_module" for name in importlib_names
            } | {f"{name}.__import__" for name in importlib_names}
            if function in dynamic_import_names and _is_entrypoint_module(imported_name):
                violations.append(
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: {function}({imported_name!r})"
                )
            elif _entrypoint_namespace_expression(node, sys_names, sys_modules_names):
                violations.append(
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: entry-point namespace lookup"
                )
            elif function in {"getattr", "hasattr"} and node.args and (
                isinstance(node.args[0], ast.Name) and node.args[0].id in entrypoint_bindings
            or _entrypoint_namespace_expression(node.args[0], sys_names, sys_modules_names)
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: {function} on entry-point namespace"
                )
        elif isinstance(node, ast.Subscript):
            if _is_sys_modules(node.value, sys_names, sys_modules_names):
                imported_name = _literal_string(node.slice)
                if _is_entrypoint_module(imported_name):
                    violations.append(
                        f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: sys.modules[{imported_name!r}]"
                    )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in entrypoint_bindings
        ):
            violations.append(
                f"{path.relative_to(BACKEND_ROOT.parent)}:{node.lineno}: entry-point attribute access"
            )
    return violations


def _top_level_implementations(tree: ast.Module) -> dict[str, int]:
    implementations: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            implementations[node.name] = node.lineno
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name):
                    implementations[target.id] = node.lineno
    return implementations


class ServerArchitectureTests(unittest.TestCase):
    def test_extraction_inventory_has_no_unassigned_p0_symbols(self) -> None:
        inventory = (REPOSITORY_ROOT / "docs" / "server-extraction-inventory.md").read_text(encoding="utf-8")
        self.assertIn("| P0 (Zuordnung offen) | 0 | 0 | 0 |", inventory)
        self.assertNotIn("| P0 (Zuordnung offen) | offen |", inventory)

    def test_backend_does_not_import_or_reach_server_namespace(self) -> None:
        self.assertTrue(BACKEND_ROOT.is_dir(), "Backend source must be available")
        violations: list[str] = []
        for path in _python_files(BACKEND_ROOT):
            violations.extend(_server_import_violations(path, _parse(path)))
        self.assertEqual(
            [],
            violations,
            "Backend modules must not import or dynamically access server.py:\n"
            + "\n".join(violations),
        )

    def test_server_does_not_redefine_extracted_public_symbols(self) -> None:
        implementations = _top_level_implementations(_parse(SERVER_PATH))
        violations = [
            f"{module}.{symbol} is redefined in server.py:{implementations[symbol]}"
            for module, symbols in MOVED_SYMBOLS
            for symbol in symbols
            if symbol in implementations
        ]
        violations.extend(
            f"legacy extracted symbol {symbol} is redefined in server.py:{implementations[symbol]}"
            for symbol in FORBIDDEN_SERVER_SYMBOLS
            if symbol in implementations
        )
        self.assertEqual(
            [],
            violations,
            "server.py must remain a composition root for extracted symbols:\n"
            + "\n".join(violations),
        )

    def test_request_handler_does_not_reintroduce_state_event_orchestration(self) -> None:
        request_handler = next(
            node
            for node in _parse(SERVER_PATH).body
            if isinstance(node, ast.ClassDef) and node.name == "RequestHandler"
        )
        methods = {
            node.name
            for node in request_handler.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue(
            {"send_state_event_batch", "handle_state_events"}.isdisjoint(methods)
        )

    def test_intervals_client_does_not_retain_snapshot_use_cases(self) -> None:
        intervals_client = next(
            node
            for node in _parse(SERVER_PATH).body
            if isinstance(node, ast.ClassDef) and node.name == "IntervalsClient"
        )
        methods = {
            node.name
            for node in intervals_client.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue(
            {"fetch_snapshot", "fetch_performance_snapshot"}.isdisjoint(methods)
        )

    def test_intervals_sync_service_uses_bounded_owner_dependencies(self) -> None:
        intervals_module = _parse(BACKEND_ROOT / "sync" / "intervals.py")
        service = next(
            node
            for node in intervals_module.body
            if isinstance(node, ast.ClassDef) and node.name == "IntervalsSyncService"
        )
        initializer = next(
            node
            for node in service.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        self.assertLessEqual(len(initializer.args.args) - 1, 7)


if __name__ == "__main__":
    unittest.main()
