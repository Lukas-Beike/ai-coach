"""Each executed work lap against its planned step's target.

The executed work laps of ``session_execution`` are paired in order with the
planned work steps of the matched local planned unit; no duration match is
required. Work steps are chosen so their count fits the executed laps when the
plan allows it (the hardest steps, else the steps within 10 % of the hardest
target, each as a fraction of its threshold). Targets come from the athlete's
current thresholds as the planned-workout estimate reads them, so zone,
percent, absolute and pace targets all count; ramps stay unscored. Time in
target reads the session's displayed streams. The laps' comparison is
descriptive; ``planned_step_adherence`` scores every planned step and the
session by their time in target for the calendar's session details (#2830). No
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
    TargetRange,
    ZoneSettings,
    hr_reference,
    step_target_range,
)
from backend.activities.workout_text import WorkoutTextError, structured_steps
from backend.canonical.vocabulary import Sport
from backend.performance.session_execution import SHORT_REP_S

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
# Longer workout texts are not parsed for the comparison.
MAX_DESCRIPTION_CHARS: Final = 20000
_STREAM_KEYS: Final = {
    "speed": "speed_mps",
    "watts": "power_w",
    "heartrate": "heart_rate_bpm",
}


def planned_target_execution(
    execution: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    thresholds: ZoneSettings,
    sport: str,
    *,
    planned_unit_id: str | None = None,
    streams: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the session's work laps with the planned unit's work steps."""
    base = {"method": METHOD, "scope": SCOPE, "planned_unit_id": planned_unit_id}
    paired = _paired(execution, steps, thresholds, sport)
    if isinstance(paired, dict):
        return {**base, **paired}
    ranges, reps, executed, work = paired
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


def _paired(
    execution: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    thresholds: ZoneSettings,
    sport: str,
) -> tuple[list[TargetRange], list[Any], int, list[int]] | dict[str, Any]:
    """Step ranges, listed reps, real lap count and work steps, or why not."""
    if execution.get("status") != "ok":
        return {"status": "not_covered", "reason": "Ausführung unbekannt."}
    if execution.get("structure") != "interval":
        return {
            "status": "not_covered",
            "reason": "Keine Intervalle in der Aufzeichnung erkannt.",
        }
    ranges = _ranges(steps, thresholds, sport)
    if isinstance(ranges, dict):
        return ranges
    reps = list(execution.get("reps") or [])
    # The real lap count, not the listed reps (at most 40).
    counted = (execution.get("rep_summary") or {}).get("rep_count")
    executed = counted if isinstance(counted, int) else len(reps)
    work = _work_steps(_levels(ranges, thresholds), executed)
    if not work:
        reasons = sorted({r.unknown for r in ranges if r.unknown})
        return {
            "status": "not_covered",
            "reason": "Keine auswertbaren Zielschritte im Plan.",
            "unknown_targets": reasons,
        }
    return ranges, reps, executed, work


def _ranges(
    steps: Sequence[Mapping[str, Any]], thresholds: ZoneSettings, sport: str
) -> list[TargetRange] | dict[str, Any]:
    """Each step's target bounds, or why the sport cannot resolve them."""
    try:
        canonical_sport = Sport(sport)
    except ValueError:
        return {"status": "not_covered", "reason": "Sportart unbekannt."}
    return [step_target_range(step, thresholds, canonical_sport) for step in steps]


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
    ranges: Sequence[TargetRange], thresholds: ZoneSettings
) -> list[tuple[int, float]]:
    """Each resolved step's target level as a fraction of its threshold.

    Pace targets without a threshold pace are scaled by the fastest pace target,
    so a plan of absolute paces still has levels.
    """
    speeds = [r.low for r in ranges if r.metric == "speed" and r.low]
    references = {
        "speed": thresholds.threshold_pace or (max(speeds) if speeds else None),
        "watts": thresholds.ftp,
        "heartrate": hr_reference(thresholds),
    }
    levels = []
    for index, target in enumerate(ranges):
        reference = references.get(target.metric or "")
        middle = _middle(target)
        if middle is None or not reference:
            continue
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


