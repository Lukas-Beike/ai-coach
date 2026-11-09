"""Each executed work lap against its planned step's target.

The executed work laps of ``session_execution`` are paired in order with the
planned work steps of the matched local planned unit; no duration match is
required. Work steps are chosen so their count fits the executed laps when the
plan allows it (the hardest steps, else the steps within 10 % of the hardest
target, each as a fraction of its threshold). Targets come from the athlete's
current thresholds as the planned-workout estimate reads them, so zone,
percent, absolute and pace targets all count; ramps stay unscored. Time in
target reads the session's displayed streams. Descriptive only: no score, no
threshold change. Pure: no I/O, inputs unchanged.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from typing import Any, Final

from backend.activities.hr_cap import (
    PERCENT_KEY,
    SOURCE_KEY,
    cap_label,
    resolve_bpm,
)
from backend.activities.workout_load import (
    AthleteThresholds,
    TargetRange,
    hr_reference,
    step_target_range,
)
from backend.canonical.vocabulary import Sport

METHOD: Final = "planned-target-execution-v1"
SCOPE: Final = (
    "Executed work laps against the planned work steps in order, from the "
    "athlete's current thresholds; for an older session the planned targets may "
    "have rested on other thresholds. deviation_pct is 0 inside the target, else "
    "the distance to the nearer bound on speed, power or heart rate in percent "
    "(positive: faster, more power or higher heart rate). Heart-rate targets use "
    "the second half of the lap and are not scored for laps under 120 s. "
    "time_in_target_pct comes from the displayed streams. Single-value targets "
    "count as plus or minus 2.5 %; the top zone is open upwards."
)
# Work steps are within this share of the hardest planned target.
WORK_SHARE: Final = 0.10
# A step count fits the executed laps only when the next easier step is
# clearly easier than the easiest chosen one.
COUNT_GAP_SHARE: Final = 0.10
# Display samples further apart than this are a pause, not part of the lap.
MAX_DISPLAY_GAP_S: Final = 15.0
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
    reps = list(execution.get("reps") or [])
    # The real lap count, not the listed reps (at most 40).
    counted = (execution.get("rep_summary") or {}).get("rep_count")
    executed = counted if isinstance(counted, int) else len(reps)
    work = _work_steps(_levels(ranges, thresholds), executed)
    if not work:
        reasons = sorted({r.unknown for r in ranges if r.unknown})
        return {
            **base,
            "status": "not_covered",
            "reason": "Keine auswertbaren Zielschritte im Plan.",
            "unknown_targets": reasons,
        }
    recoveries = {
        item.get("after_rep"): item for item in execution.get("recoveries") or []
    }
    timeline = _Timeline(streams)
    compared = []
    for number, (index, rep) in enumerate(zip(work, reps, strict=False), start=1):
        item = _compare(rep, steps[index], ranges[index], execution, timeline)
        planned_rest = _planned_rest(steps, work, index)
        actual_rest = recoveries.get(number)
        if planned_rest is not None:
            item["planned_recovery_s"] = round(planned_rest)
        if actual_rest is not None:
            item["recovery_s"] = actual_rest.get("duration_s")
        compared.append(item)
    deviations = [item["deviation_pct"] for item in compared if "deviation_pct" in item]
    summary = {
        "planned_work_steps": len(work),
        "executed_work_laps": executed,
        "compared": len(compared),
        "in_target": sum(value == 0 for value in deviations),
        "above_target": sum(value > 0 for value in deviations),
        "below_target": sum(value < 0 for value in deviations),
    }
    return {**base, "status": "ok", "reps": compared, "summary": summary}


HR_CAP_METHOD: Final = "heart-rate-cap-execution-v1"
# More than this share of the time above the cap, or a mean above it, is above the cap.
CAP_ABOVE_SHARE_PCT: Final = 10
# A mean this close below the cap (share of the cap) sits at the upper edge.
CAP_EDGE_SHARE: Final = 0.05


def heart_rate_cap_execution(
    cap: Mapping[str, Any], lthr: float | None, streams: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The whole session's heart rate against the unit's stored cap.

    The cap is stored in percent of the threshold HR; ``lthr`` is the threshold
    HR in effect on the unit's date and resolves it to bpm. Descriptive: the
    verdict is ``above_cap`` (mean above the cap or more than
    ``CAP_ABOVE_SHARE_PCT`` of the time above it), ``upper_edge`` (the mean
    within ``CAP_EDGE_SHARE`` below it) or ``within_target``. Judged against the
    stored cap, not the zones. Pure.
    """
    percent = float(cap[PERCENT_KEY])
    bpm = resolve_bpm(percent, lthr)
    base: dict[str, Any] = {
        "method": HR_CAP_METHOD,
        "cap_percent_lthr": percent,
        "cap_source": cap[SOURCE_KEY],
        "cap_label": cap_label(cap, lthr),
    }
    if bpm is None:
        return {
            **base,
            "status": "not_covered",
            "reason": "Laktatschwelle (LSHF) unbekannt: Die Obergrenze lässt sich nicht in bpm umrechnen.",
        }
    base["cap_bpm"] = bpm
    timeline = _Timeline(streams)
    spans = timeline.spans("heartrate", float("-inf"), float("inf"))
    total = sum(span for _, span in spans)
    if total <= 0:
        return {**base, "status": "not_covered", "reason": "Kein Herzfrequenzverlauf."}
    mean = sum(value * span for value, span in spans) / total
    above = sum(span for value, span in spans if value > bpm) / total * 100
    if mean > bpm or above > CAP_ABOVE_SHARE_PCT:
        verdict = "above_cap"
    elif mean >= bpm * (1 - CAP_EDGE_SHARE):
        verdict = "upper_edge"
    else:
        verdict = "within_target"
    return {
        **base,
        "status": "ok",
        "mean_bpm": round(mean),
        "mean_percent_of_cap": round(mean / bpm * 100),
        "time_above_cap_pct": round(above),
        "verdict": verdict,
    }


