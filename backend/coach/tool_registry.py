"""Assemble Coach tool schemas, dialogue tools, and capabilities."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.capabilities import build_capability_catalog
from backend.coach.tool_schemas import (
    ACCEPT_PLAN_FINDINGS,
    _canonical_coach_tool,
    build_structured_tool_schemas,
)
from backend.coach.tool_specs import READ_ONLY_TOOLS


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
    structured_read_only_tools = set(READ_ONLY_TOOLS)
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
        "accept_plan_findings": ACCEPT_PLAN_FINDINGS,
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
        ]
    )
    capabilities = build_capability_catalog(
        coach_structured_tools, coach_dialogue_tools
    )
    return (
        coach_canonical_tool_names,
        coach_structured_tools,
        structured_read_only_tools,
        coach_dialogue_tools,
        capabilities,
    )
