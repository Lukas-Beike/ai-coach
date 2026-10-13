"""Intervals.icu activity wire keys that activity projections select and read.

The activity package must not know Intervals.icu payload keys. The names below
are also keys of the app's own calendar and coach activity JSON, which the PWA
consumes, so their values must not change.
"""

from collections.abc import Mapping
from typing import Any, Final

from backend.providers.intervals_performance_fields import CONFIGURED_FTP, TRAINING_LOAD

INTENSITY: Final = "icu_intensity"
ROLLING_FTP: Final = "icu_rolling_ftp"
WEIGHTED_AVG_WATTS: Final = "icu_weighted_avg_watts"
WEIGHTED_AVG_SPEED: Final = "icu_weighted_avg_speed"
PACE: Final = "icu_pace"
RPE: Final = "icu_rpe"

TRAINING_LOAD_LOOKUP: Final = (TRAINING_LOAD, "training_load", "tss")


def activity_ftp(activity: Mapping[str, Any]) -> Any:
    """Return the functional threshold power the provider stored on an activity."""
    return activity.get(CONFIGURED_FTP)


def activity_training_load(activity: Mapping[str, Any]) -> Any:
    """Return the provider-computed training load of an activity."""
    return activity.get(TRAINING_LOAD)
