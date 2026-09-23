"""Stateless Garmin recovery record search and aggregation."""

import math
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

UTC_OFFSET_SUFFIX = "+00:00"


def _garmin_key(value: Any) -> str:
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _garmin_numeric(value: Any) -> float | int | None:
    if isinstance(value, dict):
        value = _first_present(
            value,
            (
                "value",
                "val",
                "amount",
                "seconds",
                "time",
                "raceTime",
                "racePredictionTime",
            ),
        )
    return _as_number(value)


def _planning_context_date(value: Any) -> str:
    raw = str(value or "").replace("Z", UTC_OFFSET_SUFFIX)[:10]
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return ""


def dated_garmin_recovery_records(value: Any) -> list[tuple[str, dict[str, Any]]]:
    """Find dated recovery records without returning Garmin's raw payload."""
    records: list[tuple[str, dict[str, Any]]] = []
    pending: list[Any] = [value]
    visited = 0
    while pending and visited < 2000:
        current = pending.pop()
        visited += 1
        if isinstance(current, dict):
            record_date = _planning_context_date(
                _first_present(
                    current, ("calendarDate", "summaryDate", "date", "timestamp", "id")
                )
            )
            if record_date:
                records.append((record_date, current))
            pending.extend(
                item for item in current.values() if isinstance(item, (dict, list))
            )
        elif isinstance(current, list):
            pending.extend(
                item for item in current[:500] if isinstance(item, (dict, list))
            )
    return records


def _collect_garmin_numeric_values(
    item: Any, keys: set[str], values: list[float | int]
) -> None:
    if isinstance(item, dict):
        for key, child in item.items():
            if _garmin_key(key) in keys:
                number = _garmin_numeric(child)
                if number is not None:
                    values.append(number)
            _collect_garmin_numeric_values(child, keys, values)
    elif isinstance(item, list):
        for child in item[:500]:
            _collect_garmin_numeric_values(child, keys, values)


def _garmin_last_numeric(value: Any, keys: set[str]) -> float | int | None:
    """Find the last numeric value for exact Garmin field names."""
    values: list[float | int] = []
    _collect_garmin_numeric_values(value, keys, values)
    return values[-1] if values else None


def garmin_recovery_metric(
    snapshot: dict[str, Any],
    section: str,
    keys: tuple[str, ...],
    transform: Callable[[Any], float | int | None] | None = None,
) -> tuple[float | int | None, str | None]:
    normalized_keys = {_garmin_key(key) for key in keys}
    records = sorted(
        dated_garmin_recovery_records(snapshot.get(section)),
        key=lambda item: item[0],
        reverse=True,
    )
    for record_date, record in records:
        value = _garmin_last_numeric(record, normalized_keys)
        if transform:
            value = transform(value)
        if value is not None:
            return value, record_date
    return None, None


def garmin_recovery_average(
    snapshot: dict[str, Any],
    section: str,
    keys: tuple[str, ...],
    days: int,
    end_date: date,
    transform: Callable[[Any], float | int | None] | None = None,
) -> float | None:
    normalized_keys = {_garmin_key(key) for key in keys}
    cutoff = end_date - timedelta(days=days - 1)
    values: list[float] = []
    for record_date, record in dated_garmin_recovery_records(snapshot.get(section)):
        try:
            current = date.fromisoformat(record_date[:10])
        except ValueError:
            continue
        if not cutoff <= current <= end_date:
            continue
        value = _garmin_last_numeric(record, normalized_keys)
        if transform:
            value = transform(value)
        number = _as_number(value)
        if number is not None:
            values.append(float(number))
    return round(sum(values) / len(values), 2) if values else None
