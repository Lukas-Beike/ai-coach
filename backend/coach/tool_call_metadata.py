"""Pure projection of structured Coach tool-call metadata."""

from __future__ import annotations

import json
from typing import Any

from backend.coach.proposals import coach_action_hash
from backend.coach.service import (
    coach_repair_key,
    dialogue_effect_key,
    dialogue_plan_effect_key,
    dialogue_request_binding_key,
    dialogue_scope_repair_key,
)
from backend.errors import AppError


def structured_tool_call_metadata(
    item: dict[str, Any],
    tools: list[dict[str, Any]],
    command_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a tool call and derive the stable receipt/replay keys."""
    name = str(item.get("name") or "")
    call_id = str(item.get("call_id") or "")
    if not call_id or len(call_id) > 200:
        raise AppError(400, "Ein Werkzeugaufruf konnte nicht zugeordnet werden.", reason="invalid_tool_call")
    if len(command_receipts) >= 40 and not any(entry.get("call_id") == call_id for entry in command_receipts):
        raise AppError(400, "Der Coach-Auftrag enthält zu viele Schritte.", reason="command_limit")
    if name not in {tool["name"] for tool in tools}:
        raise AppError(403, "Dieses Werkzeug steht in diesem Auftrag nicht zur Verfügung.", reason="tool_scope_denied")
    arguments = json.loads(item.get("arguments") or "{}")
    if not isinstance(arguments, dict):
        raise ValueError("arguments_object")  # noqa: TRY004 - preserve the existing exception contract
    repair_key = coach_repair_key(name, arguments)
    scope_repair_key = dialogue_scope_repair_key(name, arguments)
    request_binding_key = dialogue_request_binding_key(arguments)
    plan_effect_key = dialogue_plan_effect_key(name, arguments)
    step_key = coach_action_hash({
        "name": name,
        "scope": sorted((arguments.get("_request") or {}).get("scope") or []),
        "period": (arguments.get("_request") or {}).get("period"),
        "repair_key": repair_key,
    })
    return {
        "name": name,
        "call_id": call_id,
        "arguments": arguments,
        "action": {"operation": name, "authorization_scope": []},
        "effect_key": dialogue_effect_key(name, arguments),
        "step_key": step_key,
        "repair_key": repair_key,
        "scope_repair_key": scope_repair_key,
        "request_binding_key": request_binding_key,
        "plan_effect_key": plan_effect_key,
    }
