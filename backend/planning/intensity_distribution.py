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
from datetime import date, timedelta
from typing import Any

from backend.activities.workout_load import BANDS, WorkoutEstimate
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.vocabulary import Sport
from backend.performance.progress_report import ZONE_MAPPING
from backend.planning import plan_checks
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
    "Reference range of the training model, not a target."
)
Estimator = Callable[[Mapping[str, Any]], WorkoutEstimate]


def _monday(unit: Mapping[str, Any]) -> date | None:
    try:
        day = date.fromisoformat(
            iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")
        )
    except ValueError:
        return None
    return day - timedelta(days=day.weekday())


def _unit_seconds(unit: Mapping[str, Any], estimate: WorkoutEstimate) -> float:
    if estimate.duration_s is not None:
        return estimate.duration_s
    seconds = number(unit.get("planned_duration_s"))
    minutes = number(unit.get("duration_minutes"))
    if seconds is None and minutes is not None:
        seconds = minutes * 60
    return seconds or 0.0


def planned_weeks(
    units: Sequence[Mapping[str, Any]], estimate: Estimator, today: date
) -> list[dict[str, Any]]:
    """Planned band seconds per ISO week of the run and ride units, oldest first.

    A week that began before ``today`` is partial: its elapsed days are not in
    the planned units, so it is shown but never judged.
    """
    weeks: dict[date, dict[str, Any]] = {}
    for unit in units:
        start = _monday(unit)
        if start is None or planned_sport_environment(unit)[0] not in {
            Sport.RUN,
            Sport.RIDE,
        }:
            continue
        week = weeks.setdefault(
            start,
            {
                "week_start": start.isoformat(),
                "seconds": dict.fromkeys(BANDS, 0.0),
                "uncovered_s": 0.0,
                "local_ids": [],
                "dates": [],
            },
        )
        result = estimate(unit)
        if result.band_seconds is None:
            week["uncovered_s"] += _unit_seconds(unit, result)
        else:
            for band, seconds in result.band_seconds.items():
                week["seconds"][band] += seconds
        week["local_ids"].append(str(unit.get("local_id") or unit.get("id")))
        week["dates"].append(
            iso_date_prefix(unit.get("date") or unit.get("starts_at_local") or "")
        )
    return [_summary(weeks[start], start < today) for start in sorted(weeks)]


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
        "seconds": {band: round(seconds) for band, seconds in week["seconds"].items()},
        "shares": shares,
        "uncovered_s": round(week["uncovered_s"]),
        "coverage": round(known / total, 3) if total else None,
        "local_ids": sorted(week["local_ids"]),
        "dates": sorted(set(week["dates"])),
    }


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
                    f"Planned week of {week['week_start']} deviates clearly from the "
                    f"{model} reference range in: {', '.join(off)}."
                ),
                "evidence": {
                    "model": model,
                    "model_evidence": EVIDENCE[model],
                    "week_start": week["week_start"],
                    "shares": week["shares"],
                    "seconds": week["seconds"],
                    "uncovered_s": week["uncovered_s"],
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
                    "seconds",
                    "shares",
                    "uncovered_s",
                    "coverage",
                )
            }
            for week in weeks[:limit]
        ],
    }
