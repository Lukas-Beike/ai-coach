"""Duplicate-delete contract and the merge of identified provider rows."""

from __future__ import annotations

from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.providers.source_labels import SourceView, provider_label

_DUPLICATE_DELETE_STALE_ERROR = (
    "Das Wahoo-/Garmin-Duplikat ist nicht mehr aktuell. "
    "Bitte die letzte Einheit erneut analysieren."
)

__all__ = [
    "deduplicate_api_records",
    "duplicate_delete_action",
    "validate_duplicate_delete",
]


def duplicate_delete_action(pair: dict[str, Any]) -> dict[str, Any]:
    """Describe the explicit confirmation required to delete the Garmin copy."""
    return {
        "action_type": "delete_duplicate_intervals_activity",
        "target_system": ProviderId.INTERVALS,
        "object_ids": {
            "keep_activity_id": pair["canonical_id"],
            "delete_activity_id": pair["duplicate_id"],
        },
        "diff": [
            {
                "type": "delete",
                "id": pair["duplicate_id"],
                "name": pair["duplicate_name"],
                "date": iso_date_prefix(str(pair.get("start_date_local") or "")),
                "source": provider_label(ProviderId.GARMIN, SourceView.DUPLICATE),
                "kept_source": provider_label(ProviderId.WAHOO, SourceView.DUPLICATE),
            }
        ],
        "payload": {
            "canonical_id": pair["canonical_id"],
            "duplicate_id": pair["duplicate_id"],
            "snapshot_synced_at": pair.get("snapshot_synced_at"),
        },
    }


def validate_duplicate_delete(payload: Any, current: Any) -> tuple[str, str]:
    """Fail closed unless the confirmation matches the current duplicate snapshot."""
    keys = ("canonical_id", "duplicate_id", "snapshot_synced_at")
    if (
        not isinstance(payload, dict)
        or not isinstance(current, dict)
        or not current
        or any(
            str(payload.get(key) or "") != str(current.get(key) or "") for key in keys
        )
    ):
        raise AppError(409, _DUPLICATE_DELETE_STALE_ERROR)
    return str(payload.get("canonical_id") or ""), str(
        payload.get("duplicate_id") or ""
    )


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def deduplicate_api_records(records: list[Any]) -> list[Any]:
    """Merge date-window responses without duplicating identified rows."""
    result: list[Any] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            result.append(record)
            continue
        identifier = _first_present(record, ("id", "activityId", "external_id"))
        if identifier in (None, ""):
            result.append(record)
            continue
        key = str(identifier)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result
