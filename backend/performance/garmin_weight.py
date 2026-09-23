"""Garmin body-weight normalization and projections."""

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

UTC_OFFSET_SUFFIX = "+00:00"
GARMIN_PERFORMANCE_SOURCE = "Garmin Connect"


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


def _metric(
    value: Any, unit: str, source: str | None, note: str = ""
) -> dict[str, Any]:
    number = _as_number(value)
    return {
        "value": number,
        "unit": unit,
        "source": source if number is not None else None,
        "note": note if number is not None else "",
    }


def _garmin_weight_kg(value: Any, unit: Any = None) -> float | int | None:
    if isinstance(value, dict):
        unit = _first_present(value, ("unitKey", "unit", "weightUnit")) or unit
        value = _first_present(value, ("weightKg", "weight_kg", "weight", "value"))
    number = _as_number(value)
    if number is None:
        return None
    unit_key = _garmin_key(unit) if unit else ""
    if "lb" in unit_key or "pound" in unit_key:
        number *= 0.45359237
    elif number > 300:
        number /= 1000
    if not 30 <= float(number) <= 300:
        return None
    return round(number, 2)


def _garmin_record_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and value > 100_000_000_000:
        try:
            return (
                datetime.fromtimestamp(float(value) / 1000, timezone.utc)
                .date()
                .isoformat()
            )
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return str(value).replace("Z", UTC_OFFSET_SUFFIX)[:10]
    except (AttributeError, TypeError):
        return None


def _collect_garmin_weight_records(
    value: Any,
    records: list[tuple[str | None, float]],
    inherited_date: str | None = None,
) -> None:
    if isinstance(value, dict):
        record_date = (
            _garmin_record_date(
                _first_present(
                    value,
                    (
                        "calendarDate",
                        "summaryDate",
                        "date",
                        "timestampGMT",
                        "timestamp",
                    ),
                )
            )
            or inherited_date
        )
        direct = _first_present(value, ("weightKg", "weight_kg", "weight"))
        if direct not in (None, ""):
            weight = _garmin_weight_kg(
                direct, _first_present(value, ("unitKey", "unit", "weightUnit"))
            )
            if weight is not None:
                records.append((record_date, float(weight)))
        for key, item in value.items():
            if _garmin_key(key) not in {"minweight", "maxweight", "weightdelta"}:
                _collect_garmin_weight_records(item, records, record_date)
    elif isinstance(value, list):
        for item in value[:500]:
            _collect_garmin_weight_records(item, records, inherited_date)


def garmin_weight_records(snapshot: dict[str, Any]) -> list[tuple[str | None, float]]:
    records: list[tuple[str | None, float]] = []
    _collect_garmin_weight_records(snapshot.get("weight"), records)
    return list(dict.fromkeys(records))


def garmin_weight_metric(snapshot: dict[str, Any]) -> dict[str, Any]:
    records = garmin_weight_records(snapshot)
    if not records:
        return _metric(None, "kg", None)
    dated = sorted(records, key=lambda item: item[0] or "")
    return _metric(
        dated[-1][1],
        "kg",
        GARMIN_PERFORMANCE_SOURCE,
        "Garmin Connect Körpergewicht",
    )


def garmin_weight_average(
    snapshot: dict[str, Any], days: int, end_date: date
) -> float | None:
    cutoff = end_date - timedelta(days=days - 1)
    values: list[float] = []
    for record_date, weight in garmin_weight_records(snapshot):
        try:
            record_day = (
                date.fromisoformat(str(record_date)[:10]) if record_date else None
            )
        except ValueError:
            record_day = None
        if record_day and cutoff <= record_day <= end_date:
            values.append(weight)
    return round(sum(values) / len(values), 2) if values else None