ADHERENCE_METHOD: Final = "planned-step-adherence-v1"
ADHERENCE_SCOPE: Final = (
    "Every planned step against its window of the session: work steps on their "
    "paired laps, the steps before, between and after them on the time between "
    "those laps, split by planned duration (a distance step at its target "
    "speed); a session without work laps splits its whole span so. "
    "time_in_target_pct is the share of the window's displayed samples inside "
    "the step's target (heart rate over the second half, not for steps under "
    "120 s; stops under 0.3 m/s left out of speed targets); the score is the time in "
    "target over all scored time. Zone times count in the metric with the most "
    "planned time: planned as each step's duration in the zone of its target's "
    "middle, actual from the displayed stream with the same limits."
)
# Time in target from which a step is good, else fair; below fair it is poor
# (athlete 2026-11-14, #2830, after TrainingPeaks' compliance colours).
GOOD_SHARE_PCT: Final = 80
FAIR_SHARE_PCT: Final = 50
# Speeds below this are stops, as in the calendar's pace chart.
MIN_MOVING_SPEED_MPS: Final = 0.3
# A step between work steps below this share of the easiest work step's level
# is a recovery; a harder one is a step of its own.
RECOVERY_LEVEL_SHARE: Final = 0.8


def planned_step_adherence(
    execution: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    thresholds: ZoneSettings,
    sport: str,
    *,
    streams: Mapping[str, Any] | None,
    planned_unit_id: str | None = None,
) -> dict[str, Any]:
    """Each planned step's time in target, the session score and zone times.

    An interval session pairs its laps as the laps' comparison does; a
    continuous one shares its whole span by the steps' planned durations.
    """
    base = {
        "method": ADHERENCE_METHOD,
        "scope": ADHERENCE_SCOPE,
        "planned_unit_id": planned_unit_id,
    }
    continuous = execution.get("status") == "ok" and (
        execution.get("structure") == "continuous"
    )
    paired = (
        _continuous(steps, thresholds, sport)
        if continuous
        else _paired(execution, steps, thresholds, sport)
    )
    if isinstance(paired, dict):
        return {**base, **paired}
    ranges, reps, _executed, work = paired
    timeline = _Timeline(streams)
    span = timeline.span()
    if span is None:
        return {**base, "status": "not_covered", "reason": "Kein Messverlauf."}
    planned = [
        _planned_seconds(step, target)
        for step, target in zip(steps, ranges, strict=True)
    ]
    windows = _step_windows(planned, work, reps, span)
    roles = _roles(len(steps), work, dict(_levels(ranges, thresholds)))
    items = [
        _step_item(index, steps[index], ranges[index], windows.get(index), roles[index])
        for index in range(len(steps))
    ]
    seconds = [
        _scored(item, ranges[index], index, windows, timeline, execution)
        for index, item in enumerate(items)
    ]
    inside = sum(value[0] for value in seconds if value is not None)
    total = sum(value[1] for value in seconds if value is not None)
    result: dict[str, Any] = {**base, "status": "ok", "steps": items}
    if total > 0:
        score = round(inside / total * 100)
        result.update(score_pct=score, score_band=adherence_band(score))
    result["zones"] = _zone_times(
        [
            (target.metric, _middle(target), seconds_or_window)
            for target, seconds_or_window in zip(
                ranges, _zone_seconds(planned, windows), strict=True
            )
            if target.metric is not None and seconds_or_window
        ],
        thresholds,
        timeline,
        span,
    )
    return result


def adherence_band(share_pct: float) -> str:
    """good, fair or poor for a share of time in target."""
    if share_pct >= GOOD_SHARE_PCT:
        return "good"
    return "fair" if share_pct >= FAIR_SHARE_PCT else "poor"


def _continuous(
    steps: Sequence[Mapping[str, Any]], thresholds: ZoneSettings, sport: str
) -> tuple[list[TargetRange], list[Any], int, list[int]] | dict[str, Any]:
    """Step ranges of a session without work laps: no reps and no work steps."""
    ranges = _ranges(steps, thresholds, sport)
    if isinstance(ranges, dict):
        return ranges
    if all(target.metric is None for target in ranges):
        return {
            "status": "not_covered",
            "reason": "Keine auswertbaren Zielschritte im Plan.",
            "unknown_targets": sorted({r.unknown for r in ranges if r.unknown}),
        }
    return ranges, [], 0, []


def _planned_seconds(step: Mapping[str, Any], target: TargetRange) -> float | None:
    """A step's planned duration; a distance step at its target speed's middle."""
    duration, distance = step.get("duration"), step.get("distance")
    if isinstance(duration, (int, float)) and duration > 0:
        return float(duration)
    speed = _middle(target) if target.metric == "speed" else None
    if isinstance(distance, (int, float)) and speed:
        return float(distance) / speed
    return None


