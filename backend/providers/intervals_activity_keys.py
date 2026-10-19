"""Intervals.icu activity wire keys that activity projections select and read.

The activity package must not know Intervals.icu payload keys. The names below
are also keys of the app's own calendar and coach activity JSON, which the PWA
consumes, so their values must not change.
"""

from collections.abc import Mapping
from typing import Any, Final

from backend.providers.intervals_performance_fields import (  # noqa: F401
    CONFIGURED_FTP,
    INTENSITY,
    PACE,
    RPE,
    TRAINING_LOAD,
    WEIGHTED_AVG_SPEED,
    WEIGHTED_AVG_WATTS,
)

ROLLING_FTP: Final = "icu_rolling_ftp"
LACTATE_THRESHOLD_HR: Final = "lthr"

TRAINING_LOAD_LOOKUP: Final = (TRAINING_LOAD, "training_load", "tss")


def activity_ftp(activity: Mapping[str, Any]) -> Any:
    """Return the functional threshold power the provider stored on an activity."""
    return activity.get(CONFIGURED_FTP)


def activity_lthr(activity: Mapping[str, Any]) -> Any:
    """Return the lactate threshold heart rate the provider stored on an activity."""
    return activity.get(LACTATE_THRESHOLD_HR)


def activity_training_load(activity: Mapping[str, Any]) -> Any:
    """Return the provider-computed training load of an activity."""
    return activity.get(TRAINING_LOAD)
