"""Fail-fast validation for canonical records.

Missing values are represented as None and are never coerced to zero. Wrong
types raise TypeError; wrong or out-of-range values raise ValueError. Every
message names the offending field.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from typing import Final

from backend.canonical.vocabulary import MetricKind

MAX_TEXT_LENGTH: Final = 256
HEART_RATE_BOUNDS: Final = (20.0, 250.0)
MAX_ACTIVITY_DURATION_S: Final = 7 * 24 * 3600.0
MAX_ACTIVITY_DISTANCE_M: Final = 2_000_000.0
MAX_ACTIVITY_LOAD: Final = 10_000.0
MAX_ACTIVITY_POWER_W: Final = 5_000.0
MAX_ACTIVITY_ELEVATION_M: Final = 100_000.0
MAX_ACTIVITY_CADENCE_RPM: Final = 300.0
MAX_ACTIVITY_ENERGY_KJ: Final = 1_000_000.0
MAX_ACTIVITY_SPEED_MPS: Final = 100.0
MIN_ACTIVITY_ALTITUDE_M: Final = -500.0
MAX_ACTIVITY_ALTITUDE_M: Final = 9_000.0
MAX_ACTIVITY_STEPS: Final = 1_000_000.0

# Seconds, as accepted by the legacy Garmin race-prediction reader.
RACE_PREDICTION_BOUNDS: Final = (60.0, 100_000.0)

METRIC_BOUNDS: Final[Mapping[MetricKind, tuple[float, float]]] = {
    MetricKind.WEIGHT: (20.0, 400.0),
    MetricKind.BODY_FAT: (1.0, 80.0),
    MetricKind.FTP: (0.0, 2_500.0),
    MetricKind.THRESHOLD_HR: HEART_RATE_BOUNDS,
    MetricKind.MAX_HR: HEART_RATE_BOUNDS,
    MetricKind.RESTING_HR: HEART_RATE_BOUNDS,
    MetricKind.HRV_RMSSD: (0.0, 500.0),
    MetricKind.HRV_SDNN: (0.0, 500.0),
    MetricKind.HRV_WEEKLY_AVERAGE: (0.0, 500.0),
    MetricKind.SLEEP_DURATION: (0.0, 86_400.0),
    MetricKind.SLEEP_SCORE: (0.0, 100.0),
    MetricKind.VO2MAX: (5.0, 120.0),
    MetricKind.THRESHOLD_PACE: (0.0, 15.0),
    MetricKind.ZONE2_PACE: (0.0, 15.0),
    MetricKind.W_PRIME: (0.0, 200_000.0),
    MetricKind.HEIGHT: (30.0, 300.0),
    MetricKind.BODY_BATTERY: (0.0, 100.0),
    MetricKind.READINESS: (0.0, 100.0),
    MetricKind.CTL: (0.0, 10_000.0),
    MetricKind.ATL: (0.0, 10_000.0),
    MetricKind.TRAINING_LOAD: (0.0, 10_000.0),
    # Form (CTL minus ATL) is negative while fatigue outweighs fitness.
    MetricKind.FORM: (-10_000.0, 10_000.0),
    MetricKind.EFTP: (0.0, 2_500.0),
    MetricKind.RUN_THRESHOLD_POWER: (0.0, 2_500.0),
    MetricKind.DAILY_ENERGY_TOTAL: (0.0, 20_000.0),
    MetricKind.DAILY_ENERGY_ACTIVE: (0.0, 20_000.0),
    MetricKind.STEPS: (0.0, 200_000.0),
    MetricKind.FLOORS: (0.0, 1_000.0),
    MetricKind.STRESS: (0.0, 100.0),
    MetricKind.RACE_PREDICTION_5K: RACE_PREDICTION_BOUNDS,
    MetricKind.RACE_PREDICTION_10K: RACE_PREDICTION_BOUNDS,
    MetricKind.RACE_PREDICTION_HALF: RACE_PREDICTION_BOUNDS,
    MetricKind.RACE_PREDICTION_FULL: RACE_PREDICTION_BOUNDS,
    MetricKind.ENDURANCE_SCORE: (0.0, 20_000.0),
    MetricKind.DAILY_ENERGY_RESTING: (0.0, 20_000.0),
    # Charged and drained are totals of level changes, so a day can exceed 100.
    MetricKind.BODY_BATTERY_CHARGED: (0.0, 500.0),
    MetricKind.BODY_BATTERY_DRAINED: (0.0, 500.0),
    MetricKind.ACUTE_LOAD: (0.0, 100_000.0),
    MetricKind.CHRONIC_LOAD: (0.0, 100_000.0),
    MetricKind.ACUTE_CHRONIC_RATIO: (0.0, 100.0),
    MetricKind.LOAD_BALANCE_AEROBIC_LOW: (0.0, 100_000.0),
    MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MIN: (0.0, 100_000.0),
    MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MAX: (0.0, 100_000.0),
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH: (0.0, 100_000.0),
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MIN: (0.0, 100_000.0),
    MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MAX: (0.0, 100_000.0),
    MetricKind.LOAD_BALANCE_ANAEROBIC: (0.0, 100_000.0),
    MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MIN: (0.0, 100_000.0),
    MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MAX: (0.0, 100_000.0),
    MetricKind.RUNNING_TOLERANCE: (0.0, 100_000.0),
    MetricKind.ENDURANCE_SCORE_GROUP_AVERAGE: (0.0, 20_000.0),
    MetricKind.ENDURANCE_SCORE_GROUP_MAX: (0.0, 20_000.0),
    # The provider's 1 to 4 wellness rating scale.
    MetricKind.SUBJECTIVE_FATIGUE: (1.0, 4.0),
    MetricKind.SUBJECTIVE_SORENESS: (1.0, 4.0),
    MetricKind.SUBJECTIVE_STRESS: (1.0, 4.0),
    MetricKind.SUBJECTIVE_MOOD: (1.0, 4.0),
}


def require_instance[T](value: object, expected: type[T], field: str) -> T:
    if not isinstance(value, expected):
        raise TypeError(f"{field} must be a {expected.__name__}")
    return value


def require_text(
    value: object, field: str, *, max_length: int = MAX_TEXT_LENGTH
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    if not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    if len(value) > max_length:
        raise ValueError(f"{field} must be at most {max_length} characters")
    return value


def optional_text(
    value: object, field: str, *, max_length: int = MAX_TEXT_LENGTH
) -> str | None:
    if value is None:
        return None
    return require_text(value, field, max_length=max_length)


def finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be a number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{field} must be finite") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def bounded_number(value: object, field: str, lower: float, upper: float) -> float:
    number = finite_number(value, field)
    if not lower <= number <= upper:
        raise ValueError(f"{field} must be between {lower:g} and {upper:g}")
    return number


def optional_bounded_number(
    value: object, field: str, lower: float, upper: float
) -> float | None:
    if value is None:
        return None
    return bounded_number(value, field, lower, upper)


def require_aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def optional_aware_datetime(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    return require_aware_datetime(value, field)


def require_date(value: object, field: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field} must be a date")
    return value


def validate_metric_value(kind: MetricKind, value: object, unit: str) -> None:
    """Reject a unit other than the kind's canonical unit, then bound the value."""
    if unit != kind.unit:
        raise ValueError(f"{kind.value} must use unit {kind.unit!r}, not {unit!r}")
    lower, upper = METRIC_BOUNDS[kind]
    bounded_number(value, f"{kind.value} value", lower, upper)
