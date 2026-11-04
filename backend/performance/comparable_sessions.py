"""One session's execution against comparable earlier sessions of the athlete.

Comparable: earlier runs or rides of the last ``COMPARE_DAYS`` days with the
same sport, environment (indoor or outdoor) and structure, and a similar shape
and effort: a continuous main part within ``DURATION_SHARE`` of this one and an
average heart rate within ``HEART_RATE_BAND`` bpm, or interval sessions within
``REP_COUNT_SPREAD`` reps whose median rep lasts within ``DURATION_SHARE`` of
this one's. Sessions with doubtful heart rate or speed stay out. Fewer than
``MIN_PEERS`` of them is ``not_covered``. Values come from each session's own
execution, the median of the peers is the reference; nothing is scored, and
temperatures are named so heat is not read as fitness. Pure: no I/O.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from backend.performance.session_execution import rounded_metric

METHOD: Final = "comparable-sessions-v1"
COMPARE_DAYS: Final = 84
MIN_PEERS: Final = 3
MAX_LISTED: Final = 6
DURATION_SHARE: Final = 0.35
REP_COUNT_SPREAD: Final = 2
# Continuous sessions compare only at a similar effort, so an easy run is never
# a tempo run's peer; within the band a faster pace still shows as fitter.
HEART_RATE_BAND: Final = 8
SCOPE: Final = (
    f"This session against earlier comparable sessions of up to {COMPARE_DAYS} "
    "days: same sport, indoor or outdoor and structure; a continuous main part "
    "within 35 % of this one's duration and 8 bpm of its average heart rate, or "
    "intervals within 2 reps and 35 % of the median rep duration; sessions with "
    "doubtful heart rate or speed stay out. difference is this session minus the "
    "peers' median in the metric's unit (pace s/km: negative is faster). Terrain "
    "is not matched. Temperatures are listed so heat is not read as a fitness "
    "change. Descriptive; at least 3 peers."
)
_METRICS: Final = {
    "continuous": ("output", "heart_rate_avg", "heart_rate_change_bpm", "cadence"),
    "interval": (
        "rep_output_mean",
        "heart_rate_end_mean",
        "recovery_drop_mean",
        "first_to_last_change_pct",
        "cadence_mean",
    ),
}


def comparable_sessions(
    records: Sequence[Mapping[str, Any]],
    activity_key: str,
    *,
    covered_from: date | None = None,
) -> dict[str, Any]:
    """Compare one session's execution with its comparable earlier sessions.

    ``covered_from`` is the first day the records cover; an earlier peer window
    is cut there and named as truncated.
    """
    base = {"method": METHOD, "scope": SCOPE}
    own = next((row for row in records if row.get("activity_id") == activity_key), None)
    # A session without a curve has no full-resolution streams.
    if own is None or own.get("fingerprint") is None:
        return _not_covered(
            base, "Keine Messreihe in voller Auflösung für diese Einheit."
        )
    mine = own.get("execution_summary")
    if not isinstance(mine, Mapping):
        return _not_covered(
            base,
            "Keine vergleichbare Ausführung: Hauptteil zu kurz oder keine Intervalle mit Messwerten.",
        )
    if mine.get("data_quality_ok") is False:
        return _not_covered(
            base, "Puls oder Tempo dieser Einheit sind zweifelhaft (data_quality)."
        )
    try:
        day = date.fromisoformat(str(own.get("date") or ""))
    except ValueError:
        return _not_covered(base, "Datum der Einheit unbekannt.")
    first = day - timedelta(days=COMPARE_DAYS)
    truncated = covered_from is not None and covered_from > first
    if covered_from is not None and truncated:
        first = covered_from
    window = {"window_days": (day - first).days, "window_truncated": truncated}
    peers = _peers(records, own, mine, first, day)
    if len(peers) < MIN_PEERS:
        return _not_covered(
            base,
            f"{len(peers)} vergleichbare Einheiten in {window['window_days']} Tagen, mindestens {MIN_PEERS} nötig.",
            count=len(peers),
            **window,
        )
    metrics = _METRICS.get(str(mine.get("structure")), ())
    median, difference = _medians(mine, peers, metrics)
    peers.sort(key=lambda row: str(row.get("date")), reverse=True)
    return {
        **base,
        "status": "ok",
        "count": len(peers),
        **window,
        "this": {**mine, "date": own.get("date"), "avg_temp_c": own.get("avg_temp_c")},
        "median_of_peers": median,
        "difference": difference,
        "peers": [
            {
                "date": row.get("date"),
                "name": row.get("name"),
                "avg_temp_c": row.get("avg_temp_c"),
                "source": row["execution_summary"].get("source"),
                **{
                    key: row["execution_summary"][key]
                    for key in metrics
                    if key in row["execution_summary"]
                },
            }
            for row in peers[:MAX_LISTED]
        ],
    }


def _peers(
    records: Sequence[Mapping[str, Any]],
    own: Mapping[str, Any],
    mine: Mapping[str, Any],
    first: date,
    day: date,
) -> list[Mapping[str, Any]]:
    """Earlier sessions of the window with this one's kind, sound data and shape."""
    return [
        row
        for row in records
        if row is not own
        and first.isoformat() <= str(row.get("date") or "") < day.isoformat()
        and row.get("sport") == own.get("sport")
        and row.get("environment") == own.get("environment")
        and _sound_peer(mine, row.get("execution_summary"))
    ]


def _sound_peer(mine: Mapping[str, Any], other: Any) -> bool:
    return (
        isinstance(other, Mapping)
        and other.get("data_quality_ok") is not False
        and _similar(mine, other)
    )


def _medians(
    mine: Mapping[str, Any],
    peers: Sequence[Mapping[str, Any]],
    metrics: Sequence[str],
) -> tuple[dict[str, float], dict[str, float]]:
    """The peers' median of each metric and this session's difference to it."""
    median: dict[str, float] = {}
    difference: dict[str, float] = {}
    for metric in metrics:
        values = [
            float(row["execution_summary"][metric])
            for row in peers
            if isinstance(row["execution_summary"].get(metric), (int, float))
        ]
        if len(values) < MIN_PEERS:
            continue
        median[metric] = rounded_metric(statistics.median(values))
        if isinstance(mine.get(metric), (int, float)):
            difference[metric] = rounded_metric(float(mine[metric]) - median[metric])
    return median, difference


def _similar(mine: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
    if mine.get("structure") != other.get("structure"):
        return False
    if mine.get("output_unit") != other.get("output_unit"):
        return False
    if mine.get("structure") == "continuous":
        return _close(mine.get("main_part_s"), other.get("main_part_s")) and _within(
            mine.get("heart_rate_avg"), other.get("heart_rate_avg"), HEART_RATE_BAND
        )
    count, peer_count = mine.get("rep_count"), other.get("rep_count")
    if not isinstance(count, int) or not isinstance(peer_count, int):
        return False
    return abs(count - peer_count) <= REP_COUNT_SPREAD and _close(
        mine.get("median_rep_s"), other.get("median_rep_s")
    )


def _close(value: Any, other: Any) -> bool:
    if not isinstance(value, (int, float)) or not isinstance(other, (int, float)):
        return False
    if value <= 0:
        return False
    return abs(other - value) <= DURATION_SHARE * value


def _within(value: Any, other: Any, band: float) -> bool:
    if not isinstance(value, (int, float)) or not isinstance(other, (int, float)):
        return False
    return abs(other - value) <= band


def _not_covered(base: Mapping[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    return {**base, "status": "not_covered", "reason": reason, **extra}


EFFORT_METHOD: Final = "equal-effort-trend-v1"
EFFORT_SCOPE: Final = (
    "Steady sessions of the earlier and the later half of the period: median "
    "output per heart beat (rides with power W/bpm, runs m/s per bpm x 100) per "
    "sport and indoor or outdoor, with the median heart rate and temperature of "
    "each half. A higher later value means more output at the same heart rate. "
    f"Needs at least {MIN_PEERS} steady sessions per half; halves whose median "
    f"heart rate differs by more than {HEART_RATE_BAND} bpm are named, as effort "
    "then differs. Rides without power and terrain are not compared."
)
# Each sport's output unit; a ride without power has no comparable output.
_EFFORT_UNITS: Final = {"run": "s/km", "ride": "W"}


def equal_effort_trend(
    records: Sequence[Mapping[str, Any]],
    start: date,
    middle: date,
    end: date,
    *,
    sports: Sequence[str] = ("run", "ride"),
) -> dict[str, Any]:
    """Earlier-versus-later output per heart beat of steady runs and rides."""
    halves = {"earlier": (start, middle - timedelta(days=1)), "later": (middle, end)}
    result: dict[str, Any] = {"method": EFFORT_METHOD, "scope": EFFORT_SCOPE}
    for sport in sports:
        result[sport] = {
            environment: _effort_halves(records, sport, environment, halves)
            for environment in ("outdoor", "indoor")
        }
    return result


def _effort_halves(
    records: Sequence[Mapping[str, Any]],
    sport: str,
    environment: str,
    halves: Mapping[str, tuple[date, date]],
) -> dict[str, Any]:
    parts: dict[str, dict[str, Any]] = {}
    for name, (first, last) in halves.items():
        values = _steady_sessions(records, sport, environment, first, last)
        if len(values) < MIN_PEERS:
            return {
                "status": "not_covered",
                "reason": f"{len(values)} gleichmäßige Einheiten in der Hälfte {name}, mindestens {MIN_PEERS} nötig.",
            }
        parts[name] = _effort_half(values)
    earlier, later = parts["earlier"], parts["later"]
    return {
        "status": "ok",
        **parts,
        "change_pct": round(
            (later["output_per_beat"] - earlier["output_per_beat"])
            / earlier["output_per_beat"]
            * 100,
            1,
        ),
        "effort_differs": abs(later["heart_rate_median"] - earlier["heart_rate_median"])
        > HEART_RATE_BAND,
    }


def _steady_sessions(
    records: Sequence[Mapping[str, Any]],
    sport: str,
    environment: str,
    first: date,
    last: date,
) -> list[tuple[float, Mapping[str, Any]]]:
    """Output per beat of the steady sessions of one half, sport and place."""
    values = []
    for row in records:
        summary = row.get("execution_summary")
        if (
            row.get("sport") != sport
            or row.get("environment") != environment
            or not first.isoformat() <= str(row.get("date") or "") <= last.isoformat()
            or not isinstance(summary, Mapping)
            or summary.get("output_unit") != _EFFORT_UNITS[sport]
        ):
            continue
        efficiency = _efficiency(summary)
        if efficiency is not None:
            values.append((efficiency, row))
    return values


def _effort_half(values: Sequence[tuple[float, Mapping[str, Any]]]) -> dict[str, Any]:
    temperatures = [
        float(row["avg_temp_c"])
        for _, row in values
        if isinstance(row.get("avg_temp_c"), (int, float))
    ]
    return {
        "sessions": len(values),
        "output_per_beat": round(statistics.median(v for v, _ in values), 3),
        "heart_rate_median": rounded_metric(
            statistics.median(
                float(row["execution_summary"]["heart_rate_avg"]) for _, row in values
            )
        ),
        "temperature_median_c": rounded_metric(statistics.median(temperatures))
        if temperatures
        else None,
    }


def _efficiency(summary: Any) -> float | None:
    """Output per heart beat of a steady session with sound data."""
    if not isinstance(summary, Mapping) or summary.get("structure") != "continuous":
        return None
    if summary.get("data_quality_ok") is False:
        return None
    output, heart = summary.get("output"), summary.get("heart_rate_avg")
    if not isinstance(output, (int, float)) or not isinstance(heart, (int, float)):
        return None
    if output <= 0 or heart <= 0:
        return None
    unit = summary.get("output_unit")
    if unit == "W":
        return float(output) / float(heart)
    if unit == "s/km":
        return 1000.0 / float(output) / float(heart) * 100
    return None
