"""Compact projections for Garmin context and recovery payloads."""

from collections.abc import Mapping
from datetime import date
from typing import Any, Final

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import MetricKind
from backend.performance import freshness as performance_freshness
from backend.performance.garmin_canonical import GarminCanonicalMetrics
from backend.providers import garmin_performance_fields as garmin_perf_fields
from backend.providers.garmin_fields import (
    GARMIN_FTP_ALIASES,
    GARMIN_HRV_LAST_NIGHT_ALIASES,
    GARMIN_SLEEP_DURATION_ALIASES,
    GARMIN_SLEEP_SCORE_ALIASES,
)
from backend.providers.garmin_fields import (
    first_present as _first_present,
)

GARMIN_SOURCE = "Garmin Connect"
GARMIN_CONTEXT_FIELDS = {
    "date",
    garmin_perf_fields.CALENDAR_DATE,
    "start",
    "end",
    *GARMIN_SLEEP_DURATION_ALIASES,
    *GARMIN_SLEEP_SCORE_ALIASES,
    "deepSleepSeconds",
    "lightSleepSeconds",
    "remSleepSeconds",
    "awakeSleepSeconds",
    "value",
    "score",
    "status",
    "hrvStatus",
    garmin_perf_fields.WEEKLY_HRV_AVERAGE,
    garmin_perf_fields.WEEKLY_AVERAGE,
    *GARMIN_HRV_LAST_NIGHT_ALIASES,
    "bodyBattery",
    "body_battery",
    "charged",
    "drained",
    "qualifier",
    "racePredictionTime",
    "distance",
    "activityId",
    "activityName",
    "activityType",
    garmin_perf_fields.ACTIVITY_START_LOCAL,
    "duration",
    "averageHR",
    "maxHR",
    "maxHeartRate",
    "calories",
    "trainingEffect",
    "trainingEffectLabel",
    "activityTrainingLoad",
    garmin_perf_fields.VO2_MAX_VALUE,
    "trainingReadiness",
    "recoveryTime",
    "weight",
    garmin_perf_fields.WEIGHT_KG,
    "weight_kg",
    garmin_perf_fields.SUMMARY_DATE,
    "latestWeight",
    garmin_perf_fields.RESTING_HEART_RATE,
    "restingHR",
    *GARMIN_FTP_ALIASES,
    "power",
    "speed",
    "heartRate",
    "hearRate",
    "heartRateCycling",
    "heartRateRunning",
}


def compact_garmin_context(value: Any, depth: int = 0) -> Any:
    """Keep measured Garmin metrics while dropping free-form/vendor payloads."""
    if depth > 3:
        return None
    if isinstance(value, dict):
        return {
            str(key): compact_garmin_context(item, depth + 1)
            for key, item in value.items()
            if str(key) in GARMIN_CONTEXT_FIELDS
            and compact_garmin_context(item, depth + 1) is not None
        }
    if isinstance(value, list):
        return [compact_garmin_context(item, depth + 1) for item in value[:100]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


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
    snapshot: dict[str, Any],
    current_date: date,
    canonical: GarminCanonicalMetrics,
) -> dict[str, Any]:
    """Project the canonical Garmin training load and load balance.

    The values come from the canonical training-load and load-balance
    observations; freshness is sync status and stays on the snapshot.
    """
    freshness = performance_freshness.garmin_source_freshness(snapshot, current_date)
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


GARMIN_RECOVERY_FIELDS = (
    "date",
    garmin_perf_fields.CALENDAR_DATE,
    garmin_perf_fields.SUMMARY_DATE,
    *GARMIN_SLEEP_DURATION_ALIASES,
    *GARMIN_SLEEP_SCORE_ALIASES,
    "hrvStatus",
    garmin_perf_fields.WEEKLY_HRV_AVERAGE,
    garmin_perf_fields.WEEKLY_AVERAGE,
    *GARMIN_HRV_LAST_NIGHT_ALIASES,
    "bodyBattery",
    "body_battery",
    "charged",
    "drained",
    "score",
    "status",
    "level",
    "qualifier",
    "trainingReadiness",
    garmin_perf_fields.READINESS_SCORE,
    "trainingReadinessLevel",
    "overallReadinessScore",
    "overallReadinessLevel",
    "readinessScore",
    "recoveryTime",
)


def _selected(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in fields if key in item and item[key] is not None}


def latest_garmin_record(value: Any) -> dict[str, Any]:
    """Return one dated Garmin record without exposing the complete range payload."""
    if not isinstance(value, (dict, list)):
        return {}
    records: list[dict[str, Any]] = []
    pending: list[Any] = [value]
    visited = 0
    while pending and visited < 2000:
        current = pending.pop()
        visited += 1
        if isinstance(current, dict):
            if _first_present(current, garmin_perf_fields.RECORD_IDENTITY_KEYS):
                records.append(current)
            pending.extend(
                item for item in current.values() if isinstance(item, (dict, list))
            )
        elif isinstance(current, list):
            pending.extend(
                item for item in current[:500] if isinstance(item, (dict, list))
            )
    if records:
        return max(
            records,
            key=lambda item: (
                1
                if _first_present(item, garmin_perf_fields.RECORD_TIMESTAMP_KEYS)
                else 0,
                str(
                    _first_present(item, garmin_perf_fields.RECORD_IDENTITY_KEYS) or ""
                ),
            ),
            default={},
        )
    return value if isinstance(value, dict) else {}


def compact_garmin_recovery(value: Any) -> dict[str, Any]:
    if isinstance(value, (int, float, bool)):
        return {"value": value}
    record = latest_garmin_record(value)
    return _selected(record, GARMIN_RECOVERY_FIELDS)
