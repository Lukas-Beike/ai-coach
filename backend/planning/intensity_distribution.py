"""Planned 3-zone distribution of a week and its comparison with the training model.

Per ISO week the low / moderate / high time of the planned run and ride units is
summed from their workout steps (``estimate_planned_unit``, the zone mapping of
the weekly progress report). Time whose steps cannot be resolved is reported as
``uncovered_s``, never as low; strength does not count. A week is only judged
when enough of its endurance time is covered.

``MODEL_RANGES`` are reference ranges of the share of covered time, not targets.
Evidence: pyramidal and polarized after Seiler (2010) and Stoeggl & Sperlich
(2014, 2015); threshold and sweet spot are practice-based ranges without a
controlled evidence base. A note appears only when a share lies more than
``TOLERANCE`` outside its range. No I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from backend.activities.workout_load import BANDS, WorkoutEstimate
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.vocabulary import Sport
from backend.performance.progress_report import ZONE_MAPPING, intensity_3zone
from backend.planning import plan_checks, running_week, unit_intensity
from backend.planning.running_week import planned_seconds
from backend.planning.running_week import unit_week_start as _monday
from backend.planning.sport import planned_sport_environment

CODE = "intensity_distribution"
EVIDENCE = {
    "pyramidal": "observational/experimental, moderate (Seiler 2010; Stoeggl & Sperlich 2014)",
    "polarized": "experimental, moderate (Seiler 2010; Stoeggl & Sperlich 2014)",
    "threshold": "practice-based reference range",
    "sweet_spot": "practice-based reference range",
}
# Share of covered time (low, moderate, high) as (minimum, maximum).
MODEL_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "pyramidal": {
        "low": (0.65, 0.90),
        "moderate": (0.08, 0.30),
        "high": (0.0, 0.12),
    },
    "polarized": {
        "low": (0.65, 0.90),
        "moderate": (0.0, 0.12),
        "high": (0.08, 0.30),
    },
    "threshold": {
        "low": (0.40, 0.70),
        "moderate": (0.25, 0.55),
        "high": (0.0, 0.15),
    },
    "sweet_spot": {
        "low": (0.40, 0.70),
        "moderate": (0.30, 0.60),
        "high": (0.0, 0.12),
    },
}
TOLERANCE = 0.05
MIN_KNOWN_S = 7200
MIN_COVERAGE = 0.6
EASY_WEEK_SHARE = 0.10
NOTE = (
    "Planned endurance time (run, ride) by 3-zone band; strength excluded. "
    "Reference range of the training model, not a target. Units without parseable "
    "steps count by planned intensity, else by session focus (approximate); "
    "basis_seconds names the basis."
)
Estimator = Callable[[Mapping[str, Any]], WorkoutEstimate]


def _unit_seconds(unit: Mapping[str, Any], estimate: WorkoutEstimate) -> float:
    if estimate.duration_s is not None:
        return estimate.duration_s
    return planned_seconds(unit)


def _add_unit(
    weeks: dict[date, dict[str, Any]], unit: Mapping[str, Any], estimate: Estimator
) -> None:
    """Add one planned run or ride unit to the sums of its ISO week."""
    start = _monday(unit)
    if start is None or planned_sport_environment(unit)[0] not in {
        Sport.RUN,
        Sport.RIDE,
    }:
        return
    week = weeks.setdefault(
        start,
        {
            "week_start": start.isoformat(),
            "seconds": dict.fromkeys(BANDS, 0.0),
            "uncovered_s": 0.0,
            "basis_seconds": {},
            "local_ids": [],
            "dates": [],
        },
    )
    _add_time(week, unit, estimate(unit))
    week["local_ids"].append(str(unit.get("local_id") or unit.get("id")))
    week["dates"].append(
        iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")
    )


def _add_time(
    week: dict[str, Any], unit: Mapping[str, Any], result: WorkoutEstimate
) -> None:
    """Band time from the steps; without parseable steps from intensity or focus."""
    if result.band_seconds is not None:
        for band, seconds in result.band_seconds.items():
            week["seconds"][band] += seconds
        _add_basis(week, unit_intensity.STEPS, sum(result.band_seconds.values()))
        return
    seconds = _unit_seconds(unit, result)
    fallback = None if result.steps else unit_intensity.unit_band(unit)
    if fallback is None or not seconds:
        week["uncovered_s"] += seconds
        return
    band, basis = fallback
    week["seconds"][band] += seconds
    _add_basis(week, basis, seconds)


def _add_basis(week: dict[str, Any], basis: str, seconds: float) -> None:
    week["basis_seconds"][basis] = week["basis_seconds"].get(basis, 0.0) + seconds


def planned_weeks(
    units: Sequence[Mapping[str, Any]],
    estimate: Estimator,
    today: date,
    completed: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Planned band seconds per ISO week of the run and ride units, oldest first.

    The running week adds the completed run and ride days (zone times of the
    weekly progress report, ``ZONE_MAPPING``; completed time without zone times
    is uncovered) to the remaining planned days and is labelled
    ``running_week.RUNNING_WEEK_BASIS``. Without ``completed`` (None) it stays partial.
    """
    weeks: dict[date, dict[str, Any]] = {}
    for unit in running_week.without_done_today(units, completed or (), today):
        _add_unit(weeks, unit, estimate)
    current = running_week.week_start(today)
    if completed is not None and current in weeks:
        _add_completed(weeks[current], completed, today)
    return [
        _summary(
            weeks[start],
            start < today and not (completed is not None and start == current),
        )
        for start in sorted(weeks)
    ]


