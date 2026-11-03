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
    return {
        "status": "matched",
        "session_focus": focus.value,
        "origin": focus.origin,
        "planned_unit_id": same[0].get("id"),
        "source": LOCAL_PLAN,
    }


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "unknown", "reason": reason}