def _levels(
    ranges: Sequence[TargetRange], thresholds: AthleteThresholds
) -> list[tuple[int, float]]:
    """Each resolved step's target level as a fraction of its threshold.

    Pace targets without a threshold pace are scaled by the fastest pace target,
    so a plan of absolute paces still has levels.
    """
    speeds = [r.low for r in ranges if r.metric == "speed" and r.low]
    references = {
        "speed": thresholds.threshold_speed_mps or (max(speeds) if speeds else None),
        "watts": thresholds.zones.ftp,
        "heartrate": hr_reference(thresholds.zones),
    }
    levels = []
    for index, target in enumerate(ranges):
        reference = references.get(target.metric or "")
        if target.low is None or target.high is None or not reference:
            continue
        # The open top zone counts from its lower bound.
        middle = (
            target.low if math.isinf(target.high) else (target.low + target.high) / 2
        )
        levels.append((index, middle / reference))
    return levels


def _work_steps(levels: Sequence[tuple[int, float]], executed: int) -> list[int]:
    """Planned work steps in plan order, fitted to the executed lap count."""
    if not levels:
        return []
    ordered = sorted(levels, key=lambda item: item[1], reverse=True)
    if 0 < executed < len(ordered):
        chosen, following = ordered[executed - 1][1], ordered[executed][1]
        if following < chosen * (1 - COUNT_GAP_SHARE):
            return sorted(index for index, _ in ordered[:executed])
    hardest = ordered[0][1]
    return sorted(
        index for index, level in levels if level >= hardest * (1 - WORK_SHARE)
    )


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
    if target.metric == "heartrate" and rep.get("short"):
        item["target_unknown"] = "short_rep_heart_rate"
        return item
    window = _window(rep, target.metric)
    actual = _actual(rep, target.metric, execution)
    if actual is None and target.metric == "speed" and window is not None:
        # A ride shown in watts still has its speed in the displayed streams.
        actual = timeline.mean("speed", *window)
    if actual is None:
        item["target_unknown"] = "missing_measurement"
        return item
    item["deviation_pct"] = _deviation(actual, target.low, target.high)
    if window is not None:
        share = timeline.share_inside(target.metric, *window, target.low, target.high)
        if share is not None:
            item["time_in_target_pct"] = share
    return item


def _window(rep: Mapping[str, Any], metric: str) -> tuple[float, float] | None:
    """The rep's time window; heart rate is read over its second half only."""
    start, duration = rep.get("start_s"), rep.get("duration_s")
    if not isinstance(start, (int, float)) or not isinstance(duration, (int, float)):
        return None
    first = float(start) + (float(duration) / 2 if metric == "heartrate" else 0.0)
    return first, float(start) + float(duration)


def _shown_range(target: TargetRange, execution: Mapping[str, Any]) -> dict[str, Any]:
    """Target bounds in the units the athlete reads; ``None`` for an open bound."""
    low, high = float(target.low or 0), float(target.high or 0)
    upper = high if math.isfinite(high) else None
    if target.metric == "speed" and execution.get("output") == "pace":
        fastest = round(1000 / upper) if upper else None
        slowest = round(1000 / low) if low else None
        return {"target_pace_s_per_km": [fastest, slowest]}
    if target.metric == "speed":
        return {
            "target_kmh": [
                round(low * 3.6, 1),
                None if upper is None else round(upper * 3.6, 1),
            ]
        }
    key = "target_watts" if target.metric == "watts" else "target_bpm"
    return {key: [round(low), None if upper is None else round(upper)]}


def _actual(
    rep: Mapping[str, Any], metric: str, execution: Mapping[str, Any]
) -> float | None:
    """The rep's measured value on the target's metric."""
    if metric == "heartrate":
        # Heart rate lags; without its second half the rep stays unscored.
        value = rep.get("heart_rate_second_half")
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
        spans = self._spans(metric, start, end)
        total = sum(span for _, span in spans)
        inside = sum(span for value, span in spans if low <= value <= high)
        return round(inside / total * 100) if total > 0 else None

    def spans(self, metric: str, start: float, end: float) -> list[tuple[float, float]]:
        """Each displayed value with the time it covers inside the window."""
        return self._spans(metric, start, end)

    def mean(self, metric: str, start: float, end: float) -> float | None:
        spans = self._spans(metric, start, end)
        total = sum(span for _, span in spans)
        return sum(value * span for value, span in spans) / total if total > 0 else None

    def _spans(
        self, metric: str, start: float, end: float
    ) -> list[tuple[float, float]]:
        """Each displayed value with the time it covers inside the window."""
        channel = self._channels.get(_STREAM_KEYS[metric])
        values = channel.get("values") if isinstance(channel, Mapping) else None
        times = self._times
        if not isinstance(values, list) or len(values) != len(times) or not times:
            return []
        # The sample interval that straddles the lap start counts in part.
        first = max(0, bisect.bisect_right(times, start) - 1)
        last = bisect.bisect_left(times, end)
        spans = []
        for index in range(first, min(last, len(times) - 1)):
            value, left, right = values[index], times[index], times[index + 1]
            if not all(isinstance(item, (int, float)) for item in (value, left, right)):
                continue
            if not 0 < right - left <= MAX_DISPLAY_GAP_S:
                continue
            span = min(right, end) - max(left, start)
            if span > 0:
                spans.append((float(value), span))
        return spans
