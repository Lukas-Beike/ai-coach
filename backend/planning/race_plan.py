"""Read-only race plan of one stored competition (athlete decision, #2803).

Sections come from course-profile lines such as ``km 8-11 +4 %`` or
``km 8-11 +120 Hm``; without a valid set the whole distance is one section.
Running splits the target time by equal effort with the Minetti et al. (2002)
grade cost (Abbiss and Laursen 2008: even effort is fastest). Cycling varies
power by 5 % around the target power on climbs and descents (Swain 1997;
Atkinson, Peacock and Passfield 2007). Carbohydrates come from the nutrition
fuelling rules. Only ``read_race_plan`` reads; nothing is stored.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from itertools import pairwise
from typing import Any, Final

from backend.canonical.vocabulary import Sport
from backend.nutrition import fuelling
from backend.performance.grade_adjustment import grade_adjusted

METHOD_VERSION: Final = 1
POWER_VARIATION_PCT: Final = 5
MAX_SECTIONS: Final = 50
# Section ends may differ by this much (km) from the next start or the distance.
_GAP_KM: Final = 0.05
_DISTANCE_TOLERANCE: Final = 0.02
_NUMBER = r"(\d+(?:[.,]\d+)?)"
_SECTION = re.compile(
    rf"km\s*{_NUMBER}\s*(?:-|–|—|bis)\s*(?:km\s*)?{_NUMBER}(.*)", re.IGNORECASE
)
# The first grade in % or climb in Hm after the range counts; a typed or
# autocorrected dash is a minus, and "1.200 Hm" is a thousands separator.
_SLOPE = re.compile(
    r"([+\-−–—]?)\s*(\d+(?:[.,]\d+)*)\s*(%|hm\b|höhenmeter\b)", re.IGNORECASE
)
# Sections end at a newline, a semicolon or a comma that starts the next "km".
_SECTION_BREAK = re.compile(r"[\n;]|,\s*(?=km)", re.IGNORECASE)
_HMS = re.compile(r"\b(\d{1,2}):([0-5]\d):([0-5]\d)\b")
_HM = re.compile(r"\b(\d{1,2}):([0-5]\d)\s*h\b", re.IGNORECASE)
_WATTS = re.compile(r"\b(\d{2,4})\s*(?:w|watt)\b", re.IGNORECASE)

def _float(text: str) -> float:
    return float(text.replace(",", "."))


def _section(line: str) -> dict[str, float] | None:
    found = _SECTION.search(line)
    if found is None:
        return None
    start, end, rest = _float(found[1]), _float(found[2]), found[3]
    if end <= start:
        return None
    grade = 0.0
    if slope := _SLOPE.search(rest):
        sign = -1 if slope[1] not in {"", "+"} else 1
        if slope[3] != "%":
            metres = float(re.sub(r"[.,]", "", slope[2]))
            grade = sign * metres / ((end - start) * 10)
        elif re.fullmatch(_NUMBER, slope[2]):
            grade = sign * _float(slope[2])
    return {"from_km": start, "to_km": end, "grade_pct": round(grade, 1)}


def course_sections(
    course_profile: Any, distance_km: float | None
) -> tuple[list[dict[str, float]], bool]:
    """Return the profile sections and whether lines were given but rejected."""
    lines = _SECTION_BREAK.split(str(course_profile or ""))
    sections = [found for line in lines if (found := _section(line)) is not None]
    if not sections:
        return [], False
    contiguous = abs(sections[0]["from_km"]) <= _GAP_KM and all(
        abs(after["from_km"] - before["to_km"]) <= _GAP_KM
        for before, after in pairwise(sections)
    )
    total = sections[-1]["to_km"]
    fits = distance_km is None or abs(total - distance_km) <= distance_km * (
        _DISTANCE_TOLERANCE
    )
    if not contiguous or not fits or len(sections) > MAX_SECTIONS:
        return [], True
    return sections, False


def target_seconds(target: Any) -> int | None:
    """The first ``h:mm:ss`` or ``h:mm h`` time in the free-text target."""
    text = str(target or "")
    if found := _HMS.search(text):
        return int(found[1]) * 3600 + int(found[2]) * 60 + int(found[3])
    if found := _HM.search(text):
        return int(found[1]) * 3600 + int(found[2]) * 60
    return None


def target_watts(target: Any) -> int | None:
    found = _WATTS.search(str(target or ""))
    return int(found[1]) if found else None


def distance_km(distance: Any) -> float | None:
    """Stored distances are metres (see ``competition_distance``)."""
    try:
        metres = float(str(distance or "").replace(",", "."))
    except ValueError:
        return None
    return metres / 1000 if metres > 0 else None


def _run_sections(
    sections: list[dict[str, float]], duration_s: int
) -> list[dict[str, Any]]:
    """Split ``duration_s`` so every section costs the same effort per metre.

    ``grade_adjusted(1, g)`` is the Minetti cost at grade ``g`` relative to
    level ground, so a section's time is proportional to its length times it.
    Times are rounded on the running total, so they add up to ``duration_s``.
    """
    weights = [
        (item["to_km"] - item["from_km"]) * grade_adjusted(1.0, item["grade_pct"])
        for item in sections
    ]
    total = sum(weights)
    result = []
    elapsed = 0.0
    for item, weight in zip(sections, weights, strict=True):
        seconds = duration_s * weight / total
        time_s = round(elapsed + seconds) - round(elapsed)
        elapsed += seconds
        length = item["to_km"] - item["from_km"]
        result.append(
            {**item, "time_s": time_s, "pace_s_per_km": round(seconds / length)}
        )
    return result


def _ride_sections(
    sections: list[dict[str, float]], watts: int | None
) -> list[dict[str, Any]]:
    result = []
    for item in sections:
        grade = item["grade_pct"]
        pct = POWER_VARIATION_PCT * ((grade > 0) - (grade < 0))
        power = None if watts is None else round(watts * (100 + pct) / 100)
        result.append({**item, "power_pct": pct, "power_w": power})
    return result


def _pacing(
    competition: dict[str, Any], duration: dict[str, Any] | None
) -> dict[str, Any]:
    sport = str(competition.get("sport") or "")
    known = distance_km(competition.get("distance"))
    sections, rejected = course_sections(competition.get("course_profile"), known)
    total = sections[-1]["to_km"] if sections else known
    if sport not in {Sport.RUN.value, Sport.RIDE.value}:
        return {"status": "unavailable", "reason": "sport"}
    if total is None:
        return {"status": "unavailable", "reason": "distance"}
    base = {
        "status": "ready",
        "sections_from": "course_profile" if sections else "even",
        "profile_rejected": rejected,
    }
    sections = sections or [{"from_km": 0.0, "to_km": total, "grade_pct": 0.0}]
    if sport == Sport.RIDE.value:
        watts = target_watts(competition.get("target"))
        return {
            **base,
            "method": "power_variation",
            "target_w": watts,
            "sections": _ride_sections(sections, watts),
        }
    if duration is None:
        return {"status": "unavailable", "reason": "duration"}
    return {
        **base,
        "method": "equal_effort",
        "sections": _run_sections(sections, duration["seconds"]),
    }


def _duration(competition: dict[str, Any]) -> dict[str, Any] | None:
    if (seconds := target_seconds(competition.get("target"))) is not None:
        return {"seconds": seconds, "source": "target"}
    planned = competition.get("planned_duration_s")
    if isinstance(planned, int) and not isinstance(planned, bool) and planned > 0:
        return {"seconds": planned, "source": "planned_duration"}
    return None


def read_race_plan(
    competition_service: Callable[[], Any],
    body_weight: Callable[[], dict[str, Any] | None],
    competition_id: str,
) -> dict[str, Any] | None:
    """The race plan of a stored competition, or None for an unknown id.

    ``body_weight`` is the nutrition owner's resolved weight with its source.
    """
    competition = competition_service().get(competition_id)
    if competition is None:
        return None
    return race_plan(competition, body_weight())


def race_plan(
    competition: dict[str, Any], weight: dict[str, Any] | None
) -> dict[str, Any]:
    """The race plan of one competition; ``weight`` is ``{value, source}``."""
    duration = _duration(competition)
    seconds = None if duration is None else duration["seconds"]
    weight_kg = None if not weight else weight.get("value")
    if (
        isinstance(weight_kg, bool)
        or not isinstance(weight_kg, (int, float))
        or weight_kg <= 0
    ):
        weight_kg = None
    return {
        "competition_id": str(competition.get("id") or ""),
        "method_version": METHOD_VERSION,
        "duration": duration,
        "pacing": _pacing(competition, duration),
        "carbohydrates": {
            "source": fuelling.POSITION_STAND,
            "during": fuelling.carbohydrate_per_hour(seconds),
            "before": fuelling.pre_race_carbohydrates(seconds, weight_kg),
            "weight": None
            if weight_kg is None
            else {"kg": weight_kg, "source": (weight or {}).get("source")},
        },
    }
