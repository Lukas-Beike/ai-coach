"""This morning's overnight HRV and resting heart rate for the illness return.

Both compare with the athlete's own earlier nights through the existing personal
recovery baselines (``personal-quartiles-v1``, 42 days, at least 14 earlier
nights, measurement-context segments): the HRV (RMSSD) is "not below the usual
range" while its position is not ``below`` the lower quartile, and the usual
resting heart rate is the baseline median. A value that is not from this morning,
or a baseline without enough nights, is missing and leaves the check-in alone to
decide (#2042).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Final

from backend.performance.canonical_inputs import resolve_reader
from backend.performance.canonical_recovery import (
    CanonicalRecoveryInputs,
    read_recovery_inputs,
)
from backend.performance.personal_recovery import personal_recovery
from backend.performance.source_policy import NO_PREFERENCES, SourcePreferences
from backend.runtime.ports import ObservationReader

_USABLE: Final = {"ok", "provisional"}
_SERIES: Final = (("hrv", "RMSSD", "hrv"), ("resting_hr", "resting", "resting_hr"))
_KEYS: Final = (
    "source",
    "value",
    "unit",
    "observed_at",
    "median",
    "lower",
    "upper",
    "position",
)


def overnight_signals(
    recovery: CanonicalRecoveryInputs, today: date
) -> dict[str, dict[str, Any]]:
    """The usable HRV and resting heart rate baselines of this morning."""
    # The profile only feeds the sleep baselines, which the return does not read.
    baselines = personal_recovery({}, today, canonical=recovery)["baselines"]
    found: dict[str, dict[str, Any]] = {}
    for baseline in baselines:
        for metric, measurement, name in _SERIES:
            if (
                baseline["metric"] == metric
                and baseline["measurement"] == measurement
                and baseline["status"] in _USABLE
                and baseline["observed_at"] == today.isoformat()
            ):
                found.setdefault(name, {key: baseline.get(key) for key in _KEYS})
    return found


def overnight_reader(
    database_manager: Any,
    observation_reader: Callable[[], ObservationReader],
    source_preferences: Callable[[Any], SourcePreferences] | None,
    today: Callable[[], date],
) -> Callable[[], dict[str, dict[str, Any]]]:
    """A reader of this morning's signals in its own read transaction."""

    def read() -> dict[str, dict[str, Any]]:
        day = today()
        with database_manager.reader() as db:
            recovery = read_recovery_inputs(
                resolve_reader(observation_reader(), db),
                db,
                as_of=day,
                preferences=(
                    NO_PREFERENCES
                    if source_preferences is None
                    else source_preferences(db)
                ),
            )
        return overnight_signals(recovery, day)

    return read
