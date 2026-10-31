"""Garmin wire field names that performance code reads from stored payloads.

The performance package must not know Garmin payload keys.  It imports these
names so a change in the Garmin wire format stays inside the provider adapter.
"""

from typing import Final

from backend.providers.garmin_fields import (
    GARMIN_DATE_ALIASES,
    GARMIN_HRV_LAST_NIGHT_ALIASES,
    GARMIN_HRV_WEEKLY_ALIASES,
    GARMIN_SLEEP_DURATION_ALIASES,
)

CALENDAR_DATE: Final = "calendarDate"
SUMMARY_DATE: Final = "summaryDate"
ACTIVITY_START_LOCAL: Final = "startTimeLocal"
WEEKLY_HRV_AVERAGE, WEEKLY_AVERAGE = GARMIN_HRV_WEEKLY_ALIASES
RESTING_HEART_RATE: Final = "restingHeartRate"
READINESS_SCORE: Final = "trainingReadinessScore"
VO2_MAX_VALUE: Final = "vO2MaxValue"
WEIGHT_KG: Final = "weightKg"
SLEEP_SECONDS: Final = "sleepTimeSeconds"
HRV_NIGHT_AVERAGE: Final = "lastNightAvg"
FTP_VALUE: Final = "functionalThresholdPower"

# Date-bearing keys; each tuple keeps the lookup order it replaces.
RECORD_TIMESTAMP_KEYS: Final = (*GARMIN_DATE_ALIASES, "timestamp")
RECORD_IDENTITY_KEYS: Final = (*GARMIN_DATE_ALIASES, "timestamp", "id")
METRIC_DATE_KEYS: Final = ("date", CALENDAR_DATE, SUMMARY_DATE, "from")
PLANNING_ROW_DATE_KEYS: Final = ("id", "date", CALENDAR_DATE)
WELLNESS_ROW_DATE_KEYS: Final = (CALENDAR_DATE, "date", "id", "timestamp")
OBSERVATION_DATE_FIELDS: Final = (
    CALENDAR_DATE,
    SUMMARY_DATE,
    "date",
    "measurementDate",
    "timestampGMT",
    "timestamp",
    ACTIVITY_START_LOCAL,
    "startTimeGMT",
)

# Value aliases.
SLEEP_DURATION_ALIASES: Final = GARMIN_SLEEP_DURATION_ALIASES
ACTIVITY_FTP_ALIASES: Final = ("ftp", FTP_VALUE)
MAX_HEART_RATE_ALIASES: Final = ("maxHeartRateUsed", "maxHeartRate", "maxHR")
WEIGHT_VALUE_ALIASES: Final = (WEIGHT_KG, "weight_kg", "weight", "value")
WEIGHT_READING_ALIASES: Final = (WEIGHT_KG, "weight_kg", "weight")
WEIGHT_TIMESTAMP_ALIASES: Final = (
    "timestampGMT",
    "timestamp",
    "measurementDate",
    "date",
)
HRV_WITH_WEEKLY_ALIASES: Final = (
    *GARMIN_HRV_LAST_NIGHT_ALIASES,
    *GARMIN_HRV_WEEKLY_ALIASES,
)
PLANNING_READINESS_ALIASES: Final = (
    READINESS_SCORE,
    "overallReadinessScore",
    "readinessScore",
    "score",
    "trainingReadiness",
)
