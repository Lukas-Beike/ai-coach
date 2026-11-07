"""Local per-session efficiency, variability, work and decoupling (card M8, #1680).

``session_metrics`` computes, for one ride or run, from its canonical summary
and, where stored, its merged full-resolution streams:

* efficiency factor (EF): ride ``NP / avg HR`` (W/bpm); run grade-adjusted
  speed, else average speed, in m/min per bpm;
* variability index (VI): ride ``NP / avg power``;
* mechanical work (kJ): ride or run with power, the device's work total, else
  the power stream integrated over time;
* aerobic decoupling (%): the steady-output drift of the session analysis
  (``aerobic_analysis``, Pw:HR for rides and Pa:HR for road runs), first versus
  second half after the warm-up.

Each value carries its basis in ``details``. Provider values of these metrics
are never an input. ``metrics_fingerprint`` hashes every input before any
stream is decoded, so a caller can skip a session whose stored values are
current. This module is pure: no database, no provider and no ``server.py``
access.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from backend.canonical.activity_summary import summary_duration_s, summary_local_date
from backend.canonical.records import fingerprint_inputs
from backend.canonical.vocabulary import MetricKind, Sport
from backend.performance.session_analysis import METHOD as ANALYSIS_METHOD
from backend.performance.session_analysis import aerobic_analysis

METHOD_ID: Final = "local-session-metrics"
METHOD_VERSION: Final = 1
CARD: Final = "M8"

METRIC_SPORTS: Final = frozenset({Sport.RIDE.value, Sport.RUN.value})
# A stream sample longer than this is a gap, as in the session analysis.
MAX_SAMPLE_GAP_S: Final = 5.0
# Share of the moving duration the power stream must cover for a work value.
MIN_WORK_COVERAGE: Final = 0.85
VARIABILITY_BOUNDS: Final = (0.5, 5.0)
HEART_RATE_RANGE: Final = (30.0, 240.0)
SECONDS_PER_MINUTE: Final = 60.0
JOULES_PER_KJ: Final = 1000.0

EF_POWER_BASIS: Final = "normalized_power"
EF_GAP_BASIS: Final = "grade_adjusted_speed"
EF_SPEED_BASIS: Final = "average_speed"
WORK_DEVICE_BASIS: Final = "device_total"
WORK_STREAM_BASIS: Final = "power_stream"

# The summary values the method reads; their change changes the fingerprint.
_SUMMARY_INPUTS: Final = (
    "started_at",
    "local_offset_minutes",
    "recorded_by",
    "sport",
    "environment",
    "terrain",
    "assist",
    "moving_duration_s",
    "elapsed_duration_s",
    "avg_hr",
    "avg_power",
    "normalized_power",
    "grade_adjusted_speed_mps",
    "avg_speed_mps",
    "energy_kj",
)


@dataclass(frozen=True, slots=True)
class SessionMetrics:
    """One session's local metric values, each with its own derivation details."""

    values: Mapping[MetricKind, float]
    details: Mapping[MetricKind, Mapping[str, Any]]
    fingerprint: str


def wants_metrics(summary: Mapping[str, Any]) -> bool:
    """Whether the method covers the session's sport (ride or run)."""
    return summary.get("sport") in METRIC_SPORTS


def metrics_fingerprint(
    summary: Mapping[str, Any],
    stream_hashes: Sequence[str],
    members: Sequence[Sequence[object]],
) -> str:
    """Hash the method, the summary inputs, the stream sets and the session members.

    ``stream_hashes`` are the content hashes of the session's full-resolution
    stream sets; ``members`` identify its records in merge order, so another
    winning stream source recomputes the values.
    """
    return fingerprint_inputs(
        {
            "method": METHOD_ID,
            "method_version": METHOD_VERSION,
            "analysis_method": ANALYSIS_METHOD,
            "summary": {key: summary.get(key) for key in _SUMMARY_INPUTS},
            # The stored row's day, instant and origin come from these.
            "local_date": summary_local_date(summary),
            "streams": sorted(stream_hashes),
            "members": [list(map(_text, member)) for member in members],
        }
    )


