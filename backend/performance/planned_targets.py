"""Each executed work lap against its planned step's target.

The n-th executed work lap of ``session_execution`` is compared with the n-th
planned work step of the matched local planned unit; no duration match is
required. Work steps are the planned steps within 10 % of the hardest target,
each as a fraction of its threshold. Targets come
from the athlete's current thresholds as the planned-workout estimate reads
them, so zone, percent, absolute and pace targets all count; ramps stay
unscored. Time in target reads the session's displayed streams. Descriptive
only: no score, no threshold change. Pure: no I/O, inputs unchanged.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from typing import Any, Final

from backend.activities.workout_load import (
    AthleteThresholds,
    TargetRange,
    step_target_range,
)
from backend.activities.zone_settings import LTHR_SHARE_OF_MAX_HR
from backend.canonical.vocabulary import Sport

METHOD: Final = "planned-target-execution-v1"
SCOPE: Final = (
    "The n-th executed work lap against the n-th planned work step, from the "
    "athlete's current thresholds. deviation_pct is 0 inside the target, else "
    "the distance to the nearer bound on speed, power or heart rate in percent "
    "(positive: faster, more power or higher heart rate). Heart-rate targets "
    "use the second half of the lap. time_in_target_pct comes from the "
    "displayed streams. Single-value targets count as plus or minus 2.5 %."
)
# Work steps are within this share of the hardest planned target.
WORK_SHARE: Final = 0.10
_STREAM_KEYS: Final = {
    "speed": "speed_mps",
    "watts": "power_w",
    "heartrate": "heart_rate_bpm",
}


def planned_target_execution(
    execution: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    thresholds: AthleteThresholds,
    sport: str,
    *,
    planned_unit_id: str | None = None,
    streams: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the session's work laps with the planned unit's work steps."""
    base = {"method": METHOD, "scope": SCOPE, "planned_unit_id": planned_unit_id}
    if execution.get("status") != "ok":
        return {**base, "status": "not_covered", "reason": "Ausführung unbekannt."}
    if execution.get("structure") != "interval":
        return {
            **base,
            "status": "not_covered",
            "reason": "Keine Intervalle in der Aufzeichnung erkannt.",
        }
    try:
        canonical_sport = Sport(sport)
    except ValueError:
        return {**base, "status": "not_covered", "reason": "Sportart unbekannt."}
    ranges = [step_target_range(step, thresholds, canonical_sport) for step in steps]
    work = _work_steps(ranges, thresholds)
    if not work:
        reasons = sorted({r.unknown for r in ranges if r.unknown})
        return {
            **base,
            "status": "not_covered",
            "reason": "Keine auswertbaren Zielschritte im Plan.",
            "unknown_targets": reasons,
        }
    reps = list(execution.get("reps") or [])
    recoveries = {
        item.get("after_rep"): item for item in execution.get("recoveries") or []
    }
    timeline = _Timeline(streams)
    compared = []
    for number, (index, rep) in enumerate(zip(work, reps, strict=False), start=1):
        step, target = steps[index], ranges[index]
        item = _compare(rep, step, target, execution, timeline)
        planned_rest = _planned_rest(steps, work, index)
        actual_rest = recoveries.get(number)
        if planned_rest is not None:
            item["planned_recovery_s"] = round(planned_rest)
        if actual_rest is not None:
            item["recovery_s"] = actual_rest.get("duration_s")
        compared.append(item)
    summary = {
        "planned_work_steps": len(work),
        "executed_work_laps": len(reps),
        "compared": len(compared),
        "in_target": sum(item.get("deviation_pct") == 0 for item in compared),
        "above_target": sum((item.get("deviation_pct") or 0) > 0 for item in compared),
        "below_target": sum((item.get("deviation_pct") or 0) < 0 for item in compared),
    }
    return {**base, "status": "ok", "reps": compared, "summary": summary}


def _work_steps(
    ranges: Sequence[TargetRange], thresholds: AthleteThresholds
) -> list[int]:
    """Indexes of the planned work steps: within 10 % of the hardest target.

    Every target is compared as a fraction of its threshold (speed over
    threshold speed, watts over FTP, bpm over LTHR), so pace and heart-rate
    steps of one plan share a scale.
    """
    references = {
        "speed": thresholds.threshold_speed_mps,
        "watts": thresholds.zones.ftp,
        "heartrate": thresholds.zones.lthr
        or (thresholds.zones.max_hr or 0) * LTHR_SHARE_OF_MAX_HR,
    }
    levels = []
    for index, target in enumerate(ranges):
        reference = references.get(target.metric or "")
        if target.low is None or target.high is None or not reference:
            continue
        levels.append((index, (target.low + target.high) / 2 / reference))
    if not levels:
        return []
    hardest = max(level for _, level in levels)
    return [index for index, level in levels if level >= hardest * (1 - WORK_SHARE)]


