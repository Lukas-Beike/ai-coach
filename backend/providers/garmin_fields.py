"""Shared Garmin field aliases and value lookup, without runtime dependencies."""

from collections.abc import Mapping
from typing import Any

GARMIN_CALENDAR_DATE_KEY = "calendarDate"
GARMIN_DATE_ALIASES = (GARMIN_CALENDAR_DATE_KEY, "summaryDate", "date")
GARMIN_MEASUREMENT_DATE_ALIASES = (
    "date",
    *GARMIN_DATE_ALIASES[:2],
    "measurementTime",
    "timestamp",
)
GARMIN_EXTENDED_DATE_ALIASES = (*GARMIN_DATE_ALIASES, "measurementTime", "timestamp")
GARMIN_HRV_SUMMARIES_KEY = "hrvSummaries"
GARMIN_SLEEP_DATE_KEYS = ("calendarDate", "summaryDate")
GARMIN_SLEEP_DURATION_ALIASES = ("sleepTimeSeconds", "sleepDuration")
GARMIN_SLEEP_SCORE_ALIASES = ("sleepScore", "overallSleepScore")
GARMIN_HRV_LAST_NIGHT_ALIASES = ("hrvLastNight", "lastNightAvg")
GARMIN_RESTING_HR_ALIASES = ("restingHeartRate", "restingHR", "resting_heart_rate")
GARMIN_READINESS_ALIASES = (
    "score",
    "trainingReadinessScore",
    "overallReadinessScore",
    "readinessScore",
)
GARMIN_VO2MAX_ALIASES = ("vo2MaxPreciseValue", "vo2MaxValue")
GARMIN_FTP_ALIASES = ("functionalThresholdPower", "ftp")
GARMIN_BODY_FAT_ALIASES = (
    "bodyFat",
    "body_fat",
    "bodyFatPercent",
    "bodyFatPercentage",
    "fatPercent",
)
GARMIN_WEIGHT_ALIASES = ("weight", "weightKg", "weight_kg", "value")
GARMIN_WEIGHT_UNIT_ALIASES = ("unitKey", "unit", "weightUnit")
GARMIN_RUNNING_THRESHOLD_ALIASES = ("speed", "speedInMetersPerSecond", "thresholdPace")
GARMIN_STEPS_ALIASES = ("totalSteps", "total_steps", "steps", "stepCount", "step_count")
GARMIN_FLOORS_ALIASES = (
    "floorsAscended",
    "floors_ascended",
    "floors",
    "floorsUp",
    "floors_up",
)
GARMIN_TOTAL_KCAL_ALIASES = (
    "totalKilocalories",
    "total_kilocalories",
    "totalCalories",
    "total_calories",
    "calories",
)
GARMIN_ACTIVE_KCAL_ALIASES = (
    "activeKilocalories",
    "active_kilocalories",
    "activeCalories",
    "active_calories",
    "activeCaloriesBurned",
    "active_calories_burned",
)
GARMIN_ENDURANCE_SCORE_ALIASES = ("overallScore",)
GARMIN_ENDURANCE_WRAPPER_KEYS = ("enduranceScoreDTO", "enduranceScoreDTOList")
GARMIN_RACE_TIME_ALIASES = (
    "raceTime",
    "racePredictionTime",
    "predictedTime",
    "time",
    "seconds",
    "value",
)
GARMIN_RACE_DISTANCE_ALIASES = ("raceDistance", "distanceName", "raceType", "distance")


# Garmin's range endpoint nests the daily values the per-day summary keeps flat.
_NESTED_DAILY_FIELDS = (
    (("calories", "burnedTotal"), "totalKilocalories"),
    (("calories", "burnedActive"), "activeKilocalories"),
    (("calories", "burnedResting"), "bmrKilocalories"),
    (("movement", "steps", "value"), "totalSteps"),
    (("movement", "floorsAscended", "value"), "floorsAscended"),
)


def _nested_value(record: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def flatten_daily_summary(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Add the flat per-day aliases for a nested range-endpoint daily record.

    Existing flat keys win, so a per-day summary is returned unchanged.
    """
    extra = {
        alias: value
        for path, alias in _NESTED_DAILY_FIELDS
        if (value := _nested_value(record, path)) not in (None, "")
    }
    if not extra:
        return record
    flat = {
        key: value
        for key, value in record.items()
        if value not in (None, "")
        and not (key == "calories" and isinstance(value, Mapping))
    }
    return {**extra, **flat}


def first_present(item: Any, keys: tuple[str, ...]) -> Any:
    """Return the first non-empty field value, preserving zero and False."""
    if not isinstance(item, Mapping):
        return None
    return next((item[key] for key in keys if item.get(key) not in (None, "")), None)
