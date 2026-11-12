"""Visible receipts for the local records a Coach turn changed."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.coach.outcomes import coach_effect_label
from backend.coach.tool_specs import TOOL_DOMAIN
from backend.planning.plan_checks import BLOCKING_CODES, FINDING_CODES

# Write tools whose success leaves athlete records unchanged: previews and
# drafts take effect only through a later, separately approved step.
_NOT_A_CHANGE = frozenset({"preview_adaptive_replan", "stage_training_plan"})
_WAITING_STATUSES = frozenset({"approval_required", "cancelled"})
# As in ``outcomes.coach_effect_label``: a card run reports "applied".
_APPLIED_UNDO = frozenset({"applied", "undone"})
# Tools whose every durable effect is a change-history record that undo restores.
# Others may also write untracked state (plan constraints, tombstones, sync
# flags), so their turns are listed without a turn undo.
_FULLY_TRACKED_TOOLS = frozenset(
    {
        "update_profile",
        "save_competition",
        "manage_training_templates",
        "save_activity_feedback",
        "delete_activity_feedback",
        "confirm_activity_session",
        "split_activity_session",
        "merge_activity_sessions",
        "save_nutrition_entry",
        "update_nutrition_entry",
        "delete_nutrition_entry",
        "log_nutrition_template",
        "save_nutrition_template",
        "delete_nutrition_template",
        "save_nutrition_product",
        "fill_nutrition_product_gaps",
        "save_checkin",
        "save_equipment",
        "assign_activity_equipment",
        "log_equipment_maintenance",
    }
)


def _is_change(tool: Any, result: Any) -> bool:
    if tool not in TOOL_DOMAIN or tool in _NOT_A_CHANGE or not isinstance(result, dict):
        return False
    if tool == "undo_training_change":
        # Only an applied undo restores a record; otherwise it proposes one. The
        # tool passes on the undo service's "undone" (#2134, E-501).
        return result.get("status") in _APPLIED_UNDO
    return result.get("ok") is True and result.get("status") not in _WAITING_STATUSES


def _note_dates(value: Any) -> list[str]:
    dates = []
    for day in value if isinstance(value, list) else []:
        try:
            dates.append(date.fromisoformat(day).isoformat())
        except TypeError, ValueError:
            continue
    return dates


def _plan_notes(result: dict[str, Any]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    raw_notes = result.get("plan_check_notes")
    for note in raw_notes if isinstance(raw_notes, list) else []:
        if not isinstance(note, dict) or note.get("code") not in FINDING_CODES:
            continue
        evidence = note.get("evidence")
        warning = note["code"] in BLOCKING_CODES or (
            isinstance(evidence, dict) and evidence.get("severity") == "warning"
        )
        safe = {
            "code": note["code"],
            "dates": _note_dates(note.get("dates")),
            "severity": "warning" if warning else "notice",
        }
        if safe not in notes:
            notes.append(safe)
    return notes


def change_summary(command_receipts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Summarize a turn's applied writes for the chat, or ``None`` without any.

    The turn is undoable only when every applied write is fully tracked by
    change history; otherwise undo would silently keep part of the turn.
    """
    labels: list[str] = []
    notes: list[dict[str, Any]] = []
    undoable = True
    for entry in command_receipts:
        tool = entry.get("tool")
        if not _is_change(tool, entry.get("result")):
            continue
        undoable = (
            undoable and tool in _FULLY_TRACKED_TOOLS and bool(entry.get("changes"))
        )
        label = coach_effect_label(entry)
        if label not in labels:
            labels.append(label)
        for note in _plan_notes(entry["result"]):
            if note not in notes:
                notes.append(note)
    if not labels:
        return None
    summary = {"labels": labels, "undoable": undoable, "undone_at": None}
    if notes:
        summary["plan_check_notes"] = notes
    return summary


def turn_changes(command_receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Undo references of a turn's tracked changes, in the order recorded."""
    return [
        change
        for entry in command_receipts
        if isinstance(entry, dict)
        and entry.get("tool") in _FULLY_TRACKED_TOOLS
        and isinstance(entry.get("changes"), list)
        for change in entry["changes"]
    ]
