"""Stable Coach tool metadata derived from the executable schemas."""

from __future__ import annotations

from typing import Any

OWNER_TOOLS = {
    "CoachReadToolService": {
        "read_coach_context",
        "read_profile",
        "read_training_state",
        "list_recent_activities",
        "get_activity_details",
        "list_workout_library",
        "list_planned_workouts",
        "list_change_history",
        "list_competitions",
        "list_training_plans",
        "get_sync_job",
        "read_nutrition",
        "inspect_activity_duplicates",
    },
    "CoachProfileUpdateService": {"update_profile"},
    "CoachAthleteRecordToolService": {
        "save_checkin",
        "save_activity_feedback",
        "delete_activity_feedback",
        "save_competition",
        "delete_competition",
        "save_nutrition_entry",
        "update_nutrition_entry",
        "delete_nutrition_entry",
    },
    "CoachPlanArtifactToolService": {"stage_training_plan", "commit_training_plan"},
    "CoachPlanningChangeService": {
        "replace_training_plan",
        "apply_training_patch",
        "apply_training_changes",
    },
    "TrainingTemplateToolService": {"manage_training_templates"},
    "CoachLibraryPlanToolService": {"apply_workout_library_plan"},
    "CoachSyncToolService": {
        "start_provider_refresh",
        "refresh_current_performance",
        "start_intervals_plan_sync",
        "sync_competitions",
        "resolve_training_sync_conflict",
        "sync_nutrition",
    },
    "CoachPlanningActionToolService": {
        "preview_adaptive_replan",
        "apply_adaptive_replan",
        "update_training_plan",
        "undo_training_change",
        "delete_duplicate_intervals_activity",
    },
    "CoachDialogueActionService": {"clarify_coach_request", "cancel_coach_request"},
}

REMOTE_WRITE_TOOLS = frozenset(
    {
        "start_intervals_plan_sync",
        "sync_competitions",
        "delete_duplicate_intervals_activity",
        "sync_nutrition",
    }
)
CONDITIONAL_REMOTE_WRITE_TOOLS = frozenset(
    {"resolve_training_sync_conflict", "apply_adaptive_replan"}
)
PROVIDER_READ_JOB_TOOLS = frozenset(
    {"start_provider_refresh", "refresh_current_performance"}
)
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
        effect, authorization, receipt = _tool_effect(name, read_only_tools)
        if receipt == "durable_effect" and name not in effect_labels:
            raise ValueError(f"Coach mutation has no receipt label: {name}")
        catalog[name] = {
            "name": name,
            "schema": schema,
            "owner": owners[name],
            "effect": effect,
            "authorization": authorization,
            "receipt": receipt,
            "surface": _tool_surface(name, canonical_schemas, dialogue_schemas),
        }
    return catalog


def _tool_effect(name: str, read_only_tools: set[str]) -> tuple[str, str, str]:
    if name in read_only_tools:
        return "read", "none", "read_only"
    if name in CONTROL_TOOLS:
        return "control", "pending_request", "turn_state"
    if name in PROVIDER_READ_JOB_TOOLS:
        return "provider_read_job", "request_scope", "durable_effect"
    if name in REMOTE_WRITE_TOOLS:
        return "remote_write", "request_scope+athlete_approval", "durable_effect"
    if name in CONDITIONAL_REMOTE_WRITE_TOOLS:
        return (
            "conditional_remote_write",
            "request_scope+athlete_approval_when_remote",
            "durable_effect",
        )
    return "local_write", "request_scope", "durable_effect"


def _tool_surface(
    name: str,
    canonical_schemas: dict[str, Any],
    dialogue_schemas: dict[str, Any],
) -> str:
    in_canonical = name in canonical_schemas
    in_dialogue = name in dialogue_schemas
    if in_canonical and in_dialogue:
        return "canonical_and_dialogue"
    return "canonical_only" if in_canonical else "dialogue_only"
