"""Assemble Coach tool schemas, dialogue tools, and capabilities."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.capabilities import build_capability_catalog
from backend.coach.outcomes import COACH_OPERATION_LABELS
from backend.coach.tool_schemas import (
    _canonical_coach_tool,
    build_structured_tool_schemas,
)


def build_tool_contracts(
    *,
    default_profile: dict[str, Any],
    checkin_text_limits: dict[str, int],
    checkin_score_fields: tuple[str, ...],
    training_change_limit: int,
    library_bulk_max_entries: int,
    training_plan_statuses: Any,
    dialogue_tools: Callable[..., list[dict[str, Any]]],
):
    coach_structured_tools = build_structured_tool_schemas(
        default_profile=default_profile,
        checkin_text_limits=checkin_text_limits,
        checkin_score_fields=checkin_score_fields,
        training_change_limit=training_change_limit,
        library_bulk_max_entries=library_bulk_max_entries,
        training_plan_statuses=training_plan_statuses,
    )
    coach_canonical_tool_names = tuple(tool["name"] for tool in coach_structured_tools)
    structured_read_only_tools = {
        "read_coach_context",
        "read_profile",
        "read_training_state",
        "list_recent_activities",
        "get_activity_details",
        "get_training_report",
        "read_training_records",
        "list_workout_library",
        "list_planned_workouts",
        "list_change_history",
        "list_competitions",
        "list_training_plans",
        "get_sync_job",
        "read_nutrition",
        "lookup_food",
        "calculate_food_nutrition",
    }
    coach_dialogue_tools = dialogue_tools(
        [
            tool
            for tool in coach_structured_tools
            if tool["name"] != "apply_training_changes"
        ],
        structured_read_only_tools,
    )
    patch_properties = {
        "changes": next(
            tool
            for tool in coach_structured_tools
            if tool["name"] == "apply_training_changes"
        )["parameters"]["properties"]["changes"],
        "workouts": next(
            tool
            for tool in coach_structured_tools
            if tool["name"] == "stage_training_plan"
        )["parameters"]["properties"]["payload"]["properties"]["workouts"],
        "expected_revision": {"type": "integer"},
        "plan_name": {"type": "string"},
        "goal": {"type": "string"},
    }
    patch_properties["changes"] = {**patch_properties["changes"], "minItems": 0}
    patch_properties["workouts"] = {**patch_properties["workouts"], "minItems": 0}
    coach_dialogue_tools.extend(
        dialogue_tools(
            [
                _canonical_coach_tool(
                    "apply_training_patch",
                    "Apply related moves, edits, deletions and additions in one atomic local change. Read revision and per-unit hashes first. Existing objects keep their IDs. No remote writes.",
                    patch_properties,
                )
            ],
            structured_read_only_tools,
        )
    )
    coach_dialogue_tools.extend(
        [
            _canonical_coach_tool(
                "clarify_coach_request",
                "Keep the current request and its constraints for a concrete clarification. Source IDs refer to user messages; summary includes all unresolved requirements.",
                {
                    "source_message_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "maxItems": 24,
                    },
                    "summary": {"type": "string"},
                    "question": {"type": "string"},
                },
                strict=True,
            ),
            _canonical_coach_tool(
                "cancel_coach_request",
                "Close the pending request when the athlete cancels it; completed effects remain recorded.",
            ),
            _canonical_coach_tool(
                "inspect_activity_duplicates",
                "Inspect the latest cycling activity for duplicate Wahoo/Garmin recordings. Prefer Wahoo for analysis. A returned removal preview still requires the athlete's explicit confirmation; this tool never deletes remotely.",
            ),
        ]
    )
    structured_read_only_tools.add("inspect_activity_duplicates")
    capabilities = build_capability_catalog(
        coach_structured_tools,
        coach_dialogue_tools,
        structured_read_only_tools,
        COACH_OPERATION_LABELS,
    )
    return (
        coach_canonical_tool_names,
        coach_structured_tools,
        structured_read_only_tools,
        coach_dialogue_tools,
        capabilities,
    )
