"""Season evidence and explicit, read-only local load scenarios."""

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import (
    ActivitySummary,
    stored_activity_key,
    summary_is_indoor,
    summary_local_date,
)
from backend.athlete.local_date import iso_date_prefix
from backend.athlete.measurements import number
from backend.canonical.planning_fields import PLANNED_INTENSITY as PLANNED_INTENSITY_KEY
from backend.canonical.planning_fields import PLANNED_LOAD as PLANNED_LOAD_KEY
from backend.canonical.stored_sports import resolve_competition_sport
from backend.canonical.vocabulary import Environment, ProviderId
from backend.errors import AppError
from backend.performance.season_inputs import SeasonLoadInputs
from backend.planning.season import season_plan_summary
from backend.providers.source_labels import SourceView, provider_label

ActivitySummariesBetween = Callable[[date, date], Sequence[ActivitySummary]]


ACTIVITY_SOURCE = provider_label(
    ProviderId.INTERVALS, SourceView.SEASON_PREPARATION_ACTIVITY
)
PREPARATION_WEEKS = 12
PLANNED_LOAD_ESTIMATE_SOURCE = (
    f"estimated from planned duration and {PLANNED_INTENSITY_KEY} (hours x IF^2 x 100)"
)


def season_preparation(
    synced_at: str | None,
    competitions: list[dict[str, Any]],
    today: date,
    timezone: str = "UTC",
    observations: list[dict[str, Any]] | None = None,
    *,
    activity_summaries: ActivitySummariesBetween,
) -> dict[str, Any]:
    """Summarise the preparation evidence of every season event.

    ``activity_summaries`` returns the activity summaries around the given
    inclusive local dates; it is called once for the span of all event windows.
    ``synced_at`` is the canonical Intervals.icu sync time.
    """
    result = season_plan_summary(competitions, today)
    windows = [_evidence_window(event, today) for event in result["events"]]
    rows = (
        list(
            activity_summaries(
                min(start for start, _ in windows), max(end for _, end in windows)
            )
        )
        if windows
        else []
    )
    for event, (window_start, window_end) in zip(result["events"], windows):
        sport = _competition_sport(event)
        indoor = _competition_indoor(event)
        eligible = [
            row
            for row in rows
            if row.get("sport") == sport
            and summary_is_indoor(row) == indoor
            and window_start.isoformat()
            <= summary_local_date(row, timezone)
            <= window_end.isoformat()
        ]
        longest = sorted(
            [row for row in eligible if number(row.get("moving_duration_s"))],
            key=lambda row: number(row.get("moving_duration_s")) or -1,
            reverse=True,
        )[:3]
        weeks = _preparation_weeks(eligible, window_start, timezone)
        analyses = {row["activity_id"]: row for row in (observations or [])}
        target_context = _target_context(event)
        event["preparation"] = {
            "status": "observations" if eligible else "insufficient_data",
            "sport": sport,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "sessions_84_days": len(eligible),
            "weeks": weeks,
            "weeks_with_recorded_training": sum(
                bool(week["sessions"]) for week in weeks
            ),
            "target_context": _target_context(event),
            "weekly_observed_volume": _weekly_volume(weeks),
            "long_session_evidence": _long_session_evidence(longest),
            "target_distance_comparison": _target_distance_comparison(
                target_context, longest
            ),
            "specificity_evidence": _specificity_evidence(eligible, analyses),
            "source_counts": {
                ACTIVITY_SOURCE: len(eligible),
                "cached activity analyses": len(
                    [row for row in eligible if stored_activity_key(row) in analyses]
                ),
            },
            "long_sessions": [
                {
                    "activity_id": row["id"],
                    "date": summary_local_date(row, timezone),
                    "duration_seconds": number(row.get("moving_duration_s")),
                    "distance_meters": number(row.get("distance_m")),
                    "name": str(row.get("name") or "Training")[:200],
                    "aerobic": (analyses.get(stored_activity_key(row)) or {}).get(
                        "aerobic"
                    ),
                }
                for row in longest
            ],
            "note": "Calendar phase and observed preparation are separate. Distance, terrain, intensity and fueling rehearsal require explicit evidence; no race-time or readiness score.",
        }
    return {
        **result,
        "method": "season-observed-training-v1",
        "observed_at": synced_at,
        "timezone": timezone,
    }


