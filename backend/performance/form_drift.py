"""Running form drift of a long steady run (#1870).

Compares the first and the last third of one run at a similar pace: the change
of ground contact time, vertical oscillation and step length. A contact time that
rose by at least ``CONTACT_TIME_RISE_PCT`` flags the run as "Laufstil lässt nach".

The thresholds are heuristics chosen for this app, not validated cut-offs, and
the analysis is no injury-risk score. The input is the legacy-shaped activity
dict of ``analysis_input``; absent running dynamics are normal and give an
``insufficient_data`` result, never an error. No I/O.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from typing import Any, Final

# Bump when the computation changes, so stored analyses recompute.
METHOD_VERSION: Final = 1
METHOD: Final = "running-form-drift-v1"
FLAG_LABEL: Final = "Laufstil lässt nach"
# A run shorter than this has no third long enough to compare (45 minutes).
MIN_DURATION_S: Final = 2700.0
# The speed of the two thirds may differ by at most this share.
PACE_TOLERANCE: Final = 0.05
# Each third needs measured time of at least this share of its length.
MIN_COVERAGE: Final = 0.5
# A sample gap longer than this splits the series (seconds), as for the other analyses.
MAX_GAP_S: Final = 5.0
# Heuristic thresholds in percent of the first third.
CONTACT_TIME_RISE_PCT: Final = 5.0
OSCILLATION_RISE_PCT: Final = 10.0
STEP_LENGTH_FALL_PCT: Final = 5.0
# (metric, stream key, unit, direction of the worsening, threshold in percent)
_METRICS: Final[tuple[tuple[str, str, str, int, float], ...]] = (
    ("contact_time", "ground_contact_time", "ms", 1, CONTACT_TIME_RISE_PCT),
    ("vertical_oscillation", "vertical_oscillation", "cm", 1, OSCILLATION_RISE_PCT),
    ("step_length", "step_length", "m", -1, STEP_LENGTH_FALL_PCT),
)
_SPEED_KEY: Final = "velocity_smooth"
_INTERPRETATION: Final = "The thresholds (contact time +5 %, vertical oscillation +10 %, step length -5 %) are heuristics of this app, not validated cut-offs, and no injury-risk score. Only a rise of the contact time flags the run. Hills, surface and sensor placement can change the values."

type _Window = tuple[float, float]


def form_drift(
    activity: Mapping[str, Any], *, source_label: str
) -> dict[str, Any] | None:
    """The form drift of one run, the reason why there is none, or None.

    Sports other than non-trail runs have no form drift: None, so their stored
    analysis does not carry the key. The method text is part of the result only
    when the drift was computed.
    """
    if activity.get("sport") != "run" or activity.get("trail"):
        return None
    reason = _ineligible(activity)
    if reason is not None:
        return _insufficient(reason)
    streams = activity["streams"]
    times = [float(value) for value in streams["time"]]
    span = times[-1] - times[0]
    first, last = (times[0], times[0] + span / 3), (times[-1] - span / 3, times[-1])
    speeds = _thirds(times, streams, _SPEED_KEY, first, last)
    if speeds is None:
        return _insufficient(
            "Das Tempo ist im ersten oder letzten Drittel nicht ausreichend gemessen."
        )
    pace_change = 100 * (speeds[1] / speeds[0] - 1)
    if abs(pace_change) > 100 * PACE_TOLERANCE:
        return _insufficient(
            "Das Tempo des ersten und letzten Drittels ist nicht vergleichbar."
        )
    metrics = _metrics(times, streams, first, last)
    if not metrics:
        return _insufficient("Laufdynamik fehlt im ersten oder letzten Drittel.")
    flagged = bool(metrics.get("contact_time", {}).get("exceeds"))
    return {
        "method": METHOD,
        "source": f"derived from {source_label} original streams",
        "status": "ok",
        "third_seconds": round(span / 3, 1),
        "pace_change_percent": round(pace_change, 2),
        "metrics": metrics,
        "flagged": flagged,
        "label": FLAG_LABEL if flagged else None,
        "interpretation": _INTERPRETATION,
    }


def _insufficient(reason: str) -> dict[str, Any]:
    return {"method": METHOD, "status": "insufficient_data", "reason": reason}


def _ineligible(activity: Mapping[str, Any]) -> str | None:
    """Why the run cannot be analysed, or None when it can."""
    streams = activity.get("streams") or {}
    if not any(key in streams for _, key, _, _, _ in _METRICS):
        return "Keine Laufdynamik aufgezeichnet."
    times = streams.get("time") or []
    if len(times) < 2 or float(times[-1]) - float(times[0]) < MIN_DURATION_S:
        return "Die Einheit ist kürzer als 45 Minuten."
    return None


def _metrics(
    times: Sequence[float],
    streams: Mapping[str, Any],
    first: _Window,
    last: _Window,
) -> dict[str, dict[str, Any]]:
    """The change of each metric that both thirds measured."""
    metrics: dict[str, dict[str, Any]] = {}
    for name, key, unit, direction, threshold in _METRICS:
        means = _thirds(times, streams, key, first, last)
        if means is None:
            continue
        change = 100 * (means[1] / means[0] - 1)
        metrics[name] = {
            "first": round(means[0], 3),
            "last": round(means[1], 3),
            "unit": unit,
            "change_percent": round(change, 2),
            "threshold_percent": threshold,
            "exceeds": direction * change >= threshold,
        }
    return metrics


def _thirds(
    times: Sequence[float],
    streams: Mapping[str, Any],
    key: str,
    first: _Window,
    last: _Window,
) -> tuple[float, float] | None:
    """The time-weighted means of a positive channel in both windows, if covered."""
    means = []
    for start, end in (first, last):
        covered, total = _weighted(times, streams, key, start, end)
        if covered < MIN_COVERAGE * (end - start) or total <= 0:
            return None
        means.append(total / covered)
    return means[0], means[1]


def _weighted(
    times: Sequence[float],
    streams: Mapping[str, Any],
    key: str,
    start: float,
    end: float,
) -> tuple[float, float]:
    """Covered seconds and the sum of value times seconds of the moving samples.

    Only the sample intervals that overlap the window are visited.
    """
    values: Sequence[Any] = streams.get(key) or []
    moving: Sequence[Any] | None = streams.get("moving")
    covered = total = 0.0
    if len(values) != len(times):
        return covered, total
    low = max(bisect_right(times, start) - 1, 0)
    high = min(bisect_left(times, end), len(times) - 1)
    for index in range(low, high):
        weight = min(times[index + 1], end) - max(times[index], start)
        value = values[index]
        if (
            weight <= 0
            or times[index + 1] - times[index] > MAX_GAP_S
            or not _is_positive(value)
            or (moving and (index >= len(moving) or moving[index] is not True))
        ):
            continue
        covered += weight
        total += weight * float(value)
    return covered, total


def _is_positive(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )
