"""Grade-adjusted running speed from full-resolution streams (Minetti 2002).

Shared by the pace-at-heart-rate trend and the Pa:HR decoupling of the session
analysis (card M8). The grade of a sample is the stored grade stream, else the
altitude change over the next ``GRADE_SPAN_M`` metres of distance. No I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

GRADE_SPAN_M: Final = 200.0
# Validity range of the Minetti polynomial, as a fraction.
MAX_GRADE: Final = 0.45
# Minetti et al. (2002): metabolic cost of running (J/kg/m) at fractional grade.
_MINETTI: Final = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)
_LEVEL_COST: Final = _MINETTI[-1]


def _number(value: Any) -> float | None:
    return (
        float(value) if type(value) in {int, float} and math.isfinite(value) else None
    )


def grade_adjusted(speed: float, grade_pct: float) -> float:
    """Speed on level ground with the same metabolic cost."""
    grade = max(-MAX_GRADE, min(MAX_GRADE, grade_pct / 100))
    cost = 0.0
    for coefficient in _MINETTI:
        cost = cost * grade + coefficient
    return speed * cost / _LEVEL_COST if cost > 0 else speed


def _derived_grades(streams: Mapping[str, Any], count: int) -> list[float | None]:
    """Slope in % per sample from altitude over the next ``GRADE_SPAN_M`` metres."""
    altitude = [_number(value) for value in streams.get("altitude") or []]
    distance = [_number(value) for value in streams.get("distance") or []]
    grades: list[float | None] = [None] * count
    if len(altitude) != count or len(distance) != count:
        return grades
    end = 0
    for index, here in enumerate(distance):
        end = max(end, index)
        while end + 1 < count and (distance[end] or 0) - (here or 0) < GRADE_SPAN_M:
            end += 1
        ahead = distance[end]
        if None in (here, ahead, altitude[index], altitude[end]):
            continue
        run = ahead - here  # type: ignore[operator]
        if run >= GRADE_SPAN_M:
            grades[index] = 100 * (altitude[end] - altitude[index]) / run  # type: ignore[operator]
    return grades


def grade_stream(streams: Mapping[str, Any]) -> list[float | None] | None:
    """Grade in % per sample, or ``None`` without a grade or altitude stream."""
    times = streams.get("time") or []
    given = streams.get("grade_smooth") or []
    if len(given) == len(times) and any(_number(value) is not None for value in given):
        return [_number(value) for value in given]
    derived = _derived_grades(streams, len(times))
    return derived if any(value is not None for value in derived) else None


def grade_adjusted_speeds(
    streams: Mapping[str, Any], grades: list[float | None]
) -> list[float | None]:
    """Grade-adjusted ``velocity_smooth`` per sample; unknown where either is."""
    speeds = streams.get("velocity_smooth") or []
    adjusted: list[float | None] = []
    for raw, grade in zip(speeds, grades, strict=False):
        speed = _number(raw)
        adjusted.append(
            None if speed is None or grade is None else grade_adjusted(speed, grade)
        )
    return adjusted
