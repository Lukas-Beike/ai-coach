"""Read-time intensity, 3-zone time and load of planned run and ride workouts.

``estimate_workout`` parses Intervals.icu workout text with ``structured_steps``
and resolves each step's target (zone, percent, absolute watts/bpm/pace) against
the athlete's current thresholds. Nothing is persisted and nothing is invented:
a target, threshold or step that cannot be resolved leaves exactly the values
that depend on it as ``None`` and names the reason in ``unknown``. Every value is
derived (``SOURCE``); the thresholds it rests on keep their provider labels in
``threshold_sources``. Callers pass only thresholds they consider current.

Definitions (intensity = fraction of the threshold, 1.0 = threshold):
- Power: % of FTP, watts / FTP. Pace: % of threshold speed, speed / threshold
  speed. Heart rate: % of LTHR, bpm / LTHR; % of max HR needs the max HR, and
  without an LTHR assumes ``LTHR_SHARE_OF_MAX_HR`` of it (named in the basis).
- Zone targets use the midpoint of the zone's limits (the lower bound for the
  open top zone); ranges and ramps use the mean of both ends.
- Unit intensity factor: normalized over steps (4th-power mean) when every step
  is power-targeted, else the quadratic mean. Load = hours x IF^2 x 100
  (TSS style; for pace/HR steps an rTSS/hrTSS-style analogue, not a provider TSS).
- Bands: Z1-Z2 low, Z3-Z4 moderate, Z5+ high (7 zones); Z1-Z2 / Z3 / Z4+ with
  up to 5 zones, as in the recorded progress report.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.activities.workout_text import WorkoutTextError, structured_steps
from backend.activities.zone_settings import (
    LTHR_SHARE_OF_MAX_HR,
    ZoneSettings,
    percent_zone,
)
from backend.canonical.vocabulary import Sport

SOURCE = "derived"
METHOD = "workout-steps-v1"
BANDS = ("low", "moderate", "high")
_MANY_ZONES = 6
_MILE_M = 1609.344
_NUMBER = r"\d++(?:\.\d++)?+"
_ZONE = re.compile(r"Z(\d++)(?:-Z(\d++))?+")
_PERCENT = re.compile(rf"({_NUMBER})%?(?:-({_NUMBER})%?)?")
_ABSOLUTE = re.compile(rf"({_NUMBER})(?:-({_NUMBER}))?(W|BPM)")
_PACE = re.compile(r"\b(\d{1,3}):([0-5]\d)")
_PACE_UNIT = re.compile(r"/(KM|MI)\b")


@dataclass(frozen=True)
class AthleteThresholds:
    """Current thresholds; ``None`` means unknown, never a default.

    ``zones`` carries FTP, LTHR, max HR and the zone limits (local zone settings
    first, then provider values, as built by ``ZoneSettings``).
    ``threshold_speed_mps`` is the threshold running speed in m/s.
    ``sources`` labels each threshold ("ftp", "lthr", "max_hr", "threshold_pace").
    """

    zones: ZoneSettings = field(default_factory=ZoneSettings)
    threshold_speed_mps: float | None = None
    sources: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StepEstimate:
    kind: str
    target: str
    duration_s: float | None
    distance_m: float | None
    intensity: float | None
    zone: int | None
    band: str | None
    basis: str | None
    unknown: str | None
    used: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkoutEstimate:
    sport: str
    steps: tuple[StepEstimate, ...]
    duration_s: float | None
    distance_m: float | None
    band_seconds: dict[str, float] | None
    intensity_factor: float | None
    load: float | None
    load_basis: str | None
    unknown: tuple[str, ...]
    threshold_sources: dict[str, str]
    source: str = SOURCE
    method: str = METHOD


@dataclass(frozen=True)
class _Target:
    intensity: float | None = None
    speed_mps: float | None = None
    zone: int | None = None
    basis: str | None = None
    unknown: str | None = None
    used: tuple[str, ...] = ()


def zone_band(zone: int, zone_count: int) -> str:
    moderate, high = (3, 5) if zone_count >= _MANY_ZONES else (3, 4)
    if zone < moderate:
        return "low"
    return "moderate" if zone < high else "high"


def _unknown(reason: str) -> _Target:
    return _Target(unknown=reason)


def _limits(kind: str, zones: ZoneSettings) -> tuple[float, ...]:
    return {
        "power": zones.power_limits,
        "pace": zones.pace_limits,
        "hr": zones.hr_limits,
    }[kind]


def _zone_target(match: re.Match[str], kind: str, zones: ZoneSettings) -> _Target:
    first = int(match[1])
    last = int(match[2] or match[1])
    limits = _limits(kind, zones)
    if not 1 <= first <= last <= len(limits) + 1:
        return _unknown("zone_out_of_range")
    low = limits[first - 2] if first > 1 else 0.0
    high = limits[last - 1] if last <= len(limits) else limits[-1]
    return _Target(
        intensity=(low + high) / 200,
        zone=int((first + last) / 2 + 0.5),
        basis="zone_midpoint",
    )


def _mean(match: re.Match[str]) -> float:
    return (float(match[1]) + float(match[2] or match[1])) / 2


def _percent_target(
    text: str, kind: str, thresholds: AthleteThresholds
) -> _Target | None:
    match = _PERCENT.fullmatch(text.split()[0]) if "%" in text else None
    if match is None:
        return None
    value = _mean(match) / 100
    if kind != "hr" or "LTHR" in text:
        label = {"power": "ftp", "pace": "threshold_pace", "hr": "lthr"}[kind]
        return _Target(intensity=value, basis=f"percent_of_{label}", used=(label,))
    return _percent_of_max_hr(value, thresholds)


def _percent_of_max_hr(value: float, thresholds: AthleteThresholds) -> _Target:
    zones = thresholds.zones
    if not zones.max_hr:
        return _Target(unknown="missing_max_hr")
    if zones.lthr:
        return _Target(
            intensity=value * zones.max_hr / zones.lthr,
            basis="percent_of_max_hr",
            used=("max_hr", "lthr"),
        )
    return _Target(
        intensity=value / LTHR_SHARE_OF_MAX_HR,
        basis="percent_of_max_hr_assumed_lthr_share",
        used=("max_hr",),
    )


def _absolute_target(
    text: str, kind: str, thresholds: AthleteThresholds
) -> _Target | None:
    match = _ABSOLUTE.fullmatch(text.split()[0])
    if match is None:
        return None
    value = _mean(match)
    threshold, label = (
        (thresholds.zones.ftp, "ftp")
        if kind == "power"
        else (thresholds.zones.lthr, "lthr")
    )
    if not threshold:
        return _unknown(f"missing_{label}")
    return _Target(
        intensity=value / threshold, basis=f"absolute_over_{label}", used=(label,)
    )


def _pace_target(text: str, thresholds: AthleteThresholds) -> _Target:
    unit = _PACE_UNIT.search(text)
    times = [int(m) * 60 + int(s) for m, s in _PACE.findall(text)]
    if unit is None or not times:
        return _unknown("pace_unit_unknown")
    metres = 1000.0 if unit[1] == "KM" else _MILE_M
    if not sum(times):
        return _unknown("invalid_pace")
    speed = metres / (sum(times) / len(times))
    reference = thresholds.threshold_speed_mps
    if not reference:
        return _Target(speed_mps=speed, unknown="missing_threshold_pace")
    return _Target(
        intensity=speed / reference,
        speed_mps=speed,
        basis="absolute_over_threshold_pace",
        used=("threshold_pace",),
    )


def _bare_run_target(text: str, kind: str, sport: Sport) -> bool:
    """Unsuffixed run targets parse as power but Intervals.icu may read pace."""
    return (
        sport is Sport.RUN
        and kind == "power"
        and not text.split()[0].endswith("W")
        and "FTP" not in text.split()[1:]
    )


def _resolve_target(
    step: Mapping[str, Any], thresholds: AthleteThresholds, sport: Sport
) -> _Target:
    text, kind = str(step["target"]), str(step["kind"])
    if _bare_run_target(text, kind, sport):
        return _unknown("ambiguous_run_target")
    zone = _ZONE.fullmatch(text.split()[0])
    if zone:
        return _zone_target(zone, kind, thresholds.zones)
    if ":" in text:
        return _pace_target(text, thresholds)
    resolved = _percent_target(text, kind, thresholds) or _absolute_target(
        text, kind, thresholds
    )
    return resolved or _unknown("unsupported_target")


def _pace_speed(
    step: Mapping[str, Any], target: _Target, thresholds: AthleteThresholds
) -> float | None:
    if target.speed_mps:
        return target.speed_mps
    reference = thresholds.threshold_speed_mps
    if step["kind"] == "pace" and target.intensity and reference:
        return target.intensity * reference
    return None


def _estimate_step(
    step: Mapping[str, Any], thresholds: AthleteThresholds, sport: Sport
) -> StepEstimate:
    target = _resolve_target(step, thresholds, sport)
    speed = _pace_speed(step, target, thresholds)
    duration = step.get("duration")
    distance = step.get("distance")
    unknown = target.unknown
    if duration is None and distance is not None and speed:
        duration = distance / speed
    elif distance is None and duration is not None and speed:
        distance = duration * speed
    if duration is None:
        unknown = unknown or "missing_pace_for_distance_step"
    zone = target.zone
    if zone is None and target.intensity is not None:
        limits = _limits(str(step["kind"]), thresholds.zones)
        zone = percent_zone(target.intensity * 100, limits)
    band = None
    if zone is not None:
        band = zone_band(zone, len(_limits(str(step["kind"]), thresholds.zones)) + 1)
    return StepEstimate(
        kind=str(step["kind"]),
        target=str(step["target"]),
        duration_s=duration,
        distance_m=distance,
        intensity=target.intensity,
        zone=zone,
        band=band,
        basis=target.basis,
        unknown=unknown,
        used=target.used,
    )


def _all_known(steps: tuple[StepEstimate, ...], *fields: str) -> bool:
    return all(getattr(step, name) is not None for step in steps for name in fields)


def _unit_intensity(steps: tuple[StepEstimate, ...]) -> tuple[float, float, str]:
    """Intensity factor, hours and basis of steps with duration and intensity."""
    power = all(step.kind == "power" for step in steps)
    exponent = 4 if power else 2
    seconds = sum(step.duration_s or 0.0 for step in steps)
    mean = (
        sum(
            (step.duration_s or 0.0) * (step.intensity or 0.0) ** exponent
            for step in steps
        )
        / seconds
    )
    kinds = {step.kind for step in steps}
    basis = {
        "power": "normalized_power_over_ftp",
        "pace": "relative_pace_speed",
        "hr": "relative_lthr",
    }.get(next(iter(kinds)) if len(kinds) == 1 else "", "mixed_step_intensity")
    return mean ** (1 / exponent), seconds / 3600, basis


def _band_seconds(steps: tuple[StepEstimate, ...]) -> dict[str, float] | None:
    if not _all_known(steps, "duration_s", "band"):
        return None
    result = dict.fromkeys(BANDS, 0.0)
    for step in steps:
        result[str(step.band)] += step.duration_s or 0.0
    return result


def _sum_or_none(steps: tuple[StepEstimate, ...], name: str) -> float | None:
    if not steps or not _all_known(steps, name):
        return None
    return sum(getattr(step, name) for step in steps)


def _reasons(steps: tuple[StepEstimate, ...]) -> tuple[str, ...]:
    return tuple(sorted({step.unknown for step in steps if step.unknown}))


def _empty(sport: str, reason: str, duration_s: float | None = None) -> WorkoutEstimate:
    return WorkoutEstimate(
        sport=sport,
        steps=(),
        duration_s=duration_s,
        distance_m=None,
        band_seconds=None,
        intensity_factor=None,
        load=None,
        load_basis=None,
        unknown=(reason,),
        threshold_sources={},
    )


def estimate_workout(
    description: str,
    sport: Sport,
    thresholds: AthleteThresholds,
    *,
    fallback_duration_s: float | None = None,
) -> WorkoutEstimate:
    """Estimate one planned workout; unknown inputs stay unknown, never raise.

    Only run and ride have evaluable steps. ``fallback_duration_s`` is the unit's
    own planned duration, used only when the steps cannot be parsed.
    """
    if sport not in {Sport.RUN, Sport.RIDE}:
        return _empty(sport.value, "sport_without_step_targets", fallback_duration_s)
    try:
        parsed = structured_steps(description)
    except WorkoutTextError as error:
        return _empty(sport.value, error.reason, fallback_duration_s)
    steps = tuple(_estimate_step(step, thresholds, sport) for step in parsed)
    load = factor = basis = None
    if _all_known(steps, "duration_s", "intensity"):
        factor, hours, basis = _unit_intensity(steps)
        load = hours * factor**2 * 100
    used = {name for step in steps for name in step.used}
    return WorkoutEstimate(
        sport=sport.value,
        steps=steps,
        duration_s=_sum_or_none(steps, "duration_s"),
        distance_m=_sum_or_none(steps, "distance_m"),
        band_seconds=_band_seconds(steps),
        intensity_factor=factor,
        load=load,
        load_basis=basis,
        unknown=_reasons(steps),
        threshold_sources={
            name: thresholds.sources[name]
            for name in sorted(used)
            if name in thresholds.sources
        },
    )


# A single-value target (no range) is read as this share either side of it.
SINGLE_TARGET_SHARE = 0.025


@dataclass(frozen=True)
class TargetRange:
    """Absolute bounds of one planned step's target, or why there are none.

    ``metric`` is ``watts``, ``heartrate`` or ``speed`` (m/s); ``low`` and
    ``high`` are in W, bpm or m/s; ``high`` is ``math.inf`` for the open top
    zone. Ramps have no single range.
    """

    metric: str | None = None
    low: float | None = None
    high: float | None = None
    unknown: str | None = None


def step_target_range(
    step: Mapping[str, Any], thresholds: AthleteThresholds, sport: Sport
) -> TargetRange:
    """Bounds of a parsed workout step's target from the athlete's thresholds."""
    if step.get("ramp"):
        return TargetRange(unknown="ramp")
    text, kind = str(step["target"]), str(step["kind"])
    target = _resolve_target(step, thresholds, sport)
    if ":" in text and kind == "pace":
        return _pace_range(text) or TargetRange(unknown="pace_unit_unknown")
    if target.unknown or target.intensity is None:
        return TargetRange(unknown=target.unknown or "unsupported_target")
    bounds = _fraction_bounds(text, kind, target.intensity, thresholds.zones)
    reference = {
        "power": ("watts", thresholds.zones.ftp),
        "hr": ("heartrate", hr_reference(thresholds.zones)),
        "pace": ("speed", thresholds.threshold_speed_mps),
    }[kind]
    metric, value = reference
    if not value:
        return TargetRange(unknown=f"missing_{kind}_threshold")
    return _widened(metric, bounds[0] * value, bounds[1] * value)


def _fraction_bounds(
    text: str, kind: str, intensity: float, zones: ZoneSettings
) -> tuple[float, float]:
    """Lower and upper bound as fractions of the threshold."""
    first = text.split()[0]
    zone = _ZONE.fullmatch(first)
    if zone:
        limits = _limits(kind, zones)
        low_zone, high_zone = int(zone[1]), int(zone[2] or zone[1])
        low = limits[low_zone - 2] / 100 if low_zone > 1 else 0.0
        # The top zone is open: it has no upper bound.
        high = limits[high_zone - 1] / 100 if high_zone <= len(limits) else math.inf
        return low, max(high, low)
    match = _PERCENT.fullmatch(first) or _ABSOLUTE.fullmatch(first)
    if match is None:
        return intensity, intensity
    mean = _mean(match)
    numbers = (float(match[1]), float(match[2] or match[1]))
    return (
        intensity * min(numbers) / mean,
        intensity * max(numbers) / mean,
    )


def hr_reference(zones: ZoneSettings) -> float | None:
    """The heart rate an HR intensity of 1.0 means: LTHR, else its assumed share."""
    if zones.lthr:
        return zones.lthr
    return zones.max_hr * LTHR_SHARE_OF_MAX_HR if zones.max_hr else None


def _pace_range(text: str) -> TargetRange | None:
    unit = _PACE_UNIT.search(text)
    times = [int(m) * 60 + int(s) for m, s in _PACE.findall(text)]
    if unit is None or not times or not all(times):
        return None
    metres = 1000.0 if unit[1] == "KM" else _MILE_M
    speeds = [metres / time for time in times]
    return _widened("speed", min(speeds), max(speeds))


def _widened(metric: str, low: float, high: float) -> TargetRange:
    if math.isfinite(high) and high - low <= 1e-9:
        low, high = low * (1 - SINGLE_TARGET_SHARE), high * (1 + SINGLE_TARGET_SHARE)
    return TargetRange(metric=metric, low=low, high=high)
