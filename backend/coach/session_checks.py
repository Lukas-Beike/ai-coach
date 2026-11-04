"""Facts the session analysis checks beside the recording: focus, pace, strength.

Each block is bounded and names its source; unknown or insufficient data is
``unknown`` or ``not_covered`` with a reason, never zero. Planned units are
local records; their text is data, so only ids and focus values are returned.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.planning.session_focus import session_focus
from backend.planning.sport import planned_sport_environment

LOCAL_PLAN = "local planned unit"
TEST_EVALUATION = (
    "Judge the execution first (even pacing, too fast a start, stopped early), "
    "then compare with the previous test of the same protocol: find it with "
    "list_recent_activities and read it with get_activity_details; without one "
    "say there is no comparison. Critical-speed test: each effort's time, "
    "distance and pace against the last test; power_profiles critical_power is a "
    "separate 28-day estimate, not this test's result. Ramp test: the best 1-min "
    "power in analysis.power_profile, even when erg_like; Zwift's FTP is about "
    "75 % of it, a self-comparison. 30-min time trial: pace and average heart "
    "rate of the last 20 min as a threshold estimate (McGehee 2005). Control "
    "run: pace at the fixed heart rate against earlier control runs, with "
    "temperature. Recommend updating FTP, threshold pace or zones in "
    "Intervals.icu or Garmin only from a sound test; never write them."
)


def matched_focus(
    session: Mapping[str, Any], units: Sequence[Mapping[str, Any]] | None
) -> dict[str, Any]:
    """Focus of the one planned unit of the session's day and sport, else unknown."""
    if units is None:
        return _unknown("Geplante Einheiten nicht verfügbar.")
    day, sport = iso_date_prefix(session.get("started_at_local")), session.get("sport")
    same = [
        unit
        for unit in units
        if iso_date_prefix(unit.get("date")) == day
        and planned_sport_environment(unit)[0].value == sport
    ]
    if len(same) != 1:
        return _unknown(
            "Keine geplante Einheit dieses Tages und Sports."
            if not same
            else "Mehrere geplante Einheiten dieses Tages und Sports."
        )
    focus = session_focus(same[0])
    if focus.value is None:
        return _unknown("Die geplante Einheit hat kein Ziel.")
    matched = {
        "status": "matched",
        "session_focus": focus.value,
        "origin": focus.origin,
        "planned_unit_id": same[0].get("id"),
        "source": LOCAL_PLAN,
    }
    # A test carries its own evaluation, so other analyses do not pay for it.
    return (
        {**matched, "test_evaluation": TEST_EVALUATION}
        if focus.value == "test"
        else matched
    )


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "unknown", "reason": reason}
