"""Reusable Coach turn primitives shared by HTTP and background execution."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from backend.coach.proposals import coach_action_hash


def dialogue_scope_repair_key(name: str, arguments: dict[str, Any]) -> str:
    """Match the same requested effect when only its object scope is repaired."""
    request = arguments.get("_request") or {}
    binding = {
        key: request.get(key)
        for key in ("target", "period", "constraints", "remote_write", "sync_scope")
    }
    payload = {
        key: value for key, value in arguments.items()
        if key not in {"_request", "expected_revision"}
    }
    if isinstance(payload.get("changes"), list):
        payload["changes"] = [
            {key: value for key, value in change.items() if key != "expected_payload_hash"}
            if isinstance(change, dict) else change
            for change in payload["changes"]
        ]
    return coach_action_hash({"tool": name, "arguments": payload, "binding": binding})


def dialogue_request_binding_key(arguments: dict[str, Any]) -> str | None:
    """Identify one request without trusting its message provenance or prose."""
    request = arguments.get("_request")
    if not isinstance(request, dict):
        return None
    scope, constraints = request.get("scope"), request.get("constraints")
    if not isinstance(scope, list) or not all(isinstance(value, str) for value in scope):
        return None
    if not isinstance(constraints, list) or not all(isinstance(value, str) for value in constraints):
        return None
    binding = {
        "target": request.get("target"),
        "scope": sorted(scope),
        "period": request.get("period"),
        "constraints": sorted(constraints),
        "remote_write": request.get("remote_write"),
        "sync_scope": request.get("sync_scope"),
    }
    return coach_action_hash(binding)


def dialogue_plan_effect_key(name: str, arguments: dict[str, Any]) -> str | None:
    """Match cross-tool repairs only when the planned workout payload is exact."""
    if name == "apply_training_patch":
        if arguments.get("changes"):
            # Existing-unit edits cannot be proven equivalent to a complete
            # replacement without retaining and comparing every prior object.
            return None
        workouts = arguments.get("workouts")
    elif name == "replace_training_plan":
        workouts = (arguments.get("payload") or {}).get("workouts")
    else:
        return None
    if not isinstance(workouts, list) or not workouts:
        return None
    signatures = []
    for workout in workouts:
        if not isinstance(workout, dict):
            return None
        signatures.append({
            key: workout.get(key)
            for key in (
                "date", "sport", "name", "description", "duration_minutes", "target", "rationale",
            )
        })
    return coach_action_hash({"workouts": signatures})


def coach_repair_key(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Identify the affected object fields needed to match a correction."""
    if name != "update_profile":
        return None
    changes = arguments.get("changes")
    if not isinstance(changes, list):
        return None
    fields = sorted({
        str(item.get("field") or "")
        for item in changes
        if isinstance(item, dict) and item.get("field")
    })
    return {"profile_fields": fields} if fields else None


def dialogue_effect_key(name: str, arguments: dict[str, Any]) -> str:
    request = arguments.get("_request") or {}
    if not isinstance(request, dict):
        raise ValueError("request_object")
    binding = {
        key: request.get(key)
        for key in ("target", "period", "constraints", "remote_write", "sync_scope")
    }
    binding["scope"] = sorted(request.get("scope") or [])
    return coach_action_hash({
        "tool": name,
        "arguments": {key: value for key, value in arguments.items() if key != "_request"},
        "binding": binding,
    })


def command_receipt(value: Any) -> dict[str, Any]:
    """Decode a persisted receipt without allowing malformed state to escape."""
    try:
        receipt = json.loads(value or "{}") if not isinstance(value, dict) else dict(value)
    except (TypeError, ValueError):
        receipt = {}
    return receipt if isinstance(receipt, dict) else {}


def mark_resolved_receipts(command_receipts: list[dict[str, Any]], failures: Iterable[dict[str, Any]]) -> None:
    """Mark failed tool calls resolved when a later retry superseded them."""
    failure_ids = {id(entry) for entry in failures}
    for entry in command_receipts:
        if not entry.get("result", {}).get("ok"):
            entry["resolved"] = id(entry) not in failure_ids


def effects_from_receipts(
    command_receipts: list[dict[str, Any]], internal_tools: set[str],
) -> list[dict[str, Any]]:
    """Return successful externally meaningful tool effects."""
    return [
        entry for entry in command_receipts
        if entry.get("result", {}).get("ok") and entry.get("tool") not in internal_tools
    ]


def outcome_status(
    *, question: str, incomplete_answer: bool, failures: list[dict[str, Any]],
    missing_answer: bool, effects: list[dict[str, Any]], cancelled: bool,
) -> str:
    """Choose the durable status for a completed Coach turn."""
    if question:
        return "completed"
    if incomplete_answer or ((failures or missing_answer) and effects):
        return "partial"
    if failures or missing_answer:
        return "failed"
    return "cancelled" if cancelled else "completed"