def _planned_rest(
    steps: Sequence[Mapping[str, Any]], work: Sequence[int], index: int
) -> float | None:
    """Planned duration between this work step and the next one."""
    position = work.index(index)
    if position + 1 >= len(work):
        return None
    between = steps[index + 1 : work[position + 1]]
    durations = [step.get("duration") for step in between]
    numbers = [float(value) for value in durations if isinstance(value, (int, float))]
    if not between or len(numbers) != len(durations):
        return None
    return sum(numbers)


def _compare(
    rep: Mapping[str, Any],
    step: Mapping[str, Any],
    target: TargetRange,
    execution: Mapping[str, Any],
    timeline: _Timeline,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "rep": rep.get("rep"),
        "planned_target": str(step.get("target") or ""),
        "duration_s": rep.get("duration_s"),
    }
    if isinstance(step.get("duration"), (int, float)):
        item["planned_duration_s"] = round(float(step["duration"]))
    if isinstance(step.get("distance"), (int, float)):
        item["planned_distance_m"] = round(float(step["distance"]))
        if rep.get("distance_m") is not None:
            item["distance_m"] = rep.get("distance_m")
    if target.metric is None or target.low is None or target.high is None:
        item["target_unknown"] = target.unknown
        return item
    item.update(_shown_range(target, execution))
    actual = _actual(rep, target.metric, execution)
    if actual is None:
        item["target_unknown"] = "missing_measurement"
        return item
    item["deviation_pct"] = _deviation(actual, target.low, target.high)
    start, duration = rep.get("start_s"), rep.get("duration_s")
    if isinstance(start, (int, float)) and isinstance(duration, (int, float)):
        share = timeline.share_inside(
            target.metric,
            float(start),
            float(start + duration),
            target.low,
            target.high,
        )
        if share is not None:
            item["time_in_target_pct"] = share
    return item


def _shown_range(target: TargetRange, execution: Mapping[str, Any]) -> dict[str, Any]:
    low, high = float(target.low or 0), float(target.high or 0)
    if target.metric == "speed" and execution.get("output") == "pace":
        return {
            "target_pace_s_per_km": [
                round(1000 / high),
                round(1000 / low) if low else None,
            ]
        }
    if target.metric == "speed":
        return {"target_kmh": [round(low * 3.6, 1), round(high * 3.6, 1)]}
    if target.metric == "watts":
        return {"target_watts": [round(low), round(high)]}
    return {"target_bpm": [round(low), round(high)]}


def _actual(
    rep: Mapping[str, Any], metric: str, execution: Mapping[str, Any]
) -> float | None:
    """The rep's measured value on the target's metric."""
    if metric == "heartrate":
        value = rep.get("heart_rate_second_half") or rep.get("heart_rate_avg")
        return float(value) if isinstance(value, (int, float)) else None
    output = rep.get("output")
    if not isinstance(output, (int, float)) or output <= 0:
        return None
    shown = execution.get("output")
    if metric == "watts":
        return float(output) if shown == "power" else None
    if shown == "pace":
        return 1000.0 / float(output)
    if shown == "speed":
        return float(output) / 3.6
    return None


def _deviation(actual: float, low: float, high: float) -> float:
    if low <= actual <= high:
        return 0.0
    bound = high if actual > high else low
    if bound <= 0:
        return 0.0
    return round((actual - bound) / bound * 100, 1)


class _Timeline:
    """Displayed streams of the session, for the share of time inside a target."""

    def __init__(self, streams: Mapping[str, Any] | None) -> None:
        streams = streams if isinstance(streams, Mapping) else {}
        times = streams.get("time_s")
        self._times = list(times) if isinstance(times, list) else []
        channels = streams.get("channels")
        self._channels = channels if isinstance(channels, Mapping) else {}

    def share_inside(
        self, metric: str, start: float, end: float, low: float, high: float
    ) -> float | None:
        channel = self._channels.get(_STREAM_KEYS[metric])
        values = channel.get("values") if isinstance(channel, Mapping) else None
        if not isinstance(values, list) or len(values) != len(self._times):
            return None
        first = bisect.bisect_left(self._times, start)
        last = bisect.bisect_right(self._times, end)
        inside = total = 0.0
        for index in range(first, min(last, len(self._times) - 1)):
            value, left, right = (
                values[index],
                self._times[index],
                self._times[index + 1],
            )
            if not isinstance(value, (int, float)) or not isinstance(
                left, (int, float)
            ):
                continue
            if not isinstance(right, (int, float)) or right <= left:
                continue
            span = min(right, end) - max(left, start)
            if span <= 0:
                continue
            total += span
            inside += span if low <= value <= high else 0.0
        return round(inside / total * 100) if total > 0 else None