def session_metrics(
    summary: Mapping[str, Any],
    activity: Mapping[str, Any] | None,
    fingerprint: str,
) -> SessionMetrics:
    """Compute the session's metrics; ``activity`` is its merged analysis input.

    ``activity`` is None for a session without full-resolution streams; such a
    session gets only the summary values (EF, VI and a device work total).
    """
    values: dict[MetricKind, float] = {}
    details: dict[MetricKind, dict[str, Any]] = {}
    if not wants_metrics(summary):
        return SessionMetrics(values, details, fingerprint)
    for kind, result in (
        (MetricKind.EFFICIENCY_FACTOR, _efficiency(summary)),
        (MetricKind.VARIABILITY_INDEX, _variability(summary)),
        (MetricKind.MECHANICAL_WORK, _work(summary, activity)),
        (MetricKind.AEROBIC_DECOUPLING, _decoupling(activity)),
    ):
        if result is not None:
            values[kind], details[kind] = result
    return SessionMetrics(values, details, fingerprint)


def _efficiency(summary: Mapping[str, Any]) -> tuple[float, dict[str, Any]] | None:
    heart_rate = _positive(summary.get("avg_hr"))
    if heart_rate is None or not _within(heart_rate, HEART_RATE_RANGE):
        return None
    if summary.get("sport") == Sport.RIDE.value:
        power = _positive(summary.get("normalized_power"))
        if power is None:
            return None
        return power / heart_rate, {"basis": EF_POWER_BASIS, "unit": "W/bpm"}
    speed = _positive(summary.get("grade_adjusted_speed_mps"))
    basis = EF_GAP_BASIS
    if speed is None:
        speed, basis = _positive(summary.get("avg_speed_mps")), EF_SPEED_BASIS
    if speed is None:
        return None
    return (
        speed * SECONDS_PER_MINUTE / heart_rate,
        {"basis": basis, "unit": "(m/min)/bpm"},
    )


def _variability(summary: Mapping[str, Any]) -> tuple[float, dict[str, Any]] | None:
    if summary.get("sport") != Sport.RIDE.value:
        return None
    normalized = _positive(summary.get("normalized_power"))
    average = _positive(summary.get("avg_power"))
    if normalized is None or average is None:
        return None
    index = normalized / average
    if not _within(index, VARIABILITY_BOUNDS):
        return None
    return index, {}


def _work(
    summary: Mapping[str, Any], activity: Mapping[str, Any] | None
) -> tuple[float, dict[str, Any]] | None:
    device = _positive(summary.get("energy_kj"))
    if device is not None:
        return device, {"basis": WORK_DEVICE_BASIS}
    streams = (activity or {}).get("streams") or {}
    times, watts = streams.get("time") or [], streams.get("watts") or []
    moving = summary_duration_s(summary)
    if len(times) < 2 or len(watts) != len(times) or not moving:
        return None
    joules = covered = 0.0
    for index in range(len(times) - 1):
        step = float(times[index + 1]) - float(times[index])
        power = _number(watts[index])
        if power is None or power < 0 or not 0 < step <= MAX_SAMPLE_GAP_S:
            continue
        joules += power * step
        covered += step
    coverage = covered / moving
    if coverage < MIN_WORK_COVERAGE or joules <= 0:
        return None
    return joules / JOULES_PER_KJ, {
        "basis": WORK_STREAM_BASIS,
        "coverage": round(min(coverage, 1.0), 3),
    }


def _decoupling(
    activity: Mapping[str, Any] | None,
) -> tuple[float, dict[str, Any]] | None:
    if activity is None:
        return None
    result = aerobic_analysis(dict(activity), source_label="")
    if result.get("status") != "ok":
        return None
    return float(result["drift_percent"]), {
        "sensor": result["sensor"],
        "unit": result["unit"],
        "efficiency": result["efficiency"],
        "halves": [
            {
                key: half[key]
                for key in ("measured_seconds", "mean_output", "mean_hr", "efficiency")
            }
            for half in result["halves"]
        ],
        "long_session": result["long_session"],
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _positive(value: object) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _within(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))
