"""Validation of Coach request provenance, scope and remote-write intent."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import date
from typing import Any

from backend.errors import AppError


def coach_session_key(session_csrf_hash: str) -> str:
    """Bind persisted Coach work to a session without storing its CSRF hash."""
    return hashlib.sha256(str(session_csrf_hash or "").encode("utf-8")).hexdigest()


REQUEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "source_message_ids", "target", "scope", "period", "constraints", "remote_write", "sync_scope"],
    "properties": {
        "summary": {"type": "string", "maxLength": 2000},
        "source_message_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 24},
        "target": {"type": "string", "enum": ["local", "intervals", "garmin", "calendar", "weather"]},
        "scope": {"type": "array", "items": {"type": "string"}, "maxItems": 400},
        "period": {"type": ["object", "null"], "additionalProperties": False,
                   "properties": {"start": {"type": "string"}, "end": {"type": "string"}}, "required": ["start", "end"]},
        "constraints": {"type": "array", "items": {"type": "string"}, "maxItems": 24},
        "remote_write": {"type": "boolean"},
        "sync_scope": {"type": ["string", "null"], "enum": ["created", "selected", "all_pending", None]},
    },
}


def _validate_request_provenance(value: dict[str, Any], user_ids: set[int], current_user_id: int) -> None:
    ids = value["source_message_ids"]
    valid = isinstance(ids, list) and 1 <= len(ids) <= 24
    valid = valid and all(type(item) is int and item in user_ids for item in ids)
    if not valid or current_user_id not in ids:
        raise ValueError("request_provenance")


def _validate_request_text(value: dict[str, Any]) -> None:
    if value["target"] not in REQUEST_SCHEMA["properties"]["target"]["enum"]:
        raise ValueError("request_target")
    summary = value["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise ValueError("request_summary")
    for key, count, length in (("scope", 400, 160), ("constraints", 24, 1000)):
        items = value[key]
        valid = isinstance(items, list) and len(items) <= count
        valid = valid and all(isinstance(item, str) and item.strip() and len(item) <= length for item in items)
        if not valid:
            raise ValueError("request_" + key)


def _validate_request_sync(value: dict[str, Any]) -> None:
    if type(value["remote_write"]) is not bool or value["sync_scope"] not in {None, "created", "selected", "all_pending"}:
        raise ValueError("request_sync")


def _validate_request_period(period: Any) -> None:
    if period is None:
        return
    if not isinstance(period, dict) or set(period) != {"start", "end"}:
        raise ValueError("request_period")
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    if start.isoformat() != period["start"] or end.isoformat() != period["end"] or not 0 <= (end - start).days <= 730:
        raise ValueError("request_period")


def validate_request(value: Any, user_ids: set[int], current_user_id: int) -> dict[str, Any]:
    """Validate provenance and bounds, never the user's choice of words."""
    if not isinstance(value, dict) or set(value) != set(REQUEST_SCHEMA["required"]):
        raise ValueError("request_fields")
    _validate_request_provenance(value, user_ids, current_user_id)
    _validate_request_text(value)
    _validate_request_sync(value)
    _validate_request_period(value["period"])
    return deepcopy(value)


def dialogue_tools(tools: list[dict[str, Any]], read_tools: set[str]) -> list[dict[str, Any]]:
    result = deepcopy(tools)
    for tool in result:
        if tool["name"] not in read_tools:
            tool["parameters"]["properties"]["_request"] = deepcopy(REQUEST_SCHEMA)
            tool["parameters"].setdefault("required", []).append("_request")
    return result


def scope_values(intent: dict[str, Any]) -> set[str]:
    scope = intent.get("authorization_scope")
    if not isinstance(scope, list):
        return set()
    return {str(value).strip()[:120] for value in scope if isinstance(value, str) and value.strip()}


def coach_execution_scope(action: dict[str, Any] | None, *, background_horizon_days: int) -> dict[str, Any]:
    """Describe the local planning workload implied by a structured action."""
    period = (action or {}).get("period")
    days = (date.fromisoformat(period["end"]) - date.fromisoformat(period["start"])).days + 1 if period else None
    return {"planning": bool(period), "horizon_days": days, "planned_units": None,
            "bulk_change": bool(days and days > background_horizon_days), "background": True}


def require_coach_scope(intent: dict[str, Any], *tokens: str) -> None:
    if not require_scope(intent, *tokens):
        raise AppError(403, "Die strukturierte Coach-Autorisierung umfasst dieses Objekt nicht.", reason="intent_scope_denied")


def authorized_operations(intent: dict[str, Any]) -> set[str]:
    operations = {str(intent.get("operation") or "").strip()}
    follow_ups = intent.get("follow_up_operations")
    if isinstance(follow_ups, list):
        operations.update(str(value).strip() for value in follow_ups if str(value).strip())
    return operations


def require_scope(intent: dict[str, Any], *tokens: str) -> bool:
    return any(token in scope_values(intent) for token in tokens)


def require_operation(intent: dict[str, Any], operation: str) -> bool:
    return operation in authorized_operations(intent)


def structured_action_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a structured local-action payload or the shared client error."""
    payload = arguments.get("payload")
    if isinstance(payload, dict):
        return payload
    raise AppError(400, "Diese Aktion benoetigt payload.", reason="invalid_action")
