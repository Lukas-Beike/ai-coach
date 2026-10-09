"""Validation and visible-diff rules for Coach proposals."""

from __future__ import annotations

from typing import Any

from backend.coach.proposal_models import (
    COACH_ACTION_TYPES,
    LOCAL_COACH_WRITE_TOOLS,
    REMOTE_COACH_WRITE_TOOLS,
)
from backend.errors import AppError


def validated_coach_action_preview_input(
    values: Any,
) -> tuple[
    str, str, dict[str, Any] | list[Any], dict[str, Any] | list[Any], dict[str, Any]
]:
    """Validate proposal input shape, supported action, target, and visible diff."""
    if not isinstance(values, dict):
        raise AppError(400, "Die Aktionsvorschau muss ein Objekt sein.")
    action_type = str(values.get("action_type") or "").strip()
    if action_type not in COACH_ACTION_TYPES:
        raise AppError(400, "Unbekannter Coach-Aktionstyp.")
    target_system = str(values.get("target_system") or "").strip()
    if target_system not in {"local", "intervals", "local+intervals"}:
        raise AppError(400, "Die Aktionsvorschau benötigt ein gültiges Zielsystem.")
    object_ids = values.get("object_ids")
    diff = values.get("diff")
    payload = values.get("payload")
    if (
        not isinstance(object_ids, (dict, list))
        or not isinstance(diff, (dict, list))
        or not isinstance(payload, dict)
    ):
        raise AppError(
            400, "Die Aktionsvorschau benötigt Objekt-IDs, Diff und Payload."
        )
    expected_target = (
        "intervals"
        if action_type
        in {
            "delete_duplicate_intervals_activity",
            "remote_coach_write",
        }
        else "local"
    )
    if action_type == "local_coach_write":
        if target_system != "local" or not diff:
            raise AppError(
                400, "Die lokale Coach-Aktion benötigt einen sichtbaren Diff."
            )
        _validate_local_coach_write(payload)
    elif target_system != expected_target or not diff:
        raise AppError(
            400,
            "Die geschuetzte Aktion benoetigt das passende Ziel und einen sichtbaren Diff.",
        )
    if action_type == "remote_coach_write":
        _validate_remote_coach_write(payload)
    return action_type, target_system, object_ids, diff, payload


def _validate_remote_coach_write(payload: dict[str, Any]) -> None:
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    intent = payload.get("intent")
    request = intent.get("request") if isinstance(intent, dict) else None
    scope = intent.get("authorization_scope") if isinstance(intent, dict) else None
    scope_ok = isinstance(scope, list) and "intervals_sync" in scope
    source_ids = (
        request.get("source_message_ids") if isinstance(request, dict) else None
    )
    source_ids_ok = (
        isinstance(source_ids, list)
        and 1 <= len(source_ids) <= 24
        and all(type(value) is int and value > 0 for value in source_ids)
        and len(source_ids) == len(set(source_ids))
    )
    if (
        tool not in REMOTE_COACH_WRITE_TOOLS
        or not isinstance(arguments, dict)
        or not isinstance(intent, dict)
        or intent.get("operation") != tool
        or intent.get("target_system") != "intervals"
        or not isinstance(request, dict)
        or request.get("remote_write") is not True
        or not source_ids_ok
        or not scope_ok
    ):
        raise AppError(
            400, "Die Coach-Aktion ist keine gültige Intervals.icu-Änderung."
        )


def _validate_local_coach_write(payload: dict[str, Any]) -> None:
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    intent = payload.get("intent")
    request = intent.get("request") if isinstance(intent, dict) else None
    scope = intent.get("authorization_scope") if isinstance(intent, dict) else None
    source_ids = (
        request.get("source_message_ids") if isinstance(request, dict) else None
    )
    values = arguments.get("payload") if isinstance(arguments, dict) else None
    product_write = tool == "save_nutrition_product"
    valid_payload = (
        isinstance(values, dict)
        and isinstance(values.get("name"), str)
        and (
            values.get("basis_unit") in {"g", "ml", "portion"}
            if product_write
            else isinstance(values.get("description"), str)
        )
    )
    source_ids_ok = (
        isinstance(source_ids, list)
        and 1 <= len(source_ids) <= 24
        and all(type(value) is int and value > 0 for value in source_ids)
        and len(source_ids) == len(set(source_ids))
    )
    if (
        tool not in LOCAL_COACH_WRITE_TOOLS
        or not isinstance(intent, dict)
        or intent.get("operation") != tool
        or intent.get("target_system") != "local"
        or not isinstance(request, dict)
        or not source_ids_ok
        or not isinstance(scope, list)
        or not ({"local_nutrition", "local_nutrition_product"} & set(scope))
        or (
            product_write
            and isinstance(values, dict)
            and values.get("id")
            and f"nutrition_product:{values.get('id')}" not in scope
        )
        or not valid_payload
    ):
        raise AppError(400, "Die lokale Coach-Aktion ist ungültig.")


