"""Pure canonical projection for local and remote planned workouts."""

from typing import Any

ISO_MIDNIGHT_SUFFIX = "T00:00:00"
LOCAL_INTERVALS_SCOPE = "local+intervals"


def _canonical_remote_indexes(
    remote_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    return (
        {
            str(item.get("id")): item
            for item in remote_rows
            if item.get("id") not in (None, "")
        },
        {
            str(item.get("external_id")): item
            for item in remote_rows
            if item.get("external_id")
        },
    )


def _canonical_linked_remote(
    entry: dict[str, Any],
    remote_by_id: dict[str, dict[str, Any]],
    remote_by_external: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    remote_id = str(entry.get("remote_event_id") or "").strip()
    linked = remote_by_id.get(remote_id) if remote_id else None
    if linked is None:
        remote_external_id = str(entry.get("remote_event_external_id") or "").strip()
        linked = (
            remote_by_external.get(remote_external_id) if remote_external_id else None
        )
    return linked


def _canonical_local_event_identity(
    entry: dict[str, Any],
    linked: dict[str, Any] | None,
) -> tuple[str, str, str, str, str, str]:
    local_id = str(entry.get("id") or entry.get("local_id") or "")
    event_date = str(entry.get("date") or "")[:10]
    local_status = str(entry.get("sync_status") or "local")
    remote_id = (
        str(linked.get("id") or entry.get("remote_event_id") or "")
        if linked
        else str(entry.get("remote_event_id") or "")
    )
    remote_external_id = (
        str(linked.get("external_id") or entry.get("remote_event_external_id") or "")
        if linked
        else str(entry.get("remote_event_external_id") or "")
    )
    sync_status = (
        local_status if local_status not in {"", "synced"} or not linked else "synced"
    )
    return (
        local_id,
        event_date,
        local_status,
        remote_id,
        remote_external_id,
        sync_status,
    )


def _canonical_local_event(
    entry: dict[str, Any], linked: dict[str, Any] | None
) -> dict[str, Any]:
    local_id, event_date, _local_status, remote_id, remote_external_id, sync_status = (
        _canonical_local_event_identity(entry, linked)
    )
    result_event = {
        **entry,
        "id": remote_id or local_id,
        "local_id": local_id or None,
        "local_library_id": local_id or None,
        "remote_id": remote_id or None,
        "remote_event_id": remote_id or None,
        "remote_library_id": str(entry.get("external_id") or "") or None,
        "external_id": remote_external_id or None,
        "category": "WORKOUT",
        "start_date_local": str(
            entry.get("start_date_local")
            or (event_date + ISO_MIDNIGHT_SUFFIX if event_date else "")
        )[:40]
        or None,
        "is_local": True,
        "is_remote": bool(linked),
        "sync_source": LOCAL_INTERVALS_SCOPE if linked else "local",
        # A stale provider snapshot must not hide a local dirty or conflict
        # state. The local store remains the source of truth.
        "sync_status": sync_status,
    }
    if linked and "compliance" in linked:
        result_event["compliance"] = linked["compliance"]
    return result_event


def _canonical_remote_event(event: dict[str, Any]) -> dict[str, Any]:
    event_id = str(event.get("id") or "")
    return {
        **event,
        "local_id": None,
        "local_library_id": None,
        "remote_id": event_id or None,
        "remote_event_id": event_id or None,
        "remote_library_id": None,
        "is_local": False,
        "is_remote": True,
        "sync_source": "intervals",
        "sync_status": "remote",
    }


def _canonical_planned_workout_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("start_date_local") or item.get("date") or "9999-12-31"),
        str(item.get("name") or "").casefold(),
        str(item.get("local_id") or item.get("remote_id") or ""),
    )


def _canonical_local_events(
    local_rows: list[dict[str, Any]],
    remote_by_id: dict[str, dict[str, Any]],
    remote_by_external: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    result: list[dict[str, Any]] = []
    joined_remote_ids: set[str] = set()
    for entry in local_rows:
        linked = _canonical_linked_remote(entry, remote_by_id, remote_by_external)
        if linked is not None:
            joined_remote_ids.add(str(linked.get("id")))
        result.append(_canonical_local_event(entry, linked))
    return result, joined_remote_ids


def _canonical_unjoined_remote_events(
    remote_rows: list[dict[str, Any]],
    joined_remote_ids: set[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in remote_rows:
        event_id = str(event.get("id") or "")
        if event_id and event_id in joined_remote_ids:
            continue
        result.append(_canonical_remote_event(event))
    return result


def canonical_planned_workouts(
    remote: list[Any] | None,
    local: list[Any] | None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Merge local planned library entries and remote calendar events.

    Local entries remain the editable source of truth. A remote event is
    joined only when a local entry recorded its remote event identity; an
    otherwise similar same-day event is intentionally shown separately.
    """
    remote_rows = [dict(item) for item in (remote or []) if isinstance(item, dict)]
    local_rows = [dict(item) for item in (local or []) if isinstance(item, dict)]
    remote_by_id, remote_by_external = _canonical_remote_indexes(remote_rows)
    result, joined_remote_ids = _canonical_local_events(
        local_rows, remote_by_id, remote_by_external
    )
    result.extend(_canonical_unjoined_remote_events(remote_rows, joined_remote_ids))
    return sorted(result, key=_canonical_planned_workout_sort_key)[
        : max(1, min(int(limit), 1000))
    ]