def _add_completed(
    week: dict[str, Any], completed: Sequence[Mapping[str, Any]], today: date
) -> None:
    """Add this week's completed run and ride days to ``week``."""
    rows = [
        row
        for row in running_week.completed_this_week(completed, today)
        if row.get("sport") in {Sport.RUN.value, Sport.RIDE.value}
    ]
    measured = intensity_3zone(rows)["seconds"] or {}
    for band, seconds in measured.items():
        week["seconds"][band] += seconds
    total = sum(number(row.get("moving_duration_s")) or 0.0 for row in rows)
    week["uncovered_s"] += max(total - sum(measured.values()), 0.0)
    week["basis"] = running_week.RUNNING_WEEK_BASIS


def _summary(week: dict[str, Any], partial: bool) -> dict[str, Any]:
    known = sum(week["seconds"].values())
    total = known + week["uncovered_s"]
    shares = (
        {band: round(seconds / known, 3) for band, seconds in week["seconds"].items()}
        if known
        else None
    )
    return {
        "week_start": week["week_start"],
        "partial": partial,
        "basis": week.get("basis", "planned"),
        "seconds": {band: round(seconds) for band, seconds in week["seconds"].items()},
        "shares": shares,
        "uncovered_s": round(week["uncovered_s"]),
        "basis_seconds": {
            basis: round(seconds) for basis, seconds in week["basis_seconds"].items()
        },
        "approximate": bool(week["basis_seconds"].get(unit_intensity.SESSION_FOCUS)),
        "coverage": round(known / total, 3) if total else None,
        "local_ids": sorted(week["local_ids"]),
        "dates": sorted(set(week["dates"])),
    }


def _label(week: Mapping[str, Any]) -> str:
    if week["basis"] == running_week.RUNNING_WEEK_BASIS:
        return running_week.RUNNING_WEEK_BASIS.capitalize()
    return "Planned week"


def _outside(share: float, bounds: tuple[float, float]) -> float:
    """Distance of ``share`` beyond its range, 0 inside."""
    return max(bounds[0] - share, share - bounds[1], 0.0)


def _judged(week: Mapping[str, Any]) -> bool:
    known = sum(week["seconds"].values())
    # An easy week (recovery, taper, base) is not a model deviation.
    easy = week["shares"] is not None and (
        week["shares"]["moderate"] + week["shares"]["high"] < EASY_WEEK_SHARE
    )
    return (
        week["shares"] is not None
        and not week["partial"]
        and not easy
        and known >= MIN_KNOWN_S
        and (week["coverage"] or 0) >= MIN_COVERAGE
    )


def deviations(model: str, week: Mapping[str, Any]) -> dict[str, float]:
    """Bands whose share is clearly outside the model's range, with the distance."""
    ranges = MODEL_RANGES.get(model)
    if ranges is None or not _judged(week):
        return {}
    return {
        band: round(distance, 3)
        for band, bounds in ranges.items()
        if (distance := _outside(week["shares"][band], bounds)) > TOLERANCE
    }


def distribution_findings(
    model: str, weeks: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One non-blocking note per planned week that clearly deviates from the model."""
    findings = []
    for week in weeks:
        off = deviations(model, week)
        if not off:
            continue
        findings.append(
            {
                "code": CODE,
                "blocking": False,
                "evidence_strength": plan_checks.EVIDENCE[CODE],
                "dates": week["dates"],
                "local_ids": week["local_ids"],
                "message": (
                    f"{_label(week)} of {week['week_start']} deviates clearly from the "
                    f"{model} reference range in: {', '.join(off)}."
                    + (
                        " Partly approximate: from session focus."
                        if week["approximate"]
                        else ""
                    )
                ),
                "evidence": {
                    "model": model,
                    "model_evidence": EVIDENCE[model],
                    "week_start": week["week_start"],
                    "basis": week["basis"],
                    "shares": week["shares"],
                    "seconds": week["seconds"],
                    "uncovered_s": week["uncovered_s"],
                    "basis_seconds": week["basis_seconds"],
                    "approximate": week["approximate"],
                    "reference_ranges": MODEL_RANGES[model],
                    "deviating_bands": off,
                    "zone_mapping": ZONE_MAPPING,
                },
            }
        )
    return findings


def brief_distribution(
    model: str, weeks: Sequence[Mapping[str, Any]], limit: int
) -> dict[str, Any] | None:
    """Planned distribution of the next planned weeks for the planning brief."""
    if not weeks:
        return None
    return {
        "source": "derived from planned workout steps, local plan",
        "note": NOTE,
        "reference_ranges": MODEL_RANGES.get(model),
        "model_evidence": EVIDENCE.get(model),
        "zone_mapping": ZONE_MAPPING,
        "weeks": [
            {
                key: week[key]
                for key in (
                    "week_start",
                    "partial",
                    "basis",
                    "seconds",
                    "shares",
                    "uncovered_s",
                    "basis_seconds",
                    "approximate",
                    "coverage",
                )
            }
            for week in weeks[:limit]
        ],
    }
