"""Heart-rate caps of easy run units, stored as percent of the threshold HR.

A run unit of a capped type (``HR_CAP_PERCENT``) stores ``hr_cap``:
``{"percent_lthr": 87, "low_percent_lthr": 65, "source": "default"}``. Only
percentages are stored: the bpm is resolved wherever it is read, checked or
exported, from the lactate threshold HR in effect on the unit's date, so the
watch's own LTHR updates apply without editing a unit. The source says where the
percent comes from: the default table, the athlete's measured first threshold
(profile value ``first_threshold_pct``, entered by the athlete) or an estimated
one the athlete adopted (same value, profile origin ``estimated``). This module
is the only place that holds the cap values and the rules that derive the
measured and the exported ones; prompts, labels, checks and tests read it. Pure.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

from backend.canonical.planning_fields import HR_CAP

# Default upper limit in percent of the threshold HR by the unit's ``session_focus``.
# The athlete decides these values; change them here only.
HR_CAP_PERCENT: Final[Mapping[str, float]] = {
    "recovery": 80.0,
    "easy": 87.0,
    "long": 87.0,
}
# With a measured first threshold: the easy and long cap is that threshold's
# percent of the threshold HR minus this margin (percentage points), and the
# recovery cap is the lower of its default and the easy cap minus the gap.
MEASURED_MARGIN_PCT: Final = 3.0
RECOVERY_BELOW_EASY_PCT: Final = 7.0
# The lower bound of the exported range, in percent of the threshold HR, never
# above the cap minus the gap (percentage points): a wide range so that only the
# cap alerts the athlete on the watch.
EXPORT_FLOOR_PERCENT: Final = 65.0
EXPORT_FLOOR_BELOW_CAP_PCT: Final = 15.0
SOURCE_DEFAULT: Final = "default"
SOURCE_MEASURED: Final = "measured"
SOURCE_ESTIMATED: Final = "estimated"
SOURCES: Final = (SOURCE_DEFAULT, SOURCE_MEASURED, SOURCE_ESTIMATED)
_SOURCE_LABELS: Final = {
    SOURCE_DEFAULT: "Standard",
    SOURCE_MEASURED: "gemessen",
    SOURCE_ESTIMATED: "geschätzt",
}
HR_CAP_KEY: Final = HR_CAP
PERCENT_KEY: Final = "percent_lthr"
LOW_PERCENT_KEY: Final = "low_percent_lthr"
SOURCE_KEY: Final = "source"
LTHR_LABEL: Final = "LSHF"
# Bounds that keep a stored percent plausible.
_PERCENT_BOUNDS: Final = (20.0, 120.0)


def _floor_tenth(value: float) -> float:
    return math.floor(value * 10 + 1e-9) / 10


def export_floor_percent(cap_percent: float) -> float:
    """The lower bound of the exported range in percent of the threshold HR."""
    return _floor_tenth(
        min(EXPORT_FLOOR_PERCENT, cap_percent - EXPORT_FLOOR_BELOW_CAP_PCT)
    )


def cap_percents(
    first_threshold_pct: float | None, estimated: bool = False
) -> tuple[dict[str, float], str]:
    """The cap percent per capped type and its source.

    ``first_threshold_pct`` is the athlete's first threshold as percent of the
    threshold HR on its measurement date; ``estimated`` says it is an adopted
    estimate, not a measurement. Without one, or when it gives an implausible
    cap, the default table applies.
    """
    if first_threshold_pct is not None:
        easy = _floor_tenth(first_threshold_pct - MEASURED_MARGIN_PCT)
        recovery = min(
            HR_CAP_PERCENT["recovery"], _floor_tenth(easy - RECOVERY_BELOW_EASY_PCT)
        )
        floor_ok = (
            export_floor_percent(recovery) >= _PERCENT_BOUNDS[0]
            and export_floor_percent(easy) >= _PERCENT_BOUNDS[0]
        )
        if floor_ok and recovery >= _PERCENT_BOUNDS[0] and easy <= 100.0:
            return {
                focus: recovery if focus == "recovery" else easy
                for focus in HR_CAP_PERCENT
            }, SOURCE_ESTIMATED if estimated else SOURCE_MEASURED
    return dict(HR_CAP_PERCENT), SOURCE_DEFAULT


def hr_cap(percent: float, source: str = SOURCE_DEFAULT) -> dict[str, Any]:
    """The cap value to store for a cap percent: percentages and the source only."""
    return {
        PERCENT_KEY: percent,
        LOW_PERCENT_KEY: export_floor_percent(percent),
        SOURCE_KEY: source,
    }


def effective_caps(
    first_threshold_pct: float | None, estimated: bool = False
) -> dict[str, dict[str, Any]]:
    """The cap value to store for each capped type."""
    percents, source = cap_percents(first_threshold_pct, estimated)
    return {focus: hr_cap(percent, source) for focus, percent in percents.items()}


def resolve_bpm(percent: float, lthr: float | None) -> int | None:
    """The bpm of ``percent`` of ``lthr``, rounded half up; None without a threshold HR."""
    if not lthr or lthr <= 0:
        return None
    return math.floor(percent * lthr / 100 + 0.5)


def resolved_range(
    cap: Mapping[str, Any], lthr: float | None
) -> tuple[int, int] | None:
    """The cap's (low, high) in bpm for ``lthr``, or None when no threshold HR is known."""
    high = resolve_bpm(cap[PERCENT_KEY], lthr)
    low = resolve_bpm(cap[LOW_PERCENT_KEY], lthr)
    return None if high is None or low is None else (low, high)


