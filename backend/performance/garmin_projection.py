"""Canonical Garmin training-load projection."""

from collections.abc import Mapping
from datetime import date
from typing import Any, Final

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import MetricKind
from backend.performance import freshness as performance_freshness
from backend.performance.garmin_canonical import GarminCanonicalMetrics

GARMIN_SOURCE = "Garmin Connect"


_BALANCE_FIELDS: Final = {
    MetricKind.LOAD_BALANCE_AEROBIC_LOW: "monthlyLoadAerobicLow",
    MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MIN: "monthlyLoadAerobicLowTargetMin",
    MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MAX: "monthlyLoadAerobicLowTargetMax",
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH: "monthlyLoadAerobicHigh",
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MIN: "monthlyLoadAerobicHighTargetMin",
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MAX: "monthlyLoadAerobicHighTargetMax",
    MetricKind.LOAD_BALANCE_ANAEROBIC: "monthlyLoadAnaerobic",
    MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MIN: "monthlyLoadAnaerobicTargetMin",
    MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MAX: "monthlyLoadAnaerobicTargetMax",
}
_DAILY_FIELDS: Final = {
    MetricKind.ACUTE_LOAD: "acute_load",
    MetricKind.CHRONIC_LOAD: "chronic_load",
    MetricKind.ACUTE_CHRONIC_RATIO: "acute_chronic_ratio",
}


def _canonical_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def _canonical_load_projection(
    freshness: dict[str, Any],
    current_date: date,
    training_load: Mapping[MetricKind, tuple[date, float]],
) -> dict[str, Any]:
    """Project the canonical training load and load balance like the snapshot path.

    Each section is dated by the latest day of its kinds; its values are shown
    only when the section's sync freshness is current and that day is today.
    """
    result: dict[str, Any] = {}
    for key, section, fields in (
        ("four_week_balance", "training_load_balance", _BALANCE_FIELDS),
        ("daily_status", "daily_training_status", _DAILY_FIELDS),
    ):
        latest = {kind: training_load[kind] for kind in fields if kind in training_load}
        if not latest:
            continue
        day = max(observed for observed, _value in latest.values())
        fresh = _fresh_source(freshness.get(section), day.isoformat(), current_date)
        values = {
            fields[kind]: _canonical_number(value) if fresh else None
            for kind, (observed, value) in latest.items()
            if observed == day
        }
        if key == "four_week_balance":
            values = {
                name: value for name, value in values.items() if value is not None
            }
        else:
            values = {name: values.get(name) for name in _DAILY_FIELDS.values()}
        result[key] = {
            "source": GARMIN_SOURCE,
            **freshness.get(section, {"freshness": "unknown"}),
            "date": day.isoformat(),
            **values,
        }
    return result


def garmin_training_load_projection(
    status: performance_freshness.GarminSyncStatus,
    current_date: date,
    canonical: GarminCanonicalMetrics,
) -> dict[str, Any]:
    """Project the canonical Garmin training load and load balance.

    The values come from the canonical training-load and load-balance
    observations; ``status`` supplies only the freshness.
    """
    freshness = performance_freshness.garmin_source_freshness(status, current_date)
    return _canonical_load_projection(freshness, current_date, canonical.training_load)


def _fresh_source(value: Any, observed_at: Any, current_date: date) -> bool:
    return (
        isinstance(value, dict)
        and value.get("freshness")
        in {
            "current",
            "partial",
        }
        and _date(observed_at) == current_date.isoformat()
    )


def _date(value: Any) -> str | None:
    candidate = iso_date_prefix(str(value or ""))
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None
