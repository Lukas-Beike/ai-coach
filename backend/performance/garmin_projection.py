"""Compact projections for Garmin context and recovery payloads."""

from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.performance import freshness as performance_freshness
from backend.performance.activity_validation import bounded_activity_metric

GARMIN_CONTEXT_FIELDS = {
    "date",
    "calendarDate",
    "start",
    "end",
    "sleepTimeSeconds",
    "sleepDuration",
    "sleepScore",
    "overallSleepScore",
    "deepSleepSeconds",
    "lightSleepSeconds",
    "remSleepSeconds",
    "awakeSleepSeconds",
    "value",
    "score",
    "status",
    "hrvStatus",
    "hrvWeeklyAvg",
    "weeklyAvg",
    "hrvLastNight",
    "lastNightAvg",
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
    "startTimeLocal",
    "duration",
    "averageHR",
    "maxHR",
    "maxHeartRate",
    "calories",
    "trainingEffect",
    "trainingEffectLabel",
    "activityTrainingLoad",
    "vO2MaxValue",
    "trainingReadiness",
    "recoveryTime",
    "weight",
    "weightKg",
    "weight_kg",
    "summaryDate",
    "latestWeight",
    "restingHeartRate",
    "restingHR",
    "functionalThresholdPower",
    "ftp",
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


def garmin_training_load_projection(
    snapshot: dict[str, Any], current_date: date
) -> dict[str, Any]:
    """Project new Garmin load endpoints with source and freshness attached."""
    freshness = performance_freshness.garmin_source_freshness(snapshot, current_date)
    result: dict[str, Any] = {}
    balance = _primary_device_record(
        snapshot.get("training_load_balance"),
        "mostRecentTrainingLoadBalance",
        "metricsTrainingLoadBalanceDTOMap",
        (
            "calendarDate",
            "monthlyLoadAerobicLow",
            "monthlyLoadAerobicLowTargetMin",
            "monthlyLoadAerobicLowTargetMax",
            "monthlyLoadAerobicHigh",
            "monthlyLoadAerobicHighTargetMin",
            "monthlyLoadAerobicHighTargetMax",
            "monthlyLoadAnaerobic",
            "monthlyLoadAnaerobicTargetMin",
            "monthlyLoadAnaerobicTargetMax",
        ),
    )
    if balance is not None:
        fields = (
            "monthlyLoadAerobicLow",
            "monthlyLoadAerobicLowTargetMin",
            "monthlyLoadAerobicLowTargetMax",
            "monthlyLoadAerobicHigh",
            "monthlyLoadAerobicHighTargetMin",
            "monthlyLoadAerobicHighTargetMax",
            "monthlyLoadAnaerobic",
            "monthlyLoadAnaerobicTargetMin",
            "monthlyLoadAnaerobicTargetMax",
        )
        result["four_week_balance"] = {
            "source": "Garmin Connect",
            **freshness.get("training_load_balance", {"freshness": "unknown"}),
            "date": _date(balance.get("calendarDate")),
            **{
                key: metric
                for key in fields
                if _fresh_source(
                    freshness.get("training_load_balance"),
                    balance.get("calendarDate"),
                    current_date,
                )
                if (metric := bounded_activity_metric(balance.get(key), 0, 100_000))
                is not None
            },
        }
    daily = _primary_device_record(
        snapshot.get("daily_training_status"),
        "mostRecentTrainingStatus",
        "latestTrainingStatusData",
        (
            "calendarDate",
            "acuteTrainingLoadDTO.dailyTrainingLoadAcute",
            "acuteTrainingLoadDTO.dailyTrainingLoadChronic",
            "acuteTrainingLoadDTO.dailyAcuteChronicWorkloadRatio",
        ),
    )
    acute = daily.get("acuteTrainingLoadDTO") if daily else None
    acute = acute if isinstance(acute, dict) else {}
    if daily is not None:
        result["daily_status"] = {
            "source": "Garmin Connect",
            **freshness.get("daily_training_status", {"freshness": "unknown"}),
            "date": _date(daily.get("calendarDate")),
            "acute_load": bounded_activity_metric(
                acute.get("dailyTrainingLoadAcute"), 0, 100_000
            )
            if daily
            and _fresh_source(
                freshness.get("daily_training_status"),
                daily.get("calendarDate"),
                current_date,
            )
            else None,
            "chronic_load": bounded_activity_metric(
                acute.get("dailyTrainingLoadChronic"), 0, 100_000
            )
            if daily
            and _fresh_source(
                freshness.get("daily_training_status"),
                daily.get("calendarDate"),
                current_date,
            )
            else None,
            "acute_chronic_ratio": bounded_activity_metric(
                acute.get("dailyAcuteChronicWorkloadRatio"), 0, 100
            )
            if daily
            and _fresh_source(
                freshness.get("daily_training_status"),
                daily.get("calendarDate"),
                current_date,
            )
            else None,
        }
    return result


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


def _primary_device_record(
    value: Any,
    section_key: str,
    devices_key: str,
    comparable_fields: tuple[str, ...],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    section = value.get(section_key)
    devices = value.get(devices_key)
    if not isinstance(devices, dict) and isinstance(section, dict):
        devices = section.get(devices_key)
    if not isinstance(devices, dict) or not devices:
        return None
    candidates = [
        dict(item) for item in list(devices.values())[:100] if isinstance(item, dict)
    ]
    primary = _primary_candidates(candidates)
    if primary:
        return (
            primary[0]
            if len(primary) == 1 and _date(primary[0].get("calendarDate"))
            else None
        )
    dated: list[tuple[str, dict[str, Any]]] = []
    for item in candidates:
        day = _date(item.get("calendarDate"))
        if day is not None:
            dated.append((day, item))
    return _latest_unambiguous_record(dated, comparable_fields)


def _primary_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in candidates if item.get("primaryTrainingDevice") is True]


def _latest_unambiguous_record(
    dated: list[tuple[str, dict[str, Any]]], comparable_fields: tuple[str, ...]
) -> dict[str, Any] | None:
    latest = max((day for day, _ in dated), default=None)
    if latest is None:
        return None
    matches = [item for day, item in dated if day == latest]
    return _one_unambiguous_record(matches, comparable_fields)


def _one_unambiguous_record(
    matches: list[dict[str, Any]], comparable_fields: tuple[str, ...]
) -> dict[str, Any] | None:
    if len(matches) == 1:
        return matches[0] if _date(matches[0].get("calendarDate")) else None
    if not matches:
        return None

    def comparable(item: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            _nested_value(item, field.split(".")) for field in comparable_fields
        )

    first = comparable(matches[0])
    return (
        matches[0] if all(comparable(item) == first for item in matches[1:]) else None
    )


def _nested_value(value: dict[str, Any], keys: list[str]) -> Any:
    current: Any = value
    for key in keys:
        current = current.get(key) if isinstance(current, dict) else None
    return current


GARMIN_RECOVERY_FIELDS = (
    "date",
    "calendarDate",
    "summaryDate",
    "sleepTimeSeconds",
    "sleepDuration",
    "sleepScore",
    "overallSleepScore",
    "hrvStatus",
    "hrvWeeklyAvg",
    "weeklyAvg",
    "hrvLastNight",
    "lastNightAvg",
    "bodyBattery",
    "body_battery",
    "charged",
    "drained",
    "score",
    "status",
    "level",
    "qualifier",
    "trainingReadiness",
    "trainingReadinessScore",
    "trainingReadinessLevel",
    "overallReadinessScore",
    "overallReadinessLevel",
    "readinessScore",
    "recoveryTime",
)


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


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
            if _first_present(
                current, ("calendarDate", "summaryDate", "date", "timestamp", "id")
            ):
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
                if _first_present(
                    item, ("calendarDate", "summaryDate", "date", "timestamp")
                )
                else 0,
                str(
                    _first_present(
                        item, ("calendarDate", "summaryDate", "date", "timestamp", "id")
                    )
                    or ""
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