def _competition_sport(event: dict[str, Any]) -> str | None:
    """Return the canonical sport of a supported competition, else None."""
    stored = resolve_competition_sport(event.get("sport"), event.get("environment"))
    return None if stored is None else stored.sport.value


def _competition_indoor(event: dict[str, Any]) -> bool:
    """Return True when the competition is indoor or virtual."""
    stored = resolve_competition_sport(event.get("sport"), event.get("environment"))
    return stored is not None and stored.environment in {
        Environment.INDOOR,
        Environment.VIRTUAL,
    }


def _target_context(event: dict[str, Any]) -> dict[str, Any]:
    raw = str(event.get("distance") or "").strip().lower()
    distance = None
    try:
        value = float(raw.replace(",", ".").replace("km", "").replace("m", "").strip())
        if "km" in raw:
            distance = value * 1000
        elif raw.endswith("m") or value >= 100:
            distance = value
    except ValueError:
        pass
    target = str(event.get("target") or "").strip()
    return {
        "sport": _competition_sport(event),
        "distance_meters": int(distance)
        if distance is not None and distance.is_integer()
        else distance,
        "distance_confirmed": distance is not None,
        "target": target or None,
        "target_confirmed": bool(target),
        "source": "confirmed local competition",
    }


def _weekly_volume(weeks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "observations"
        if any(week["sessions"] for week in weeks)
        else "insufficient_data",
        "weeks_with_sessions": sum(bool(week["sessions"]) for week in weeks),
        "weeks_total": len(weeks),
        "sessions": sum(week["sessions"] for week in weeks),
        "duration_seconds": sum(week["duration_seconds"] or 0 for week in weeks)
        or None,
        "duration_known_sessions": sum(
            week["duration_known_sessions"] for week in weeks
        ),
        "distance_meters": sum(week["distance_meters"] or 0 for week in weeks) or None,
        "distance_known_sessions": sum(
            week["distance_known_sessions"] for week in weeks
        ),
        "source": ACTIVITY_SOURCE,
    }


