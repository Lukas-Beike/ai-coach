"""Structured Coach intent contract.

Intent parsing is intentionally JSON-only.  This module never searches the
athlete's sentence for authorization words; the caller must treat malformed or
unsupported output as a non-mutating clarification.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


INTENT_VALUES = frozenset({"advice", "local_action", "remote_sync", "needs_clarification"})
TARGET_VALUES = frozenset({"none", "local", "intervals", "garmin", "calendar", "weather"})
OPERATION_VALUES = frozenset({
    "read_training_state",
    "stage_training_plan",
    "commit_training_plan",
    "apply_training_changes",
    "manage_training_templates",
    "start_provider_refresh",
    "start_intervals_plan_sync",
    "get_sync_job",
    "resolve_training_sync_conflict",
    "undo_training_change",
})

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "operation", "target_system", "artifact_id", "ambiguities", "authorization_scope", "follow_up_operations"],
    "properties": {
        "intent": {"type": "string", "enum": sorted(INTENT_VALUES)},
        "operation": {"type": ["string", "null"], "enum": [*sorted(OPERATION_VALUES), None]},
        "target_system": {"type": "string", "enum": sorted(TARGET_VALUES)},
        "artifact_id": {"type": ["string", "null"]},
        "ambiguities": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "authorization_scope": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "follow_up_operations": {"type": "array", "items": {"type": "string", "enum": sorted(OPERATION_VALUES)}, "maxItems": 4},
    },
}


def intent_request_payload(
    message: str,
    artifact_refs: list[dict[str, Any]],
    allowed_targets: list[str],
) -> dict[str, Any]:
    """Build the isolated low-reasoning intent request without provider data."""
    return {
        "model": "gpt-5.6-luna",
        "instructions": (
            "Classify exactly the user's current Coach request. Return only the JSON schema. "
            "Do not infer authorization from previous turns. Advice is non-mutating. "
            "If the user explicitly requests a same-turn follow-up such as saving a newly created plan, "
            "include the additional operation in follow_up_operations. Never add an operation that is not "
            "explicitly requested in the current message. Ambiguous actions must use needs_clarification "
            "and exactly one concrete question in ambiguities. "
            "Only use targets explicitly listed in allowed_targets. "
            "authorization_scope must contain exact operation or object tokens: "
            "local_plan, local_template, artifact:<id>, planned_unit:<id>, "
            "library_workout:<id>, sync_job:<id>, change:<id>, intervals_refresh, "
            "garmin_refresh, calendar_refresh, or weather_refresh."
        ),
        "input": json.dumps({
            "message": str(message)[:12000],
            "artifact_refs": artifact_refs[:20],
            "allowed_targets": allowed_targets[:8],
        }, ensure_ascii=False, separators=(",", ":")),
        "tools": [],
        "tool_choice": "none",
        "reasoning": {"effort": "low"},
        "text": {"format": {"type": "json_schema", "name": "coach_intent", "strict": True, "schema": INTENT_SCHEMA}},
        "max_output_tokens": 800,
    }


def _response_text(response: Any) -> str:
    if isinstance(response, Mapping):
        direct = response.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        for item in response.get("output", []) if isinstance(response.get("output"), list) else []:
            if not isinstance(item, Mapping):
                continue
            for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
                if isinstance(content, Mapping) and isinstance(content.get("text"), str):
                    return content["text"].strip()
    return ""


def parse_intent_response(response: Any) -> dict[str, Any]:
    """Validate one model response; callers must retry once on ValueError."""
    raw = _response_text(response)
    if not raw:
        raise ValueError("intent response has no JSON text")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("intent response is not JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("intent response is not an object")
    intent = value.get("intent")
    operation = value.get("operation")
    target = value.get("target_system")
    if intent not in INTENT_VALUES or target not in TARGET_VALUES:
        raise ValueError("intent response contains an unsupported enum")
    if operation is not None and operation not in OPERATION_VALUES:
        raise ValueError("intent response contains an unsupported operation")
    ambiguities = value.get("ambiguities")
    scope = value.get("authorization_scope")
    follow_up_operations = value.get("follow_up_operations") or []
    if not isinstance(ambiguities, list) or not all(isinstance(item, str) for item in ambiguities):
        raise ValueError("intent ambiguities must be a string list")
    if not isinstance(scope, list) or not all(isinstance(item, str) for item in scope):
        raise ValueError("intent authorization scope must be a string list")
    if not isinstance(follow_up_operations, list) or not all(item in OPERATION_VALUES for item in follow_up_operations):
        raise ValueError("intent follow-up operations must be a supported operation list")
    if intent == "needs_clarification" and len(ambiguities) != 1:
        raise ValueError("clarification must contain exactly one question")
    if intent in {"advice", "needs_clarification"} and operation is not None:
        raise ValueError("non-action intent cannot contain an operation")
    if follow_up_operations and intent not in {"local_action", "remote_sync"}:
        raise ValueError("only an action intent can contain follow-up operations")
    if follow_up_operations and operation is None:
        raise ValueError("follow-up operations require a primary operation")
    if intent in {"advice", "needs_clarification"} and target != "none":
        raise ValueError("non-action intent cannot contain a target")
    if intent == "local_action" and target != "local":
        raise ValueError("local action requires local target")
    if intent == "remote_sync" and target not in {"intervals", "garmin", "calendar", "weather"}:
        raise ValueError("remote sync requires provider target")
    return {
        "intent": intent,
        "operation": operation,
        "target_system": target,
        "artifact_id": str(value.get("artifact_id") or "")[:120] or None,
        "ambiguities": [item[:300] for item in ambiguities[:8]],
        "authorization_scope": [item[:120] for item in scope[:8]],
        "follow_up_operations": [item for item in follow_up_operations[:4]],
    }
