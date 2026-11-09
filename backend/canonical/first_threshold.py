"""The athlete's measured first-threshold heart rate (a profile value).

Entered by the athlete only (for example from a lab lactate or gas-exchange
test) in bpm and stored as percent of the lactate threshold HR in effect on the
measurement date; empty means not set. Stdlib and canonical text helpers only.
"""

from __future__ import annotations

import math
from typing import Final

from backend.canonical.decimal_text import comma_decimal_float

# The stored value (percent of LTHR), and the transient entry fields of a save.
FIRST_THRESHOLD_FIELD: Final = "first_threshold_pct"
FIRST_THRESHOLD_ENTRY_FIELD: Final = "first_threshold_hr"
FIRST_THRESHOLD_DATE_FIELD: Final = "first_threshold_on"
FIRST_THRESHOLD_BOUNDS: Final = (60, 220)
FIRST_THRESHOLD_PERCENT_BOUNDS: Final = (40.0, 100.0)


def _number(value: object) -> float | None:
    try:
        number = comma_decimal_float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def first_threshold_bpm(value: object) -> float | None:
    """The measured first threshold (bpm) entered by the athlete, or None if unset or implausible."""
    number = _number(value)
    low, high = FIRST_THRESHOLD_BOUNDS
    return number if number is not None and low <= number <= high else None


def first_threshold_percent(value: object) -> float | None:
    """The stored first threshold (percent of LTHR), or None if unset or implausible."""
    number = _number(value)
    low, high = FIRST_THRESHOLD_PERCENT_BOUNDS
    return number if number is not None and low <= number <= high else None


def percent_of_lthr(bpm: float, lthr: float) -> float | None:
    """The first threshold as percent of ``lthr``, one decimal, or None if implausible."""
    if lthr <= 0:
        return None
    return first_threshold_percent(round(bpm / lthr * 100, 1))
