"""Garmin body-weight normalization and projections."""

import math
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.decimal_text import provider_number as _as_number
from backend.canonical.vocabulary import ProviderId
from backend.providers import garmin_performance_fields as garmin_perf_fields
from backend.providers.garmin_fields import (
    GARMIN_BODY_FAT_ALIASES,
    GARMIN_WEIGHT_UNIT_ALIASES,
)
from backend.providers.garmin_fields import (
    first_present as _first_present,
)
from backend.providers.garmin_weight_walk import (
    BODY_FAT_SKIP_KEYS,
    WALK_DATE_KEYS,
    WEIGHT_SKIP_KEYS,
    walk_records,
    weight_payload,
)
from backend.providers.source_labels import SourceView, provider_label

UTC_OFFSET_SUFFIX = "+00:00"
GARMIN_PERFORMANCE_SOURCE = provider_label(ProviderId.GARMIN, SourceView.BODY_HISTORY)
# (day, value, timestamp, traversal ordinal) of one accepted weight or body-fat value.
_Accepted = tuple[str | None, float, float | None, int]


def _garmin_key(value: Any) -> str:
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


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
        unit = _first_present(value, GARMIN_WEIGHT_UNIT_ALIASES) or unit
        value = _first_present(value, garmin_perf_fields.WEIGHT_VALUE_ALIASES)
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
            return datetime.fromtimestamp(float(value) / 1000, UTC).date().isoformat()
        except OverflowError, OSError, ValueError:
            return None
    try:
        return iso_date_prefix(str(value).replace("Z", UTC_OFFSET_SUFFIX))
    except AttributeError, TypeError:
        return None


def _garmin_record_timestamp(item: Mapping[str, Any]) -> float | None:
    value = _first_present(item, garmin_perf_fields.WEIGHT_TIMESTAMP_ALIASES)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            scale = 1000 if value > 100_000_000_000 else 1
            return datetime.fromtimestamp(float(value) / scale, UTC).timestamp()
        except OverflowError, OSError, ValueError:
            return None
    if isinstance(value, str) and len(value.strip()) > 10:
        try:
            parsed = datetime.fromisoformat(value.strip())
            return (
                parsed.replace(tzinfo=UTC).timestamp()
                if parsed.tzinfo is None
                else parsed.timestamp()
            )
        except ValueError:
            return None
    return None


def _legacy_record_day(record: Mapping[str, Any]) -> str | None:
    """Text day of a record's own date field, or None so the record inherits one."""
    return _garmin_record_date(_first_present(record, WALK_DATE_KEYS)) or None


def _weight_reading(record: Mapping[str, Any]) -> float | None:
    direct = _first_present(record, garmin_perf_fields.WEIGHT_READING_ALIASES)
    if direct in (None, ""):
        return None
    weight = _garmin_weight_kg(
        direct, _first_present(record, GARMIN_WEIGHT_UNIT_ALIASES)
    )
    return None if weight is None else float(weight)


def _accepted_readings(
    snapshot: Mapping[str, Any],
    skip_keys: frozenset[str],
    read: Callable[[Mapping[str, Any]], float | None],
) -> list[_Accepted]:
    accepted: list[_Accepted] = []
    for walked in walk_records(
        weight_payload(snapshot), skip_keys=skip_keys, resolve_day=_legacy_record_day
    ):
        value = read(walked.record)
        if value is not None:
            accepted.append(
                (
                    walked.day,
                    value,
                    _garmin_record_timestamp(walked.record),
                    walked.ordinal,
                )
            )
    return accepted


def _daily_records(records: list[_Accepted]) -> list[tuple[str | None, float]]:
    latest: dict[str, _Accepted] = {}
    for record in records:
        observed = record[0]
        if observed is None:
            continue
        current = latest.get(observed)
        if current is None or (record[2] is not None, record[2] or 0, record[3]) >= (
            current[2] is not None,
            current[2] or 0,
            current[3],
        ):
            latest[observed] = record
    return [(day, record[1]) for day, record in sorted(latest.items())]


def garmin_weight_records(snapshot: dict[str, Any]) -> list[tuple[str | None, float]]:
    accepted = _accepted_readings(snapshot, WEIGHT_SKIP_KEYS, _weight_reading)
    return list(dict.fromkeys((day, value) for day, value, _, _ in accepted))


def garmin_weight_daily_records(
    snapshot: dict[str, Any],
) -> list[tuple[str | None, float]]:
    return _daily_records(
        _accepted_readings(snapshot, WEIGHT_SKIP_KEYS, _weight_reading)
    )


def _garmin_body_fat_pct(value: Any, unit: Any = None) -> float | None:
    try:
        number = comma_decimal_float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    unit_key = _garmin_key(unit) if unit else ""
    if any(term in unit_key for term in ("fraction", "ratio")):
        number *= 100
    if (
        any(term in unit_key for term in ("fraction", "ratio", "percent"))
        or "%" in str(unit or "")
        or not unit_key
    ):
        return round(number, 2) if 2 <= number <= 70 else None
    return None


def _body_fat_reading(record: Mapping[str, Any]) -> float | None:
    direct = _first_present(record, GARMIN_BODY_FAT_ALIASES)
    if direct in (None, ""):
        return None
    raw_value = direct
    unit = _first_present(record, ("bodyFatUnit", "bodyFatUnitKey"))
    if isinstance(direct, dict):
        unit = _first_present(direct, ("unitKey", "unit", "bodyFatUnit")) or unit
        raw_value = _first_present(direct, ("value", "val", "amount"))
    pct = _garmin_body_fat_pct(raw_value, unit)
    return None if pct is None else float(pct)


def garmin_body_fat_records(snapshot: dict[str, Any]) -> list[tuple[str | None, float]]:
    accepted = _accepted_readings(snapshot, BODY_FAT_SKIP_KEYS, _body_fat_reading)
    return list(dict.fromkeys((day, value) for day, value, _, _ in accepted))


def garmin_body_fat_daily_records(
    snapshot: dict[str, Any],
) -> list[tuple[str | None, float]]:
    return _daily_records(
        _accepted_readings(snapshot, BODY_FAT_SKIP_KEYS, _body_fat_reading)
    )


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
                date.fromisoformat(iso_date_prefix(str(record_date)))
                if record_date
                else None
            )
        except ValueError:
            record_day = None
        if record_day and cutoff <= record_day <= end_date:
            values.append(weight)
    return round(sum(values) / len(values), 2) if values else None
