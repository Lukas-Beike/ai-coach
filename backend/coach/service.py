"""Reusable Coach turn primitives shared by HTTP and background execution."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


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
