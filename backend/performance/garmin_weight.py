"""Garmin body-weight normalization and projections."""

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.athlete.local_date import iso_date_prefix

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
    except TypeError, ValueError:
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
        except OverflowError, OSError, ValueError:
            return None
    try:
        return iso_date_prefix(str(value).replace("Z", UTC_OFFSET_SUFFIX))
    except AttributeError, TypeError:
        return None


def _garmin_record_timestamp(item: dict[str, Any]) -> float | None:
    value = _first_present(
        item, ("timestampGMT", "timestamp", "measurementDate", "date")
    )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            scale = 1000 if value > 100_000_000_000 else 1
            return datetime.fromtimestamp(
                float(value) / scale, timezone.utc
            ).timestamp()
        except OverflowError, OSError, ValueError:
            return None
    if isinstance(value, str) and len(value.strip()) > 10:
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return (
                parsed.replace(tzinfo=timezone.utc).timestamp()
                if parsed.tzinfo is None
                else parsed.timestamp()
            )
        except ValueError:
            return None
    return None


def _collect_garmin_weight_records(
    value: Any,
    records: list[tuple[str | None, float]],
    inherited_date: str | None = None,
    daily: list[tuple[str | None, float, float | None, int]] | None = None,
    sequence: list[int] | None = None,
    depth: int = 0,
    visits: list[int] | None = None,
) -> None:
    visits = visits if visits is not None else [0]
    if depth > 20 or visits[0] >= 2000:
        return
    visits[0] += 1
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
        _append_weight_record(value, record_date, records, daily, sequence)
        for key, item in value.items():
            if _garmin_key(key) not in {"minweight", "maxweight", "weightdelta"}:
                _collect_garmin_weight_records(
                    item, records, record_date, daily, sequence, depth + 1, visits
                )
    elif isinstance(value, list):
        for item in value[:500]:
            _collect_garmin_weight_records(
                item, records, inherited_date, daily, sequence, depth + 1, visits
            )


def garmin_weight_records(snapshot: dict[str, Any]) -> list[tuple[str | None, float]]:
    records: list[tuple[str | None, float]] = []
    _collect_garmin_weight_records(
        snapshot.get("weight") or snapshot.get("weigh_ins") or snapshot.get("weighIns"),
        records,
    )
    return list(dict.fromkeys(records))


def _daily_records(
    records: list[tuple[str | None, float, float | None, int]],
) -> list[tuple[str | None, float]]:
    latest: dict[str, tuple[str | None, float, float | None, int]] = {}
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


def garmin_weight_daily_records(
    snapshot: dict[str, Any],
) -> list[tuple[str | None, float]]:
    detailed: list[tuple[str | None, float, float | None, int]] = []
    _collect_garmin_weight_records(
        snapshot.get("weight") or snapshot.get("weigh_ins") or snapshot.get("weighIns"),
        [],
        daily=detailed,
        sequence=[0],
        visits=[0],
    )
    return _daily_records(detailed)


def _garmin_body_fat_pct(value: Any, unit: Any = None) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
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


def _collect_garmin_body_fat_records(
    value: Any,
    records: list[tuple[str | None, float]],
    inherited_date: str | None = None,
    daily: list[tuple[str | None, float, float | None, int]] | None = None,
    sequence: list[int] | None = None,
    depth: int = 0,
    visits: list[int] | None = None,
) -> None:
    visits = visits if visits is not None else [0]
    if depth > 20 or visits[0] >= 2000:
        return
    visits[0] += 1
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
        _append_body_fat_record(value, record_date, records, daily, sequence)
        for key, item in value.items():
            if _garmin_key(key) not in {"minbodyfat", "maxbodyfat", "bodyfatdelta"}:
                _collect_garmin_body_fat_records(
                    item, records, record_date, daily, sequence, depth + 1, visits
                )
    elif isinstance(value, list):
        for item in value[:500]:
            _collect_garmin_body_fat_records(
                item, records, inherited_date, daily, sequence, depth + 1, visits
            )


def garmin_body_fat_records(snapshot: dict[str, Any]) -> list[tuple[str | None, float]]:
    records: list[tuple[str | None, float]] = []
    _collect_garmin_body_fat_records(
        snapshot.get("weight") or snapshot.get("weigh_ins") or snapshot.get("weighIns"),
        records,
    )
    return list(dict.fromkeys(records))


def garmin_body_fat_daily_records(
    snapshot: dict[str, Any],
) -> list[tuple[str | None, float]]:
    detailed: list[tuple[str | None, float, float | None, int]] = []
    _collect_garmin_body_fat_records(
        snapshot.get("weight") or snapshot.get("weigh_ins") or snapshot.get("weighIns"),
        [],
        daily=detailed,
        sequence=[0],
        visits=[0],
    )
    return _daily_records(detailed)


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


def _append_weight_record(
    value: dict[str, Any],
    record_date: str | None,
    records: list,
    daily: list | None,
    sequence: list[int] | None,
) -> None:
    direct = _first_present(value, ("weightKg", "weight_kg", "weight"))
    if direct not in (None, ""):
        weight = _garmin_weight_kg(
            direct, _first_present(value, ("unitKey", "unit", "weightUnit"))
        )
        if weight is not None:
            records.append((record_date, float(weight)))
            if daily is not None and sequence is not None:
                daily.append(
                    (
                        record_date,
                        float(weight),
                        _garmin_record_timestamp(value),
                        sequence[0],
                    )
                )
                sequence[0] += 1


def _append_body_fat_record(
    value: dict[str, Any],
    record_date: str | None,
    records: list,
    daily: list | None,
    sequence: list[int] | None,
) -> None:
    direct = _first_present(
        value,
        (
            "bodyFat",
            "body_fat",
            "bodyFatPercent",
            "bodyFatPercentage",
            "fatPercent",
        ),
    )
    if direct not in (None, ""):
        raw_value = direct
        unit = _first_present(value, ("bodyFatUnit", "bodyFatUnitKey"))
        if isinstance(direct, dict):
            unit = _first_present(direct, ("unitKey", "unit", "bodyFatUnit")) or unit
            raw_value = _first_present(direct, ("value", "val", "amount"))
        pct = _garmin_body_fat_pct(raw_value, unit)
        if pct is not None:
            records.append((record_date, pct))
            if daily is not None and sequence is not None:
                daily.append(
                    (
                        record_date,
                        pct,
                        _garmin_record_timestamp(value),
                        sequence[0],
                    )
                )
                sequence[0] += 1