def _middle(target: TargetRange) -> float | None:
    """A resolved target's middle; the open top zone counts from its lower bound."""
    if target.low is None or target.high is None:
        return None
    return target.low if math.isinf(target.high) else (target.low + target.high) / 2


def _step_windows(
    planned: Sequence[float | None],
    work: Sequence[int],
    reps: Sequence[Mapping[str, Any]],
    span: tuple[float, float],
) -> dict[int, tuple[float, float] | None]:
    """Each step's time window, ``None`` when its gap cannot be shared.

    Steps after an unrun work step have no entry.
    """
    windows: dict[int, tuple[float, float] | None] = {}
    gaps: list[tuple[range, float, float]] = []
    previous, previous_end = -1, span[0]
    paired = 0
    for index, rep in zip(work, reps, strict=False):
        start, duration = rep.get("start_s"), rep.get("duration_s")
        if not isinstance(start, (int, float)) or not isinstance(
            duration, (int, float)
        ):
            break
        windows[index] = (float(start), float(start) + float(duration))
        gaps.append((range(previous + 1, index), previous_end, float(start)))
        previous, previous_end = index, float(start) + float(duration)
        paired += 1
    if paired == len(work):
        gaps.append((range(previous + 1, len(planned)), previous_end, span[1]))
    for indices, start, end in gaps:
        windows.update(_split(planned, indices, start, end))
    return windows


def _split(
    planned: Sequence[float | None], indices: range, start: float, end: float
) -> dict[int, tuple[float, float] | None]:
    """The time between two laps shared by the planned durations of its steps."""
    if not indices or end <= start:
        return {}
    if len(indices) == 1:
        return {indices[0]: (start, end)}
    seconds = [planned[index] for index in indices]
    known = [value for value in seconds if value]
    if len(known) != len(seconds):
        return dict.fromkeys(indices)
    windows: dict[int, tuple[float, float] | None] = {}
    at = start
    for index, value in zip(indices, known, strict=True):
        following = at + (end - start) * value / sum(known)
        windows[index] = (at, following)
        at = following
    return windows


def _roles(count: int, work: Sequence[int], levels: Mapping[int, float]) -> list[str]:
    """warmup, work, recovery or cooldown; ``step`` without work steps or for a
    step between them that is not clearly easier than the easiest work step."""
    if not work:
        return ["step"] * count
    easiest = min(levels[index] for index in work)
    roles = []
    for index in range(count):
        level = levels.get(index)
        if index in work:
            roles.append("work")
        elif index < work[0] or index > work[-1]:
            roles.append("warmup" if index < work[0] else "cooldown")
        elif level is None or level < easiest * RECOVERY_LEVEL_SHARE:
            roles.append("recovery")
        else:
            roles.append("step")
    return roles


def _step_item(
    index: int,
    step: Mapping[str, Any],
    target: TargetRange,
    window: tuple[float, float] | None,
    role: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "step": index + 1,
        "role": role,
        "planned_target": str(step.get("target") or ""),
    }
    for key, field in (
        ("duration", "planned_duration_s"),
        ("distance", "planned_distance_m"),
    ):
        if isinstance(step.get(key), (int, float)):
            item[field] = round(float(step[key]))
    if window is not None:
        item["start_s"], item["end_s"] = round(window[0]), round(window[1])
    if target.metric is not None and target.low is not None and target.high is not None:
        item["metric"] = target.metric
        item["low"] = round(target.low, 3)
        item["high"] = None if math.isinf(target.high) else round(target.high, 3)
    return item