def _long_session_evidence(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    durations = [
        value
        for row in sessions
        if (value := number(row.get("moving_duration_s"))) is not None
    ]
    distances = [
        value
        for row in sessions
        if (value := number(row.get("distance_m"))) is not None
    ]
    return {
        "status": "observations" if sessions else "insufficient_data",
        "sessions": len(sessions),
        "duration_seconds": max(durations) if durations else None,
        "duration_known_sessions": len(durations),
        "distance_meters": max(distances) if distances else None,
        "distance_known_sessions": len(distances),
        "source": ACTIVITY_SOURCE,
    }


def _target_distance_comparison(
    target_context: dict[str, Any], sessions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    target = target_context.get("distance_meters")
    distances = [
        value
        for row in sessions
        if (value := number(row.get("distance_m"))) is not None
    ]
    if target is None or not distances:
        return {
            "status": "unknown",
            "target_distance_meters": target,
            "observed_long_session_distance_meters": max(distances)
            if distances
            else None,
            "source": "confirmed competition and recorded activities",
        }
    return {
        "status": "observed",
        "target_distance_meters": target,
        "observed_long_session_distance_meters": max(distances),
        "source": "confirmed competition and recorded activities",
    }


def _specificity_evidence(
    eligible: Sequence[Mapping[str, Any]], analyses: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    cached = [
        analyses[stored_activity_key(row)]
        for row in eligible
        if stored_activity_key(row) in analyses
    ]
    return {
        "status": "observations" if cached else "insufficient_data",
        "cached_analyses": len(cached),
        "known_dimensions": {
            key: sum((item.get(key) or {}).get("status") == "ok" for item in cached)
            for key in ("aerobic", "power_profile", "interval_quality")
        },
        "source": "cached activity analyses",
    }


def load_scenarios(
    synced_at: str | None,
    plan: dict[str, Any],
    today: date,
    values: dict[str, Any],
    *,
    inputs: SeasonLoadInputs,
) -> dict[str, Any]:
    """Model the load curves of the current plan and one explicit alternative.

    ``inputs`` carries yesterday's CTL/ATL and today's completed activities, read
    by ``read_season_load_inputs``; ``synced_at`` is the canonical Intervals.icu
    sync time.
    """
    end, scale, taper = _scenario_values(values, today)
    ctl, atl = (
        number(observation.value.value) if observation is not None else None
        for observation in (inputs.ctl, inputs.atl)
    )
    basis = {
        "as_of": inputs.basis_day.isoformat(),
        "ctl": ctl,
        "atl": atl,
        "source": inputs.source_label(),
    }
    completed_today = list(inputs.completed_today)
    base = {
        "method": "explicit-local-exponential-model-v1",
        "basis": basis,
        "parameters": {"ctl_days": 42, "atl_days": 7},
        "assumptions": "Local standard time constants, not verified provider configuration. Unplanned days are modeled as zero planned load. Planned units without a recorded load use a labelled duration-and-intensity estimate; units with neither block both scenarios. CTL/TSB do not predict performance, health or race time.",
        "input_sha256": hashlib.sha256(
            json.dumps(
                {
                    "snapshot": synced_at,
                    "basis": basis,
                    "completed_today": completed_today,
                    "plan": plan,
                    "values": values,
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest(),
    }
    if ctl is None or atl is None:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Datierter CTL-/ATL-Ausgangszustand von gestern fehlt.",
        }
    calendar = [
        row
        for row in plan.get("training_calendar", [])
        if not row.get("is_completed_activity")
        and not (row.get("compliance") or {}).get("actual_activity")
        and today.isoformat()
        <= iso_date_prefix(str(row.get("starts_at_local") or row.get("date") or ""))
        <= end.isoformat()
    ]
    planned_loads, estimated, missing = _planned_loads(calendar)
    if missing:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Mindestens einer geplanten Einheit fehlt die Belastung.",
            "units_without_load": missing,
            "planned_load_estimated": bool(estimated),
            "estimated_planned_units": estimated,
        }
    if any(number(row.get("training_load")) is None for row in completed_today):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Eine heute absolvierte Einheit hat keine bekannte Belastung.",
        }
    actual_today_load = sum(float(row["training_load"]) for row in completed_today)
    curves = [
        _scenario_curve(
            planned_loads,
            (today, end),
            (ctl, atl),
            (label, multiplier, taper),
            actual_today_load,
        )
        for label, multiplier in (("current", 1.0), ("alternative", scale))
    ]
    return {
        **base,
        "status": "ok",
        "curves": curves,
        "alternative": {
            "load_scale": scale,
            "taper_days": taper,
            "end": end.isoformat(),
        },
        "planned_load_estimated": bool(estimated),
        "estimated_planned_units": estimated,
        "apply": "Request an adaptive preview using current planning state, then explicitly approve. Simulation does not change local or remote workouts.",
    }


def _evidence_window(event: dict[str, Any], today: date) -> tuple[date, date]:
    """Return the 12 Monday-Sunday weeks of evidence before the competition.

    Evidence ends at the event date for completed competitions and at today
    for future ones, so a past race is judged by its own preparation.
    """
    window_end = min(today, date.fromisoformat(event["event_date"]))
    window_start = _week_start(window_end) - timedelta(weeks=PREPARATION_WEEKS - 1)
    return window_start, window_end


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _preparation_weeks(
    eligible: Sequence[Mapping[str, Any]], window_start: date, timezone: str
) -> list[dict]:
    weeks = []
    for offset in range(PREPARATION_WEEKS):
        start = window_start + timedelta(weeks=offset)
        end = start + timedelta(days=6)
        measured = [
            row
            for row in eligible
            if start.isoformat() <= summary_local_date(row, timezone) <= end.isoformat()
        ]
        durations = [
            value
            for row in measured
            if (value := number(row.get("moving_duration_s"))) is not None
        ]
        distances = [
            value
            for row in measured
            if (value := number(row.get("distance_m"))) is not None
        ]
        weeks.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "sessions": len(measured),
                "duration_seconds": sum(durations) if durations else None,
                "duration_known_sessions": len(durations),
                "distance_meters": sum(distances) if distances else None,
                "distance_known_sessions": len(distances),
            }
        )

    return weeks


def _scenario_values(values: dict, today: date) -> tuple[date, float, int]:
    try:
        end = date.fromisoformat(str(values.get("end")))
        scale = _decimal(values.get("load_scale", 1))
        taper = int(values.get("taper_days", 0))
    except (TypeError, ValueError) as exc:
        raise AppError(400, "Ungültiges Szenario.") from exc
    if (
        set(values) - {"end", "load_scale", "taper_days"}
        or not today < end <= today + timedelta(days=180)
        or not math.isfinite(scale)
        or not 0.5 <= scale <= 1.5
        or not 0 <= taper <= 21
    ):
        raise AppError(
            400, "Szenario: maximal 180 Tage, Faktor 0,5–1,5, Entlastung 0–21 Tage."
        )

    return end, scale, taper


def _decimal(value: Any) -> float:
    """Parse a number that may use a German decimal comma (for example 0,85)."""
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    return float(value)


def _planned_loads(
    calendar: list[dict],
) -> tuple[list[tuple[str, float]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (date key, load) pairs, estimated units and units without any load."""
    loads: list[tuple[str, float]] = []
    estimated: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in calendar:
        key = str(row.get("starts_at_local") or row.get("date") or "")
        day = iso_date_prefix(key)
        name = str(row.get("name") or "Training")[:200]
        load = number(row.get(PLANNED_LOAD_KEY))
        if load is None:
            load = _estimated_load(row)
            if load is None:
                missing.append({"date": day, "name": name})
                continue
            estimated.append(
                {
                    "date": day,
                    "name": name,
                    "load": round(load, 2),
                    "source": PLANNED_LOAD_ESTIMATE_SOURCE,
                }
            )
        loads.append((key, load))
    return loads, estimated, missing


def _estimated_load(row: dict[str, Any]) -> float | None:
    """TSS-like estimate: hours x IF^2 x 100, from planned duration and the activity intensity."""
    seconds = number(row.get("planned_duration_s"))
    intensity = number(row.get(PLANNED_INTENSITY_KEY))
    if not seconds or seconds <= 0 or intensity is None:
        return None
    # Intervals.icu reports intensity in percent; plain intensity factors are accepted too.
    factor = intensity / 100 if intensity > 1.5 else intensity
    if not 0 < factor <= 1.5:
        return None
    return seconds / 3600 * factor**2 * 100


def _scenario_curve(
    planned_loads: list[tuple[str, float]],
    dates: tuple[date, date],
    basis: tuple[float, float],
    scenario: tuple[str, float, int],
    actual_today_load: float,
) -> dict[str, Any]:
    today, end = dates
    ctl, atl = basis
    label, multiplier, taper = scenario
    fitness, fatigue, points = ctl, atl, []
    day = today
    while day <= end:
        load = sum(
            planned_load
            for key, planned_load in planned_loads
            if key.startswith(day.isoformat())
        )
        load *= multiplier
        if label == "alternative" and taper and 0 <= (end - day).days < taper:
            load *= 0.5
        if day == today:
            load += actual_today_load
        fitness += (load - fitness) * (1 - math.exp(-1 / 42))
        fatigue += (load - fatigue) * (1 - math.exp(-1 / 7))
        points.append(
            {
                "date": day.isoformat(),
                "load": round(load, 2),
                "ctl": round(fitness, 2),
                "atl": round(fatigue, 2),
                "tsb": round(fitness - fatigue, 2),
            }
        )
        day += timedelta(days=1)

    return {"name": label, "points": points}
