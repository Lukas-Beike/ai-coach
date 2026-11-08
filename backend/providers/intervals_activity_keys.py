"""Intervals.icu activity wire keys that the output side and diagnostics read.

The activity package must not know Intervals.icu payload keys. The names below
are also keys of the app's own calendar and coach activity JSON, which the PWA
consumes, so their values must not change.
"""

from collections.abc import Mapping
from typing import Any, Final

from backend.providers.intervals_performance_fields import TRAINING_LOAD

# The ``source`` enum of the Intervals.icu Activity schema (GET /api/v1/docs):
# the service an activity reached Intervals.icu from.
ACTIVITY_SOURCES: Final = frozenset(
    (
        "STRAVA",
        "UPLOAD",
        "MANUAL",
        "GARMIN_CONNECT",
        "OAUTH_CLIENT",
        "DROPBOX",
        "POLAR",
        "SUUNTO",
        "COROS",
        "WAHOO",
        "ZWIFT",
        "ZEPP",
        "CONCEPT2",
        "HUAWEI",
    )
)


def activity_training_load(activity: Mapping[str, Any]) -> Any:
    """Return the provider-computed training load of an activity."""
    return activity.get(TRAINING_LOAD)
