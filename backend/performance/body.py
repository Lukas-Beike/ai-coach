"""Historical body metrics and cycling power-to-weight projections."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from statistics import median
from typing import Any

from backend.athlete.local_date import LocalDate
from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance import (
    eftp,
)
from backend.performance.canonical_body import (
    BODY_FAT_BOUNDS,
    WEIGHT_BOUNDS,
    CanonicalBodyInputs,
)
from backend.performance.display_sources import preferred_providers
from backend.performance.wellness_days import WellnessDay
from backend.providers.source_labels import SourceView, provider_label

INTERVALS_SOURCE = provider_label(ProviderId.INTERVALS, SourceView.BODY_HISTORY)
GARMIN_SOURCE = provider_label(ProviderId.GARMIN, SourceView.BODY_HISTORY)
WAHOO_SOURCE = provider_label(ProviderId.WAHOO, SourceView.BODY_HISTORY)
# Body history keys its eFTP-derived FTP series by this label, not the wellness label.
INTERVALS_FTP_SOURCE = "Intervals.icu"
_MEASUREMENT_SOURCES = {
    ProviderId.INTERVALS: INTERVALS_SOURCE,
    ProviderId.GARMIN: GARMIN_SOURCE,
}
_FTP_SOURCES = {
    ProviderId.INTERVALS: INTERVALS_FTP_SOURCE,
    ProviderId.GARMIN: GARMIN_SOURCE,
    ProviderId.WAHOO: WAHOO_SOURCE,
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


def _bounded_weight(value: Any) -> float | None:
    number = _number(value)
    lower, upper = WEIGHT_BOUNDS
    return round(number, 2) if number is not None and lower <= number <= upper else None


def _bounded_body_fat(value: Any) -> float | None:
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


def _intervals_measurements(
    today: date,
    days: Sequence[WellnessDay],
) -> dict[str, dict[date, tuple[float, str, Any]]]:
    values: dict[str, dict[date, tuple[float, str, Any]]] = {
        "weight_kg": {},
        "body_fat_pct": {},
    }
    for item in days:
        if item.day > today:
            continue
        for key, kind, bounded in (
            ("weight_kg", MetricKind.WEIGHT, _bounded_weight),
            ("body_fat_pct", MetricKind.BODY_FAT, _bounded_body_fat),
        ):
            observation = item.observations.get(kind)
            value = None if observation is None else bounded(item.value(kind))
            if observation is None or value is None:
                continue
            retrieved_at = observation.provenance.retrieved_at
            values[key][item.day] = (
                value,
                item.day.isoformat(),
                None if retrieved_at is None else retrieved_at.isoformat(),
            )
    return values


def _garmin_ftp(
    garmin: dict[str, Any], today: date, history: Mapping[date, float]
) -> dict[date, tuple[float, str, Any]]:
    """Garmin's cycling FTP per day from the canonical history."""
    synced_at = _sync_timestamp(garmin, "cycling_ftp_history")
    return {
        day: (float(value), day.isoformat(), synced_at)
        for day, value in history.items()
        if day <= today
    }


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
    values: Mapping[date, float], synced_at: Any
) -> dict[date, tuple[float, str, Any]]:
    """Attach the legacy observed_at and synced_at stamps to canonical values."""
    return {day: (value, day.isoformat(), synced_at) for day, value in values.items()}


def body_history(
    snapshot: dict[str, Any] | None,
    garmin: dict[str, Any] | None,
    today: date,
    *,
    canonical: CanonicalBodyInputs,
    wellness_days: Sequence[WellnessDay],
    activities: Sequence[Mapping[str, Any]],
    garmin_ftp: Mapping[date, float],
    eftp_by_day: Mapping[date, float] | None = None,
) -> dict[str, Any]:
    """Return API-ready 14d/12w charts under performance.history.body.

    Daily points include observed_at and synced_at when measured. Derived power-
    to-weight points also retain separate FTP and weight dates, sync times, and
    weight age. Missing dates stay null; profile values are never observations.

    Wellness measurements come solely from canonical days, Garmin weight, body fat
    and FTP solely from canonical observations, and activity eFTP from the canonical
    activity summaries. The stored views supply only sync times.
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    garmin = garmin if isinstance(garmin, dict) else {}
    intervals = _intervals_measurements(today, wellness_days)
    garmin_synced_at = _sync_timestamp(garmin, "weight")
    garmin_values = {
        "weight_kg": _stamped(canonical.garmin_weight_kg, garmin_synced_at),
        "body_fat_pct": _stamped(canonical.garmin_body_fat_pct, garmin_synced_at),
    }
    weights = {
        ProviderId.INTERVALS: intervals["weight_kg"],
        ProviderId.GARMIN: garmin_values["weight_kg"],
    }
    intervals_ftp: dict[date, tuple[float, str, Any]] = {}
    for observed_at, value in eftp.eftp_daily_values(
        eftp_by_day,
        list(activities),
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
        ProviderId.GARMIN: _garmin_ftp(garmin, today, garmin_ftp),
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