def _scored(
    item: dict[str, Any],
    target: TargetRange,
    index: int,
    windows: Mapping[int, tuple[float, float] | None],
    timeline: _Timeline,
    execution: Mapping[str, Any],
) -> tuple[float, float] | None:
    """Score the step in place; its seconds in target and scored, if any.

    Stops (speed under 0.3 m/s) count neither for a speed target nor its mean.
    """
    if target.metric is None or target.low is None or target.high is None:
        item["unscored"] = target.unknown or "unsupported_target"
        return None
    item.update(_shown_range(target, execution))
    window = windows.get(index)
    if window is None:
        item["unscored"] = "window_unknown" if index in windows else "not_executed"
        return None
    start, end = window
    if target.metric == "heartrate":
        if end - start < SHORT_REP_S:
            item["unscored"] = "short_step_heart_rate"
            return None
        start = (start + end) / 2
    spans = [
        (value, span)
        for value, span in timeline.spans(target.metric, start, end)
        if target.metric != "speed" or value >= MIN_MOVING_SPEED_MPS
    ]
    total = sum(span for _, span in spans)
    if total <= 0:
        item["unscored"] = "missing_measurement"
        return None
    inside = sum(span for value, span in spans if target.low <= value <= target.high)
    share = round(inside / total * 100)
    actual = sum(value * span for value, span in spans) / total
    item.update(
        time_in_target_pct=share,
        band=adherence_band(share),
        actual=_shown_value(target.metric, actual, execution),
    )
    return inside, total


def _shown_value(metric: str, value: float, execution: Mapping[str, Any]) -> float:
    """A measured mean in the units the athlete reads (s/km, km/h, W, bpm)."""
    if metric == "speed" and execution.get("output") == "pace":
        return round(1000 / value)
    if metric == "speed":
        return round(value * 3.6, 1)
    return round(value)


def _zone_seconds(
    planned: Sequence[float | None],
    windows: Mapping[int, tuple[float, float] | None],
) -> list[float | None]:
    """Each step's planned seconds, else the length of its window."""
    result = []
    for index, seconds in enumerate(planned):
        window = windows.get(index)
        result.append(seconds or (window[1] - window[0] if window else None))
    return result


def _zone_times(
    planned: Sequence[tuple[str | None, float | None, float]],
    thresholds: ZoneSettings,
    timeline: _Timeline,
    span: tuple[float, float],
) -> dict[str, Any]:
    """Planned and actual time per zone in the plan's leading target metric.

    ``planned`` holds each targeted step's metric, target middle and seconds.
    """
    by_metric: dict[str, list[tuple[float, float]]] = {}
    for metric, middle, seconds in planned:
        if metric is not None and middle is not None:
            by_metric.setdefault(metric, []).append((middle, seconds))
    if not by_metric:
        return {"status": "not_covered", "reason": "Keine Zielvorgaben im Plan."}
    metric = max(by_metric, key=lambda key: sum(value for _, value in by_metric[key]))
    reference, zone_of, limits = {
        "speed": (
            thresholds.threshold_pace,
            thresholds.pace_zone,
            thresholds.pace_limits,
        ),
        "watts": (thresholds.ftp, thresholds.power_zone, thresholds.power_limits),
        "heartrate": (
            thresholds.hr_zone_reference,
            thresholds.hr_zone_of_lthr,
            thresholds.hr_limits,
        ),
    }[metric]
    if not reference:
        return {
            "status": "not_covered",
            "metric": metric,
            "reason": "Schwelle unbekannt: keine Zonen.",
        }
    planned_s, actual_s = [0.0] * (len(limits) + 1), [0.0] * (len(limits) + 1)
    for middle, seconds in by_metric[metric]:
        planned_s[zone_of(middle / reference * 100) - 1] += seconds
    for value, seconds in timeline.spans(metric, *span):
        if metric != "speed" or value >= MIN_MOVING_SPEED_MPS:
            actual_s[zone_of(value / reference * 100) - 1] += seconds
    return {
        "status": "ok",
        "metric": metric,
        "zones": [
            {"zone": number, "planned_s": round(plan), "actual_s": round(actual)}
            for number, (plan, actual) in enumerate(
                zip(planned_s, actual_s, strict=True), start=1
            )
        ],
    }


def unit_steps(unit: Mapping[str, Any]) -> list[dict[str, Any]] | dict[str, Any] | None:
    """The unit's expanded steps, why they do not parse, or None without a text."""
    description = unit.get("description")
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_CHARS:
        return None
    try:
        return structured_steps(description, str(unit.get("target") or "AUTO"))
    except WorkoutTextError as error:
        return {
            "status": "not_covered",
            "planned_unit_id": unit.get("id"),
            "reason": error.reason,
        }


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

    def span(self) -> tuple[float, float] | None:
        """First and last time of the displayed streams."""
        times = [time for time in self._times if isinstance(time, (int, float))]
        return (float(times[0]), float(times[-1])) if len(times) >= 2 else None

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
