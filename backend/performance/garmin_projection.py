"""Compact projections for Garmin context and recovery payloads."""

from typing import Any

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
