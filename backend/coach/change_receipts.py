"""Visible receipts for the local records a Coach turn changed."""

from __future__ import annotations

from typing import Any

from backend.coach.outcomes import coach_effect_label
from backend.coach.write_gate import TOOL_DOMAIN

# Write tools whose success leaves athlete records unchanged: previews and
# drafts take effect only through a later, separately approved step.
_NOT_A_CHANGE = frozenset(
    {"preview_adaptive_replan", "stage_training_plan", "undo_training_change"}
)
_WAITING_STATUSES = frozenset({"approval_required", "cancelled"})


def change_summary(command_receipts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summarize a turn's applied writes for the chat, or ``None`` without any.

    The turn is undoable only when every applied write recorded change history;
    otherwise undo would silently keep part of the turn.
    """
    labels: list[str] = []
    undoable = True
    for entry in command_receipts:
        tool = entry.get("tool")
        result = entry.get("result")
        if (
            tool not in TOOL_DOMAIN
            or tool in _NOT_A_CHANGE
            or not isinstance(result, dict)
            or result.get("ok") is not True
            or result.get("status") in _WAITING_STATUSES
        ):
            continue
        undoable = undoable and bool(entry.get("changes"))
        label = coach_effect_label(entry)
        if label not in labels:
            labels.append(label)
    if not labels:
        return None
    return {"labels": labels, "undoable": undoable, "undone_at": None}


def turn_changes(command_receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Undo references of a turn, in the order they were recorded."""
    return [
        change
        for entry in command_receipts
        if isinstance(entry, dict) and isinstance(entry.get("changes"), list)
        for change in entry["changes"]
    ]
