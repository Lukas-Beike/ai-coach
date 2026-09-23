"""Pure projections for calendar conflicts during local planning."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

_UTC_OFFSET_SUFFIX = "+00:00"


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _naive_calendar_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", _UTC_OFFSET_SUFFIX)
        )
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _calendar_duration_minutes(value: dict[str, Any], default_minutes: int) -> int:
    duration = value.get("duration_minutes")
    if duration in (None, "") and value.get("moving_time") not in (None, ""):
        duration = float(value["moving_time"]) / 60
    try:
        return (
            max(1, int(float(duration)))
            if duration not in (None, "")
            else default_minutes
        )
    except (TypeError, ValueError):
        return default_minutes


def _calendar_interval_end(
    value: dict[str, Any], start: datetime, default_minutes: int
) -> datetime:
    end = _naive_calendar_datetime(
        _first_present(value, ("end_date_local", "end_local", "end"))
    )
    if end is None:
        end = start + timedelta(
            minutes=_calendar_duration_minutes(value, default_minutes)
        )
    return max(end, start + timedelta(minutes=1))


def _calendar_interval(
    value: dict[str, Any], default_minutes: int = 60
) -> tuple[datetime, datetime, bool] | None:
    raw_start = _first_present(
        value, ("start_date_local", "start_local", "start", "date")
    )
    if raw_start in (None, ""):
        return None
    raw_start = str(raw_start).strip()
    if len(raw_start) == 10:
        try:
            start = datetime.combine(date.fromisoformat(raw_start), datetime.min.time())
        except ValueError:
            return None
        return start, start + timedelta(days=1), False
    start = _naive_calendar_datetime(raw_start)
    if start is None:
        return None
    end = _calendar_interval_end(value, start, default_minutes)
    return start, max(end, start + timedelta(minutes=1)), True


def _calendar_items_conflict(
    candidate: dict[str, Any], existing: dict[str, Any]
) -> tuple[bool, str]:
    candidate_date = str(
        _first_present(
            candidate, ("date", "event_date", "start_date_local", "start_local")
        )
        or ""
    )[:10]
    existing_date = str(
        _first_present(
            existing, ("date", "event_date", "start_date_local", "start_local")
        )
        or ""
    )[:10]
    candidate_interval = _calendar_interval(candidate)
    existing_interval = _calendar_interval(existing)
    if (
        candidate_interval
        and existing_interval
        and candidate_interval[2]
        and existing_interval[2]
    ):
        return (
            candidate_interval[0] < existing_interval[1]
            and existing_interval[0] < candidate_interval[1],
            "time_window",
        )
    return bool(candidate_date and candidate_date == existing_date), "date"


def _calendar_conflict_record(
    item: dict[str, Any], source: str, match: str
) -> dict[str, Any]:
    interval = _calendar_interval(item)
    return {
        "id": item.get("id") or item.get("local_id"),
        "name": item.get("name") or "Einheit",
        "date": str(
            _first_present(
                item, ("date", "event_date", "start_date_local", "start_local")
            )
            or ""
        )[:10],
        "source": source,
        "match": match,
        "start_local": interval[0].isoformat(timespec="minutes")
        if interval and interval[2]
        else None,
        "end_local": interval[1].isoformat(timespec="minutes")
        if interval and interval[2]
        else None,
    }


def calendar_conflicts_for_items(
    candidate: dict[str, Any], items: list[dict[str, Any]], source: str
) -> list[dict[str, Any]]:
    conflicts = []
    for item in items:
        matches, match = _calendar_items_conflict(candidate, item)
        if matches:
            conflicts.append(_calendar_conflict_record(item, source, match))
    return conflicts
