"""Pure Garmin observation-date and sleep-freshness helpers.

The Garmin snapshot synchronizer owns persistence and freshness state.  This
module only reads the supplied snapshot and never reaches into that state.
"""

from datetime import date, datetime, timezone
from typing import Any

_OBSERVATION_DATE_FIELDS = (
    "calendarDate",
    "summaryDate",
    "date",
    "measurementDate",
    "timestampGMT",
    "timestamp",
    "startTimeLocal",
    "startTimeGMT",
)


def _garmin_record_date(value: Any) -> str | None:
    """Return a validated ISO date from a Garmin date or timestamp value."""
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= 100_000_000_000:
            return None
        try:
            return (
                datetime.fromtimestamp(float(value) / 1000, timezone.utc)
                .date()
                .isoformat()
            )
        except (OverflowError, OSError, ValueError):
            return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return date.fromisoformat(text[:10]).isoformat()
    except (AttributeError, TypeError, ValueError):
        return None


def garmin_record_observation_date(record: dict[str, Any]) -> str | None:
    """Return the first valid observation date represented by one record."""
    if not isinstance(record, dict):
        return None
    for field in _OBSERVATION_DATE_FIELDS:
        value = record.get(field)
        if value not in (None, ""):
            return _garmin_record_date(value)
    return None


def _garmin_nested_records(record: dict[str, Any]) -> list[Any]:
    return [item for item in record.values() if isinstance(item, (dict, list))]


def garmin_source_observed_at(value: Any) -> str | None:
    """Return the newest valid observation date in nested Garmin data."""
    dates: list[str] = []
    pending = [value]
    visited: set[int] = set()
    while pending:
        record = pending.pop()
        if isinstance(record, dict):
            marker = id(record)
            if marker in visited:
                continue
            visited.add(marker)
            observed_at = garmin_record_observation_date(record)
            if observed_at:
                dates.append(observed_at)
            pending.extend(_garmin_nested_records(record))
        elif isinstance(record, list):
            marker = id(record)
            if marker in visited:
                continue
            visited.add(marker)
            pending.extend(record)
    return max(dates, default=None)


def garmin_sleep_observation_date(snapshot: dict[str, Any]) -> str | None:
    """Return the authoritative sleep observation date from a snapshot."""
    if not isinstance(snapshot, dict):
        return None
    freshness = snapshot.get("source_freshness")
    if isinstance(freshness, dict):
        sleep_freshness = freshness.get("sleep")
        if isinstance(sleep_freshness, dict):
            observed_at = sleep_freshness.get("observed_at")
            if observed_at not in (None, ""):
                # Preserve the source-owned value exactly; malformed values
                # must remain authoritative and must not fall back to raw data.
                return str(observed_at)[:10]
    return garmin_source_observed_at(snapshot.get("sleep"))


def garmin_sleep_ready_for_checkin(
    checkin_date: date, snapshot: dict[str, Any]
) -> bool:
    """Allow a check-in only for current-day sleep with usable freshness."""
    if not isinstance(checkin_date, date) or isinstance(checkin_date, datetime):
        return False
    if not isinstance(snapshot, dict):
        return False
    if garmin_sleep_observation_date(snapshot) != checkin_date.isoformat():
        return False
    freshness = snapshot.get("source_freshness")
    if not isinstance(freshness, dict) or not isinstance(freshness.get("sleep"), dict):
        return True
    return freshness["sleep"].get("freshness") in {"current", "partial"}
