"""Historical body metrics and cycling power-to-weight projections."""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import median
from typing import Any

from backend.performance import (
    activity_validation,
    eftp,
    garmin_metric_history,
    garmin_weight,
)

INTERVALS_SOURCE = "Intervals.icu Wellness"
GARMIN_SOURCE = "Garmin Connect"


def _number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _rows(value: Any) -> list[dict[str, Any]]:
    return (
        [row for row in value if isinstance(row, dict)]
        if isinstance(value, list)
        else []
    )


def _bounded_weight(value: Any) -> float | None:
    if isinstance(value, dict):
        unit = value.get("unit") or value.get("unitKey")
        if unit and "kg" not in str(unit).casefold():
            return None
        value = value.get("value", value.get("weightKg", value.get("weight")))
    number = _number(value)
    return round(number, 2) if number is not None and 30 <= number <= 300 else None


def _bounded_body_fat(value: Any) -> float | None:
    if isinstance(value, dict):
        unit = value.get("unit") or value.get("unitKey")
        if unit and "%" not in str(unit) and "percent" not in str(unit).casefold():
            return None
        value = value.get("value", value.get("percent", value.get("bodyFat")))
    number = _number(value)
    return round(number, 2) if number is not None and 2 <= number <= 70 else None


def _sync_timestamp(payload: dict[str, Any], source: str) -> Any:
    freshness = payload.get("source_freshness")
    details = freshness.get(source) if isinstance(freshness, dict) else None
    if isinstance(details, dict):
        return (
            details.get("fetched_at")
            or details.get("synced_at")
            or payload.get("synced_at")
            or payload.get("fetched_at")
        )
    return payload.get("synced_at") or payload.get("fetched_at")


