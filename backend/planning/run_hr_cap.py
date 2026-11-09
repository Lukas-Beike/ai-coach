"""What is wrong with the heart-rate cap of a Coach-written easy run unit.

A run unit whose set ``session_focus`` has a cap (``HR_CAP_PERCENT``) needs
``hr_cap``: a percent not above the effective cap (the default table, or the
athlete's measured first threshold), the exported lower bound that belongs to it
and the source of the cap. Only percentages are stored and checked: the bpm is
resolved from the threshold HR in effect on the unit's date wherever it is read
or exported, so a threshold change never makes a stored unit wrong. Each problem
names the value to write. Pure, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from backend.activities.hr_cap import (
    HR_CAP_KEY,
    HR_CAP_PERCENT,
    LOW_PERCENT_KEY,
    PERCENT_KEY,
    SOURCE_KEY,
    cap_percents,
    effective_caps,
    export_floor_percent,
    hr_cap,
    normalize_hr_cap,
    percent_text,
)
from backend.canonical.first_threshold import (
    FIRST_THRESHOLD_FIELD,
    first_threshold_estimated,
    first_threshold_percent,
)
from backend.canonical.planning_fields import SESSION_FOCUS
from backend.canonical.vocabulary import Sport
from backend.planning.sport import planned_sport_environment

MISSING: Final = "missing"
MALFORMED: Final = "malformed"
TOO_HIGH: Final = "too_high"
SOURCE_MISMATCH: Final = "source_mismatch"
LOW_MISMATCH: Final = "low_mismatch"


def capped_focus(unit: Mapping[str, Any]) -> str | None:
    """The set focus of a run unit when its type has a cap, else None."""
    if planned_sport_environment(unit)[0] is not Sport.RUN:
        return None
    focus = str(unit.get(SESSION_FOCUS) or "").strip().casefold()
    return focus if focus in HR_CAP_PERCENT else None


def cap_problem(
    unit: Mapping[str, Any],
    first_threshold_pct: float | None = None,
    estimated: bool = False,
) -> dict[str, Any] | None:
    """The problem of one run unit's cap with the value to write, or None if right."""
    focus = capped_focus(unit)
    if focus is None:
        return None
    percents, source = cap_percents(first_threshold_pct, estimated)
    limit = percents[focus]
    base: dict[str, Any] = {
        "focus": focus,
        "limit_percent_lthr": limit,
        "cap_source": source,
        "expected": hr_cap(limit, source),
    }
    raw = unit.get(HR_CAP_KEY)
    if raw is None:
        return {**base, "reason": MISSING}
    try:
        cap = normalize_hr_cap(raw)
    except ValueError:
        return {**base, "reason": MALFORMED}
    if cap[PERCENT_KEY] > limit:
        return {**base, "reason": TOO_HIGH, "stored": cap}
    if cap[SOURCE_KEY] != source:
        return {**base, "reason": SOURCE_MISMATCH, "stored": cap}
    if cap[LOW_PERCENT_KEY] != export_floor_percent(cap[PERCENT_KEY]):
        return {
            **base,
            "reason": LOW_MISMATCH,
            "stored": cap,
            "expected": hr_cap(cap[PERCENT_KEY], source),
        }
    return None


def problems(
    units: Iterable[Mapping[str, Any]],
    first_threshold_pct: float | None = None,
    estimated: bool = False,
) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    """Each capped run unit with a wrong cap, with its problem."""
    found = []
    for unit in units:
        problem = cap_problem(unit, first_threshold_pct, estimated)
        if problem is not None:
            found.append((unit, problem))
    return found


def message(problem: Mapping[str, Any]) -> str:
    """The text that tells the Coach what to write."""
    expected = problem["expected"]
    value = (
        f"{{percent_lthr: {percent_text(expected[PERCENT_KEY])}, "
        f"low_percent_lthr: {percent_text(expected[LOW_PERCENT_KEY])}, "
        f"source: {expected[SOURCE_KEY]}}}"
    )
    limit = percent_text(problem["limit_percent_lthr"])
    reason = {
        MISSING: "has no hr_cap",
        MALFORMED: "has a malformed hr_cap",
        TOO_HIGH: f"has an hr_cap above {limit} %",
        SOURCE_MISMATCH: f"has an hr_cap whose source is not {problem['cap_source']}",
        LOW_MISMATCH: "has an hr_cap whose lower bound does not belong to its percent",
    }[problem["reason"]]
    return (
        f"Run unit '{problem['focus']}' {reason}: write hr_cap {value} "
        f"(cap source {problem['cap_source']}). Percentages only; the bpm follows "
        "the athlete's current lactate threshold HR."
    )


def profile_run_caps(profile: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The cap value to store per capped type for the athlete's profile."""
    return effective_caps(
        first_threshold_percent(profile.get(FIRST_THRESHOLD_FIELD)),
        first_threshold_estimated(profile),
    )
