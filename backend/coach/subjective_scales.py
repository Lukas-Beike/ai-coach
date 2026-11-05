"""The scale, direction and source of each subjective rating the Coach reads.

Ratings keep the number the athlete entered. This legend names, per context
section and field, which scale that number is on, so same-named ratings of
different scales, such as Intervals.icu soreness 1-4 and check-in soreness 0-10,
are never read as comparable numbers.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

from backend.canonical.rating_scales import (
    INTERVALS_FEEL_SCALE,
    INTERVALS_RPE_SCALE,
    INTERVALS_WELLNESS_SCALES,
    LOCAL_CHECKIN_SCALES,
    LOCAL_SESSION_RPE_SCALE,
)
from backend.canonical.vocabulary import ProviderId
from backend.performance.context import SUBJECTIVE_RATINGS
from backend.providers.source_labels import SourceView, provider_label

CHECKIN_SOURCE: Final = "Lokales Check-in, Athleteneingabe"
FEEDBACK_SOURCE: Final = "Lokale Aktivitätsrückmeldung, Athleteneingabe"
# The daily view repeats the check-in and feedback ratings of their own sections.
_DAILY_SCALES: Final = {
    "checkin": "Skalen wie local_feedback",
    "activity_feedback": "Skalen wie activity_feedback",
}


def _intervals_source() -> str:
    label = provider_label(ProviderId.INTERVALS, SourceView.CURRENT_METRIC)
    return f"{label}, Athleteneingabe"


def activity_scales() -> dict[str, str]:
    """The source and scales of an activity summary's ``rpe`` and ``feel``."""
    return {
        "source": _intervals_source(),
        "rpe": INTERVALS_RPE_SCALE.describe(),
        "feel": INTERVALS_FEEL_SCALE.describe(),
    }


def feedback_scales() -> dict[str, str]:
    """The source and scale of the local activity feedback ``session_rpe``."""
    return {
        "source": FEEDBACK_SOURCE,
        "session_rpe": LOCAL_SESSION_RPE_SCALE.describe(),
    }


def _section_scales(section: str) -> dict[str, Any]:
    if section == "current_performance":
        recovery = {
            key: INTERVALS_WELLNESS_SCALES[kind].describe()
            for key, kind in SUBJECTIVE_RATINGS
        }
        return {"recovery": {"source": _intervals_source(), **recovery}}
    if section == "activities":
        return dict(activity_scales())
    if section == "local_feedback":
        checkin = {key: scale.describe() for key, scale in LOCAL_CHECKIN_SCALES.items()}
        return {"source": CHECKIN_SOURCE, **checkin}
    if section == "activity_feedback":
        return dict(feedback_scales())
    if section == "daily_planning_context":
        return dict(_DAILY_SCALES)
    return {}


def subjective_scales(sections: Iterable[str]) -> dict[str, Any]:
    """The rating scales of the given context sections that carry ratings.

    The daily view refers to the check-in and feedback scales, so they come along.
    """
    named = set(sections)
    if "daily_planning_context" in named:
        named |= {"local_feedback", "activity_feedback"}
    scales = {section: _section_scales(section) for section in sorted(named)}
    return {section: value for section, value in scales.items() if value}