def _wellness_records(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("raw_provider_data")
    raw_rows = raw.get("wellness") if isinstance(raw, dict) else []
    # Compact rows follow raw rows so the saved compact projection wins on duplicates.
    return _rows(raw_rows) + _rows(snapshot.get("recent_wellness"))


def _intervals_measurements(
    snapshot: dict[str, Any], today: date
) -> dict[str, dict[date, tuple[float, str, Any]]]:
    values: dict[str, dict[date, tuple[float, str, Any]]] = {
        "weight_kg": {},
        "body_fat_pct": {},
    }
    synced_at = snapshot.get("synced_at")
    for row in _wellness_records(snapshot):
        observed = _day(row.get("id") or row.get("date"))
        if observed is None or observed > today:
            continue
        weight = _bounded_weight(row.get("weight"))
        body_fat = _bounded_body_fat(
            row.get("bodyFat", row.get("body_fat", row.get("body_fat_pct")))
        )
        if weight is not None:
            values["weight_kg"][observed] = (weight, observed.isoformat(), synced_at)
        if body_fat is not None:
            values["body_fat_pct"][observed] = (
                body_fat,
                observed.isoformat(),
                synced_at,
            )
    return values


def _garmin_measurements(
    garmin: dict[str, Any], today: date
) -> dict[str, dict[date, tuple[float, str, Any]]]:
    synced_at = _sync_timestamp(garmin, "weight")
    result: dict[str, dict[date, tuple[float, str, Any]]] = {
        "weight_kg": {},
        "body_fat_pct": {},
    }
    for observed_text, value in garmin_weight.garmin_weight_daily_records(garmin):
        observed = _day(observed_text)
        if observed is not None and observed <= today:
            result["weight_kg"][observed] = (value, observed.isoformat(), synced_at)
    for observed_text, value in garmin_weight.garmin_body_fat_daily_records(garmin):
        observed = _day(observed_text)
        if observed is not None and observed <= today:
            result["body_fat_pct"][observed] = (value, observed.isoformat(), synced_at)
    return result


def _garmin_ftp(
    garmin: dict[str, Any], today: date
) -> dict[date, tuple[float, str, Any]]:
    result: dict[date, tuple[float, str, Any]] = {}
    synced_at = _sync_timestamp(garmin, "cycling_ftp")
    for row in garmin_metric_history.ftp_points(
        garmin.get("cycling_ftp_history"),
        start=today - timedelta(days=89),
        end=today,
    ):
        observed = _day(row["date"])
        if observed is not None:
            result[observed] = (float(row["value"]), row["date"], synced_at)
    _append_performance_ftp(garmin, today, synced_at, result)
    direct = garmin.get("cycling_ftp")
    freshness = garmin.get("source_freshness")
    fallback_day = _day(
        freshness.get("cycling_ftp", {}).get("observed_at")
        if isinstance(freshness, dict)
        and isinstance(freshness.get("cycling_ftp"), dict)
        else None
    )

    _append_direct_ftp(direct, today, fallback_day, synced_at, result)
    return result


def _append_performance_ftp(garmin, today, synced_at, result) -> None:
    for row in _rows(garmin.get("performance_history")):
        observed = _day(row.get("date"))
        metrics = row.get("metrics")
        value = (
            activity_validation.bounded_performance_metric(
                "cycling_ftp_watts", metrics.get("cycling_ftp_watts")
            )
            if observed is not None and isinstance(metrics, dict)
            else None
        )
        if observed is not None and observed <= today and value is not None:
            result[observed] = (float(value), observed.isoformat(), synced_at)


def _append_direct_ftp(direct, today, fallback_day, synced_at, result) -> None:
    budget = [2000]

    _visit_direct_ftp(direct, None, 0, budget, today, fallback_day, synced_at, result)


def _visit_direct_ftp(
    value, inherited, depth, budget, today, fallback_day, synced_at, result
) -> None:
    if depth > 20 or budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(value, dict):
        _visit_direct_dict(
            value, inherited, depth, budget, today, fallback_day, synced_at, result
        )
    elif isinstance(value, list):
        _visit_direct_list(
            value, inherited, depth, budget, today, fallback_day, synced_at, result
        )


def _visit_direct_dict(
    value, inherited, depth, budget, today, fallback_day, synced_at, result
) -> None:
    observed = _direct_ftp_record(
        value, inherited or fallback_day, today, synced_at, result
    )
    for child in value.values():
        if isinstance(child, (dict, list)):
            _visit_direct_ftp(
                child,
                observed,
                depth + 1,
                budget,
                today,
                fallback_day,
                synced_at,
                result,
            )


def _visit_direct_list(
    value, inherited, depth, budget, today, fallback_day, synced_at, result
) -> None:
    for child in value[:500]:
        _visit_direct_ftp(
            child, inherited, depth + 1, budget, today, fallback_day, synced_at, result
        )


def _direct_ftp_record(value, fallback_day, today, synced_at, result):
    observed = _direct_ftp_date(value, fallback_day)
    candidate = _direct_ftp_value(value)
    number = activity_validation.bounded_performance_metric(
        "cycling_ftp_watts", candidate
    )
    if observed is not None and observed <= today and number is not None:
        result[observed] = (float(number), observed.isoformat(), synced_at)
    return observed


def _direct_ftp_date(value, fallback_day):
    raw = next(
        (
            value.get(key)
            for key in ("calendarDate", "summaryDate", "date", "timestamp")
            if value.get(key)
        ),
        None,
    )
    return _day(raw) or fallback_day


def _direct_ftp_value(value):
    return next(
        (
            value.get(key)
            for key in ("functionalThresholdPower", "ftp", "power")
            if value.get(key) not in (None, "")
        ),
        None,
    )


def _point(day: date, record: tuple[float, str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {"date": day.isoformat(), "value": None}
    value, observed_at, synced_at = record
    return {
        "date": day.isoformat(),
        "value": value,
        "observed_at": observed_at,
        "synced_at": synced_at,
        "sync_timestamp": synced_at,
    }


def _weekly(
    points: list[dict[str, Any]], start: date, end: date
) -> list[dict[str, Any]]:
    weeks: list[dict[str, Any]] = []
    # Fixed rolling 7-day buckets keep an 84-day selection to exactly 12 weeks.
    for offset in range(0, (end - start).days + 1, 7):
        bucket_start = start + timedelta(days=offset)
        bucket_end = min(bucket_start + timedelta(days=6), end)
        items = [
            point
            for point in points
            if bucket_start.isoformat() <= point["date"] <= bucket_end.isoformat()
            and point.get("value") is not None
        ]
        weeks.append(
            {
                "week_start": bucket_start.isoformat(),
                "week_end": bucket_end.isoformat(),
                "value": round(
                    float(median([float(item["value"]) for item in items])), 2
                )
                if items
                else None,
                "count": len(items),
                "dates": [item["date"] for item in items],
            }
        )
    return weeks


def _series(
    source: str,
    unit: str,
    records: dict[date, tuple[float, str, Any]],
    start: date,
    end: date,
) -> dict[str, Any]:
    points = [
        _point(
            start + timedelta(days=index), records.get(start + timedelta(days=index))
        )
        for index in range((end - start).days + 1)
    ]
    return {
        "source": source,
        "unit": unit,
        "points": points,
        "weekly": _weekly(points, start, end),
    }


def _quotient_series(
    source: str,
    method: str,
    ftp: dict[date, tuple[float, str, Any]],
    weights: dict[str, dict[date, tuple[float, str, Any]]],
    start: date,
    end: date,
) -> dict[str, Any]:
    all_weights = [
        (day, record, provider)
        for provider, records in weights.items()
        for day, record in records.items()
    ]
    points: list[dict[str, Any]] = []
    for index in range((end - start).days + 1):
        day = start + timedelta(days=index)
        ftp_record = ftp.get(day)
        point = _point(day, None)
        if ftp_record is not None:
            ftp_value, observed_at, synced_at = ftp_record
            candidates = [
                item
                for item in all_weights
                if day - timedelta(days=7) <= item[0] <= day
            ]
            weight_item = max(
                candidates,
                key=lambda item: (item[0], item[2] == GARMIN_SOURCE),
                default=None,
            )
            point.update(
                {
                    "ftp_watts": ftp_value,
                    "observed_at": observed_at,
                    "synced_at": synced_at,
                    "ftp_observed_at": observed_at,
                    "ftp_synced_at": synced_at,
                }
            )
            if weight_item is not None:
                weight_day, weight_record, weight_source = weight_item
                weight_value = weight_record[0]
                point.update(
                    {
                        "value": round(ftp_value / weight_value, 3),
                        "weight_kg": weight_value,
                        "weight_source": weight_source,
                        "weight_observed_at": weight_record[1],
                        "weight_synced_at": weight_record[2],
                        "weight_age_days": (day - weight_day).days,
                    }
                )
        points.append(point)
    return {
        "source": source,
        "power_method": method,
        "unit": "W/kg",
        "points": points,
        "weekly": _weekly(points, start, end),
    }


def body_history(
    snapshot: dict[str, Any] | None, garmin: dict[str, Any] | None, today: date
) -> dict[str, Any]:
    """Return API-ready 14d/12w charts under performance.history.body.

    Daily points include observed_at and synced_at when measured. Derived power-
    to-weight points also retain separate FTP and weight dates, sync times, and
    weight age. Missing dates stay null; profile values are never observations.
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    garmin = garmin if isinstance(garmin, dict) else {}
    intervals = _intervals_measurements(snapshot, today)
    garmin_values = _garmin_measurements(garmin, today)
    weights = {
        INTERVALS_SOURCE: intervals["weight_kg"],
        GARMIN_SOURCE: garmin_values["weight_kg"],
    }
    intervals_ftp: dict[date, tuple[float, str, Any]] = {}
    for observed_at, value in eftp.eftp_daily_values(
        _wellness_records(snapshot),
        _rows(snapshot.get("recent_activities"))
        + _rows(
            (snapshot.get("raw_provider_data") or {}).get("activities")
            if isinstance(snapshot.get("raw_provider_data"), dict)
            else []
        ),
        today - timedelta(days=83),
        today,
    ).items():
        observed = _day(observed_at)
        if observed is not None:
            intervals_ftp[observed] = (
                value,
                observed.isoformat(),
                snapshot.get("synced_at"),
            )
    ftp: dict[str, dict[date, tuple[float, str, Any]]] = {
        GARMIN_SOURCE: _garmin_ftp(garmin, today),
        "Intervals.icu": intervals_ftp,
    }
    windows: dict[str, Any] = {}
    for key, days in (("14d", 14), ("12w", 84)):
        start = today - timedelta(days=days - 1)
        windows[key] = {
            "start": start.isoformat(),
            "end": today.isoformat(),
            "days": days,
            "metrics": {
                "weight_kg": [
                    _series(source, "kg", values, start, today)
                    for source, values in weights.items()
                ],
                "body_fat_pct": [
                    _series(
                        INTERVALS_SOURCE, "%", intervals["body_fat_pct"], start, today
                    ),
                    _series(
                        GARMIN_SOURCE, "%", garmin_values["body_fat_pct"], start, today
                    ),
                ],
                "cycling_w_per_kg": [
                    _quotient_series(
                        source,
                        "FTP" if source == GARMIN_SOURCE else "eFTP",
                        values,
                        weights,
                        start,
                        today,
                    )
                    for source, values in ftp.items()
                ],
            },
        }
    return {"version": 1, "default_window": "12w", "windows": windows}
