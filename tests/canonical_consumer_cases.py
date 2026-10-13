"""Synthetic provider inputs shared by the canonical performance reader tests.

Each case holds one stored Intervals.icu snapshot, one Garmin payload and a local
profile. The helpers project the snapshots into canonical observations and pick
the newest wellness row, so the reader tests compare against the same inputs.
This is a helper module, not a test module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import Any, Final

from backend.canonical.records import Observation
from backend.providers.snapshot_projection import (
    project_garmin_snapshot,
    project_intervals_snapshot,
)

ZONE: Final[tzinfo] = UTC
RETRIEVED_AT: Final = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
TODAY: Final = date(2026, 10, 12)


@dataclass(frozen=True, slots=True)
class Case:
    """Synthetic stored inputs shared by the legacy and canonical paths."""

    name: str
    intervals: dict[str, Any]
    garmin: dict[str, Any]
    profile: dict[str, Any]


def _garmin_complete() -> dict[str, Any]:
    day = "2026-10-11"
    return {
        "synced_at": "2026-10-12T06:00:00+00:00",
        "weight": [
            {"calendarDate": day, "weight": 80.4, "bodyFat": 15.2},
            {"calendarDate": day, "weight": 80.1},
        ],
        "sleep": [{"calendarDate": day, "sleepTimeSeconds": 26400, "sleepScore": 84}],
        "resting_hr": [{"calendarDate": day, "restingHeartRate": 45}],
        "hrv": [{"calendarDate": day, "hrvLastNight": 66}],
        "readiness": [{"calendarDate": day, "score": 70}],
        "max_metrics": [
            {
                "calendarDate": day,
                "generic": {"vo2MaxPreciseValue": 56.1},
                "cycling": {"vo2MaxPreciseValue": 58.0},
                "running": {"vo2MaxPreciseValue": 53.5},
            }
        ],
        "cycling_ftp": [{"calendarDate": day, "functionalThresholdPower": 262}],
        "cycling_ftp_history": [
            {"calendarDate": "2026-10-12", "functionalThresholdPower": 268}
        ],
        "running_threshold": [
            {
                "speed_and_heart_rate": {
                    "speed": 3.9,
                    "heartRate": 171,
                    "heartRateCycling": 166,
                },
                "power": {"functionalThresholdPower": 215},
            }
        ],
        "heart_rate_zones": [
            {"sport": "cycling", "maxHeartRateUsed": 184},
            {"sport": "running", "maxHeartRateUsed": 188},
        ],
    }


def _intervals_complete() -> dict[str, Any]:
    return {
        "synced_at": "2026-10-12T06:00:00+00:00",
        "athlete": {
            "id": "athlete-1",
            "sport_settings": [
                {
                    "id": 1,
                    "types": ["Ride"],
                    "ftp": 265,
                    "lthr": 168,
                    "max_hr": 186,
                    "vo2max": 57.5,
                },
                {
                    "id": 2,
                    "types": ["Run"],
                    "threshold_pace": 3.9,
                    "lthr": 172,
                    "max_hr": 190,
                    "vo2max": 54.0,
                },
            ],
        },
        "recent_wellness": [
            {"id": "2026-10-10", "weight": 80.9, "restingHR": 47, "sleepSecs": 25200},
            {
                "id": "2026-10-11",
                "weight": 80.6,
                "bodyFat": 12.5,
                "restingHR": 46,
                "hrv": 62.0,
                "sleepSecs": 27000,
                "sleepScore": 81,
                "readiness": 74,
                "ctl": 58.2,
                "atl": 61.4,
            },
        ],
        "recent_activities": [],
    }


def _build_cases() -> tuple[Case, ...]:
    intervals_only = _intervals_complete()
    intervals_only["athlete"]["sport_settings"] = [
        {"id": 1, "types": ["Ride"], "ftp": 265, "lthr": 168, "vo2max": 57.5},
        {
            "id": 2,
            "types": ["Run"],
            "threshold_pace": 3.9,
            "lthr": 172,
            "vo2max": 54.0,
        },
    ]
    intervals_only["recent_activities"] = [
        {
            "id": "ride-1",
            "type": "Ride",
            "start_date_local": "2026-10-10T08:00:00",
            "max_heartrate": 181,
        },
        {
            "id": "run-1",
            "type": "Run",
            "start_date_local": "2026-10-09T07:00:00",
            "max_heartrate": 176,
        },
    ]
    sparse = {
        "synced_at": "2026-10-12T06:00:00+00:00",
        "athlete": {"id": "athlete-2", "weight": "79.9"},
        "recent_wellness": [
            {
                "id": "2026-10-11",
                "weight": "80,4",
                "restingHR": 47,
                "ctl": "58,2",
                "atl": 61.0,
            }
        ],
        "recent_activities": [],
    }
    sparse_garmin = {
        "sleep": [
            {"calendarDate": "2026-10-11", "sleepTimeSeconds": 0, "sleepScore": 0}
        ],
        "resting_hr": [{"calendarDate": "2026-10-11", "restingHeartRate": 12}],
    }
    return (
        Case("complete", _intervals_complete(), _garmin_complete(), {}),
        Case("intervals_only", intervals_only, {}, {}),
        Case(
            "sparse_profile",
            sparse,
            sparse_garmin,
            {"weight_kg": 78.0, "body_fat_pct": 14.0},
        ),
        Case(
            "garmin_only",
            {"athlete": {}, "recent_wellness": []},
            _garmin_complete(),
            {},
        ),
    )


CASES: Final[tuple[Case, ...]] = _build_cases()


def _wellness_rows(intervals: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = intervals.get("recent_wellness")
    return (
        [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    )


def _latest_wellness(intervals: Mapping[str, Any]) -> dict[str, Any]:
    return max(
        _wellness_rows(intervals),
        key=lambda row: str(row.get("id") or ""),
        default={},
    )


def _latest_wellness_day(latest: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(latest.get("id")))
    except ValueError:
        return None


def _observations(case: Case) -> tuple[Observation, ...]:
    _, intervals = project_intervals_snapshot(
        case.intervals, zone=ZONE, retrieved_at=RETRIEVED_AT
    )
    _, garmin = project_garmin_snapshot(
        case.garmin, zone=ZONE, retrieved_at=RETRIEVED_AT
    )
    return (*intervals.records, *garmin.records)