def percent_text(percent: float) -> str:
    return f"{percent:g}"


def normalize_hr_cap(value: object) -> dict[str, Any]:
    """The stored cap of a request value; ``ValueError`` when it is malformed."""
    keys = {PERCENT_KEY, LOW_PERCENT_KEY, SOURCE_KEY}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError("hr_cap needs percent_lthr, low_percent_lthr and source")
    percent, low, source = (
        value[PERCENT_KEY],
        value[LOW_PERCENT_KEY],
        value[SOURCE_KEY],
    )
    for number in (percent, low):
        if (
            isinstance(number, bool)
            or not isinstance(number, int | float)
            or not math.isfinite(number)
            or not _PERCENT_BOUNDS[0] <= number <= _PERCENT_BOUNDS[1]
        ):
            raise ValueError("hr_cap needs plausible percentages")
    if low >= percent or source not in SOURCES:
        raise ValueError("hr_cap needs a lower bound below the cap and a known source")
    return {
        PERCENT_KEY: float(percent),
        LOW_PERCENT_KEY: float(low),
        SOURCE_KEY: source,
    }


def stored_cap(unit: Mapping[str, Any]) -> dict[str, Any] | None:
    """The valid cap stored on a unit payload, or None (a malformed one counts as none)."""
    value = unit.get(HR_CAP_KEY)
    focus = str(unit.get("session_focus") or "").strip().casefold()
    if value is None or focus not in HR_CAP_PERCENT:
        # A cap left over from another focus does not apply.
        return None
    try:
        return normalize_hr_cap(value)
    except ValueError:
        return None


def cap_label(cap: Mapping[str, Any], lthr: float | None = None) -> str:
    """The card text: percent first, then the currently resolved bpm, then the source.

    For example ``≤ 87 % LSHF · 142 bpm · Standard``; without a known threshold
    HR only the percent is shown.
    """
    bpm = resolve_bpm(cap[PERCENT_KEY], lthr)
    parts = [f"≤ {percent_text(float(cap[PERCENT_KEY]))} % {LTHR_LABEL}"]
    if bpm is not None:
        parts.append(f"{bpm} bpm")
    parts.append(_SOURCE_LABELS[cap[SOURCE_KEY]])
    return " · ".join(parts)


def cap_table_text() -> str:
    """The default caps of all capped types in one line, derived from the table."""
    return ", ".join(
        f"{focus} ≤{percent_text(percent)} %"
        for focus, percent in HR_CAP_PERCENT.items()
    )
