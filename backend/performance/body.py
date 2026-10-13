"""Historical body metrics and cycling power-to-weight projections."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from statistics import median
from typing import Any

from backend.athlete.local_date import LocalDate
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.vocabulary import ProviderId
from backend.performance import (
    activity_validation,
    eftp,
    garmin_metric_history,
    garmin_weight,
)
from backend.performance.canonical_body import (
    BODY_FAT_BOUNDS,
    WEIGHT_BOUNDS,
    CanonicalBodyInputs,
)
from backend.performance.display_sources import preferred_providers
from backend.providers import garmin_performance_fields as garmin_perf_fields
from backend.providers.source_labels import SourceView, provider_label

INTERVALS_SOURCE = provider_label(ProviderId.INTERVALS, SourceView.BODY_HISTORY)
GARMIN_SOURCE = provider_label(ProviderId.GARMIN, SourceView.BODY_HISTORY)
# Body history keys its eFTP-derived FTP series by this label, not the wellness label.
INTERVALS_FTP_SOURCE = "Intervals.icu"
_MEASUREMENT_SOURCES = {
    ProviderId.INTERVALS: INTERVALS_SOURCE,
    ProviderId.GARMIN: GARMIN_SOURCE,
}
_FTP_SOURCES = {
    ProviderId.INTERVALS: INTERVALS_FTP_SOURCE,
    ProviderId.GARMIN: GARMIN_SOURCE,
}


def _number(value: Any) -> float | None:
    try:
        result = comma_decimal_float(value)
    except TypeError, ValueError:
        return None
    return result if math.isfinite(result) else None


def _day(value: Any) -> date | None:
    try:
        return LocalDate.parse(value).to_date()
    except TypeError, ValueError:
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
        value = value.get(
            "value", value.get(garmin_perf_fields.WEIGHT_KG, value.get("weight"))
        )
    number = _number(value)
    lower, upper = WEIGHT_BOUNDS
    return round(number, 2) if number is not None and lower <= number <= upper else None


def _bounded_body_fat(value: Any) -> float | None:
    if isinstance(value, dict):
        unit = value.get("unit") or value.get("unitKey")
        if unit and "%" not in str(unit) and "percent" not in str(unit).casefold():
            return None
        value = value.get("value", value.get("percent", value.get("bodyFat")))
    number = _number(value)
    lower, upper = BODY_FAT_BOUNDS
    return round(number, 2) if number is not None and lower <= number <= upper else None


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


def _snapshot_activity_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("raw_provider_data")
    raw_rows = raw.get("activities") if isinstance(raw, dict) else []
    return _rows(snapshot.get("recent_activities")) + _rows(raw_rows)


def _intervals_measurements(
    snapshot: dict[str, Any],
    today: date,
    wellness: Sequence[dict[str, Any]] | None = None,
) -> dict[str, dict[date, tuple[float, str, Any]]]:
    values: dict[str, dict[date, tuple[float, str, Any]]] = {
        "weight_kg": {},
        "body_fat_pct": {},
    }
    synced_at = snapshot.get("synced_at")
    for row in _wellness_records(snapshot) if wellness is None else wellness:
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
    history_synced_at = _sync_timestamp(garmin, "cycling_ftp_history")
    for row in garmin_metric_history.ftp_points(
        garmin.get("cycling_ftp_history"),
        start=today - timedelta(days=89),
        end=today,
    ):
        observed = _day(row["date"])
        if observed is not None:
            result[observed] = (float(row["value"]), row["date"], history_synced_at)
    _append_performance_ftp(garmin, today, history_synced_at, result)
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
            for key in garmin_perf_fields.RECORD_TIMESTAMP_KEYS
            if value.get(key)
        ),
        None,
    )
    return _day(raw) or fallback_day


def _direct_ftp_value(value):
    return next(
        (
            value.get(key)
            for key in garmin_perf_fields.DIRECT_FTP_VALUE_KEYS
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
    provider: ProviderId,
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
        "source": _MEASUREMENT_SOURCES[provider],
        "source_provider": provider.value,
        "unit": unit,
        "points": points,
        "weekly": _weekly(points, start, end),
    }


def _quotient_series(
    provider: ProviderId,
    method: str,
    ftp: dict[date, tuple[float, str, Any]],
    weights: dict[ProviderId, dict[date, tuple[float, str, Any]]],
    start: date,
    end: date,
) -> dict[str, Any]:
    all_weights = [
        (day, record, weight_provider)
        for weight_provider, records in weights.items()
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
                key=lambda item: (item[0], item[2] is ProviderId.GARMIN),
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
                weight_day, weight_record, weight_provider = weight_item
                weight_value = weight_record[0]
                point.update(
                    {
                        "value": round(ftp_value / weight_value, 3),
                        "weight_kg": weight_value,
                        "weight_source": _MEASUREMENT_SOURCES[weight_provider],
                        "weight_observed_at": weight_record[1],
                        "weight_synced_at": weight_record[2],
                        "weight_age_days": (day - weight_day).days,
                    }
                )
        points.append(point)
    return {
        "source": _FTP_SOURCES[provider],
        "source_provider": provider.value,
        "power_method": method,
        "unit": "W/kg",
        "points": points,
        "weekly": _weekly(points, start, end),
    }


def _stamped(
    values: dict[date, float], synced_at: Any
) -> dict[date, tuple[float, str, Any]]:
    """Attach the legacy observed_at and synced_at stamps to canonical values."""
    return {day: (value, day.isoformat(), synced_at) for day, value in values.items()}


def body_history(
    snapshot: dict[str, Any] | None,
    garmin: dict[str, Any] | None,
    today: date,
    *,
    canonical: CanonicalBodyInputs | None = None,
    wellness_rows: Sequence[dict[str, Any]] | None = None,
    activity_rows: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return API-ready 14d/12w charts under performance.history.body.

    Daily points include observed_at and synced_at when measured. Derived power-
    to-weight points also retain separate FTP and weight dates, sync times, and
    weight age. Missing dates stay null; profile values are never observations.

    ``canonical`` overrides only the weight and body-fat days it holds. Days it lacks
    keep the legacy value, so values the canonical mapper does not store are not
    dropped. When None, the legacy wellness and Garmin readers are used, as before.

    ``wellness_rows`` and ``activity_rows`` are the rows rebuilt from the canonical
    read ports; without them the snapshot sections are read.
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    garmin = garmin if isinstance(garmin, dict) else {}
    intervals = _intervals_measurements(snapshot, today, wellness_rows)
    garmin_values = _garmin_measurements(garmin, today)
    if canonical is not None:
        garmin_synced_at = _sync_timestamp(garmin, "weight")
        intervals["weight_kg"] = {
            **intervals["weight_kg"],
            **_stamped(canonical.intervals_weight_kg, snapshot.get("synced_at")),
        }
        intervals["body_fat_pct"] = {
            **intervals["body_fat_pct"],
            **_stamped(canonical.intervals_body_fat_pct, snapshot.get("synced_at")),
        }
        garmin_values["weight_kg"] = {
            **garmin_values["weight_kg"],
            **_stamped(canonical.garmin_weight_kg, garmin_synced_at),
        }
        garmin_values["body_fat_pct"] = {
            **garmin_values["body_fat_pct"],
            **_stamped(canonical.garmin_body_fat_pct, garmin_synced_at),
        }
    weights = {
        ProviderId.INTERVALS: intervals["weight_kg"],
        ProviderId.GARMIN: garmin_values["weight_kg"],
    }
    intervals_ftp: dict[date, tuple[float, str, Any]] = {}
    for observed_at, value in eftp.eftp_daily_values(
        _wellness_records(snapshot) if wellness_rows is None else list(wellness_rows),
        _snapshot_activity_rows(snapshot)
        if activity_rows is None
        else list(activity_rows),
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
    ftp: dict[ProviderId, dict[date, tuple[float, str, Any]]] = {
        ProviderId.GARMIN: _garmin_ftp(garmin, today),
        ProviderId.INTERVALS: intervals_ftp,
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
                    _series(provider, "kg", values, start, today)
                    for provider, values in weights.items()
                ],
                "body_fat_pct": [
                    _series(
                        ProviderId.INTERVALS,
                        "%",
                        intervals["body_fat_pct"],
                        start,
                        today,
                    ),
                    _series(
                        ProviderId.GARMIN,
                        "%",
                        garmin_values["body_fat_pct"],
                        start,
                        today,
                    ),
                ],
                "cycling_w_per_kg": [
                    _quotient_series(
                        provider,
                        "FTP" if provider is ProviderId.GARMIN else "eFTP",
                        values,
                        weights,
                        start,
                        today,
                    )
                    for provider, values in ftp.items()
                ],
            },
        }
    return {
        "version": 1,
        "default_window": "12w",
        "windows": windows,
        "preferred_providers": preferred_providers(),
    }
