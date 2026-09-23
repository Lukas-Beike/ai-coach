"""Pure local calendar read-model projection."""

from typing import Any

ISO_MIDNIGHT_SUFFIX = "T00:00:00"
LOCAL_INTERVALS_SCOPE = "local+intervals"


def _local_calendar_competition(competition: dict[str, Any]) -> dict[str, Any]:
    event_date = str(competition.get("event_date") or "")[:10]
    linked = bool(competition.get("external_id"))
    return {
        **competition,
        "date": event_date,
        "start_date_local": competition.get("start_date_local")
        or f"{event_date}{ISO_MIDNIGHT_SUFFIX}",
        "type": competition.get("sport") or "Competition",
        "category": competition.get("category") or "RACE_B",
        "is_competition": True,
        "is_local": True,
        "is_remote": linked,
        "sync_source": LOCAL_INTERVALS_SCOPE if linked else "local",
        "sync_status": competition.get("sync_state") or "local",
    }


def _local_calendar_external_event(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict) or int(event.get("training_relevant") or 0) != 1:
        return None
    return {
        **event,
        "date": str(event.get("event_date") or "")[:10],
        "is_external_calendar": True,
        "is_local": True,
        "is_remote": False,
        "sync_source": "external-calendar",
        "sync_status": "read-only",
    }


def _local_calendar_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(
            item.get("start_date_local")
            or item.get("date")
            or item.get("event_date")
            or "9999-12-31"
        ),
        str(item.get("name") or "").casefold(),
    )


def local_calendar_events(
    planned: list[Any],
    competitions: list[Any],
    external_events: list[Any],
) -> list[dict[str, Any]]:
    """Build the local calendar read model without performing I/O."""
    result = [dict(item) for item in planned if isinstance(item, dict)]
    result.extend(
        _local_calendar_competition(item)
        for item in competitions
        if isinstance(item, dict)
    )
    for event in external_events:
        projected = _local_calendar_external_event(event)
        if projected:
            result.append(projected)
    return sorted(result, key=_local_calendar_sort_key)
