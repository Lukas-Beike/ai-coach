"""Pure canonical projection for local planned workouts."""

from typing import Any

from backend.athlete.local_date import LocalDate

ISO_MIDNIGHT_SUFFIX = "T00:00:00"


def _event_date(entry: dict[str, Any]) -> str:
    try:
        return LocalDate.parse(entry.get("date")).isoformat()
    except TypeError, ValueError:
        return ""


def _starts_at_local(entry: dict[str, Any], event_date: str) -> str | None:
    fallback = event_date + ISO_MIDNIGHT_SUFFIX if event_date else ""
    return str(entry.get("starts_at_local") or fallback)[:40] or None


def _canonical_local_event(entry: dict[str, Any]) -> dict[str, Any]:
    local_id = str(entry.get("id") or entry.get("local_id") or "")
    remote_id = str(entry.get("remote_event_id") or "")
    remote_external_id = str(entry.get("remote_event_external_id") or "")
    return {
        **entry,
        "id": remote_id or local_id,
        "local_id": local_id or None,
        "local_library_id": local_id or None,
        "remote_id": remote_id or None,
        "remote_event_id": remote_id or None,
        "remote_library_id": str(entry.get("external_id") or "") or None,
        "external_id": remote_external_id or None,
        "category": "WORKOUT",
        "starts_at_local": _starts_at_local(entry, _event_date(entry)),
        "is_local": True,
        "is_remote": False,
        "sync_source": "local",
        # The local store is the source of truth for the dirty or conflict state.
        "sync_status": str(entry.get("sync_status") or "local"),
    }


def _canonical_planned_workout_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("starts_at_local") or item.get("date") or "9999-12-31"),
        str(item.get("name") or "").casefold(),
        str(item.get("local_id") or item.get("remote_id") or ""),
    )


def canonical_planned_workouts(
    local: list[Any] | None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Project the local planned library entries; they are the editable source."""
    local_rows = [dict(item) for item in (local or []) if isinstance(item, dict)]
    result = [_canonical_local_event(entry) for entry in local_rows]
    return sorted(result, key=_canonical_planned_workout_sort_key)[
        : max(1, min(int(limit), 1000))
    ]
