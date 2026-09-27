"""Stable Coach tool metadata derived from the executable schemas."""

from __future__ import annotations

from typing import Any


OWNER_TOOLS = {
    "CoachReadToolService": {
        "read_profile", "read_training_state", "list_recent_activities", "get_activity_details",
        "list_workout_library", "list_planned_workouts", "list_change_history", "list_competitions",
        "list_training_plans", "get_sync_job", "read_nutrition", "inspect_activity_duplicates",
    },
    "CoachProfileUpdateService": {"update_profile"},
    "CoachAthleteRecordToolService": {
        "save_checkin", "save_activity_feedback", "delete_activity_feedback", "save_competition",
        "delete_competition", "save_nutrition_entry", "update_nutrition_entry", "delete_nutrition_entry",
    },
    "CoachPlanArtifactToolService": {"stage_training_plan", "commit_training_plan"},
    "CoachPlanningChangeService": {"replace_training_plan", "apply_training_patch", "apply_training_changes"},
    "TrainingTemplateToolService": {"manage_training_templates"},
    "CoachLibraryPlanToolService": {"apply_workout_library_plan"},
    "CoachSyncToolService": {
        "start_provider_refresh", "refresh_current_performance", "start_intervals_plan_sync",
        "sync_competitions", "resolve_training_sync_conflict", "sync_nutrition",
    },
    "CoachPlanningActionToolService": {
        "preview_adaptive_replan", "apply_adaptive_replan", "update_training_plan",
        "undo_training_change", "delete_duplicate_intervals_activity",
    },
    "CoachDialogueActionService": {"clarify_coach_request", "cancel_coach_request"},
}

REMOTE_WRITE_TOOLS = frozenset({
    "start_intervals_plan_sync", "sync_competitions", "delete_duplicate_intervals_activity", "sync_nutrition",
})
CONDITIONAL_REMOTE_WRITE_TOOLS = frozenset({"resolve_training_sync_conflict", "apply_adaptive_replan"})
PROVIDER_READ_JOB_TOOLS = frozenset({"start_provider_refresh", "refresh_current_performance"})
CONTROL_TOOLS = frozenset({"clarify_coach_request", "cancel_coach_request"})


def build_capability_catalog(
    structured_tools: list[dict[str, Any]],
    dialogue_tools: list[dict[str, Any]],
    read_only_tools: set[str],
    effect_labels: dict[str, str],
) -> dict[str, dict[str, Any]]:
    owners = {name: owner for owner, names in OWNER_TOOLS.items() for name in names}
    canonical_schemas = {tool["name"]: tool for tool in structured_tools}
    dialogue_schemas = {tool["name"]: tool for tool in dialogue_tools}
    schemas = {**canonical_schemas, **dialogue_schemas}
    catalog = {}
    for name, schema in schemas.items():
        if name not in owners:
            raise ValueError(f"Coach tool has no capability owner: {name}")
        if name in read_only_tools:
            effect, authorization, receipt = "read", "none", "read_only"
        elif name in CONTROL_TOOLS:
            effect, authorization, receipt = "control", "pending_request", "turn_state"
        elif name in PROVIDER_READ_JOB_TOOLS:
            effect, authorization, receipt = "provider_read_job", "request_scope", "durable_effect"
        elif name in REMOTE_WRITE_TOOLS:
            effect, authorization, receipt = "remote_write", "request_scope+athlete_approval", "durable_effect"
        elif name in CONDITIONAL_REMOTE_WRITE_TOOLS:
            effect, authorization, receipt = "conditional_remote_write", "request_scope+athlete_approval_when_remote", "durable_effect"
        else:
            effect, authorization, receipt = "local_write", "request_scope", "durable_effect"
        if receipt == "durable_effect" and name not in effect_labels:
            raise ValueError(f"Coach mutation has no receipt label: {name}")
        catalog[name] = {
            "name": name,
            "schema": schema,
            "owner": owners[name],
            "effect": effect,
            "authorization": authorization,
            "receipt": receipt,
            "surface": (
                "canonical_and_dialogue" if name in canonical_schemas and name in dialogue_schemas
                else "canonical_only" if name in canonical_schemas
                else "dialogue_only"
            ),
        }
    return catalog