REMOTE_WRITE_LABELS = {
    "start_intervals_plan_sync": "Trainingseinheiten mit Intervals.icu synchronisieren",
    "sync_competitions": "Bestätigte Wettkämpfe mit Intervals.icu synchronisieren",
    "delete_duplicate_intervals_activity": "Garmin-Duplikat mit Intervals.icu löschen",
    "sync_nutrition": "Ernährungsdaten mit Intervals.icu synchronisieren",
    "resolve_training_sync_conflict": "Fehlgeschlagenen Intervals.icu-Sync wiederholen",
    "apply_adaptive_replan": "Adaptive Änderung anwenden und Krankheitspause synchronisieren",
}


def remote_coach_write_diff(
    tool: str,
    arguments: dict[str, Any],
    intent: dict[str, Any],
    approval_manifest: Any = None,
    approval_details: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Project the remote effect into a compact, non-sensitive approval summary."""
    name = REMOTE_WRITE_LABELS[tool]
    if tool == "sync_nutrition":
        return _nutrition_approval_diff(name, approval_manifest)
    if tool == "start_intervals_plan_sync":
        return _plan_sync_write_diff(
            {"name": name}, arguments, intent, approval_details or []
        )
    if tool == "sync_competitions" and approval_details:
        return approval_details
    return _remote_write_summary(tool, name, arguments, approval_manifest)


def _remote_write_summary(
    tool: str, name: str, arguments: dict[str, Any], approval_manifest: Any
) -> list[dict[str, str]]:
    entry: dict[str, str] = {"name": name}
    if tool == "resolve_training_sync_conflict":
        entry["date"] = (
            "Synchronisationsauftrag " + str(arguments.get("job_id") or "")[:36]
        )
    elif tool == "delete_duplicate_intervals_activity":
        manifest = approval_manifest if isinstance(approval_manifest, dict) else {}
        entry.update(
            date=str(manifest.get("date") or "")[:10],
            keep=str(manifest.get("canonical_id") or "")[:80],
            delete=str(manifest.get("duplicate_id") or "")[:80],
        )
    elif tool == "apply_adaptive_replan":
        entry["date"] = (
            "Adaptive Vorschau " + str(arguments.get("adjustment_id") or "")[:36]
        )
    return [entry]


def _nutrition_approval_diff(name: str, approval_manifest: Any) -> list[dict[str, str]]:
    entries = approval_manifest if isinstance(approval_manifest, list) else []
    if entries:
        return _nutrition_write_diff(name, entries)
    return [{"name": name, "date": "Keine ausstehenden Tage"}]


def _nutrition_write_diff(
    name: str, manifest: list[dict[str, Any]]
) -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "date": str(item["date"]),
            "kcal": f"{item['total_kcal']} kcal",
            "entries": str(item["entry_count"]),
            **{
                field: f"{item[key]} g"
                for field, key in (
                    ("carbs", "total_carbs_g"),
                    ("protein", "total_protein_g"),
                    ("fat", "total_fat_g"),
                )
                if item.get(key) is not None
            },
        }
        for item in manifest
    ]


def _plan_sync_write_diff(
    entry: dict[str, str],
    arguments: dict[str, Any],
    intent: dict[str, Any],
    details: list[dict[str, str]],
) -> list[dict[str, str]]:
    scope = str((intent.get("request") or {}).get("sync_scope") or "selected")
    entries = arguments.get("entries") or []
    count = len(entries)
    entry["scope"] = scope
    entry["units"] = f"{count} konkret ausgewählte Einheit(en)"
    labels = {
        "selected": entry["units"],
        "all_pending": f"{count} derzeit ausstehende Einheit(en)",
    }
    entry["sport"] = labels.get(
        scope, f"{count} in diesem Auftrag erstellte Einheit(en)"
    )
    dates = sorted(
        {
            str(item["date"])
            for item in entries
            if isinstance(item, dict) and item.get("date")
        }
    )
    if dates:
        entry["date"] = dates[0]
        if len(dates) > 1:
            entry["date"] = f"{dates[0]} bis {dates[-1]}"
    return details or [entry]
