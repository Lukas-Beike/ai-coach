"""Shared Garmin field aliases and value lookup, without runtime dependencies."""

from collections.abc import Mapping
from typing import Any

GARMIN_DATE_ALIASES = ("calendarDate", "summaryDate", "date")
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


def first_present(item: Any, keys: tuple[str, ...]) -> Any:
    """Return the first non-empty field value, preserving zero and False."""
    if not isinstance(item, Mapping):
        return None
    return next((item[key] for key in keys if item.get(key) not in (None, "")), None)
