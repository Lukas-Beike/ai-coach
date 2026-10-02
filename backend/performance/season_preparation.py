"""Season evidence and explicit, read-only local load scenarios."""

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any

from backend.errors import AppError
from backend.performance.training_report import activity_day, canonical_rows, number
from backend.planning.competitions import supported_competition_sport
from backend.planning.season import season_plan_summary


def season_preparation(
    snapshot: dict[str, Any],
    competitions: list[dict[str, Any]],
    today: date,
    timezone: str = "UTC",
    observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = season_plan_summary(competitions, today)
    rows, _ = canonical_rows(snapshot)
    for event in result["events"]:
        sport = supported_competition_sport(event.get("sport"))
        eligible = [
            row
            for row in rows
            if row.get("type") == sport
            and (today - timedelta(days=83)).isoformat()
            <= activity_day(row, timezone)
            <= today.isoformat()
        ]
        longest = sorted(
            [row for row in eligible if number(row.get("moving_time"))],
            key=lambda row: number(row.get("moving_time")) or -1,
            reverse=True,
        )[:3]
        weeks = _preparation_weeks(eligible, today, timezone)
        analyses = {row["activity_id"]: row for row in (observations or [])}
        event["preparation"] = {
            "status": "observations" if eligible else "insufficient_data",
            "sport": sport,
            "sessions_84_days": len(eligible),
            "weeks": weeks,
            "weeks_with_recorded_training": sum(
                bool(week["sessions"]) for week in weeks
            ),
            "long_sessions": [
                {
                    "activity_id": str(row.get("id")),
                    "date": activity_day(row, timezone),
                    "duration_seconds": number(row.get("moving_time")),
                    "distance_meters": number(row.get("distance")),
                    "name": str(row.get("name") or "Training")[:200],
                    "aerobic": (analyses.get(str(row.get("id"))) or {}).get("aerobic"),
                }
                for row in longest
            ],
            "note": "Calendar phase and observed preparation are separate. Distance, terrain, intensity and fueling rehearsal require explicit evidence; no race-time or readiness score.",
        }
    return {
        **result,
        "method": "season-observed-training-v1",
        "observed_at": snapshot.get("synced_at"),
        "timezone": timezone,
    }


def load_scenarios(
    snapshot: dict[str, Any],
    plan: dict[str, Any],
    today: date,
    values: dict[str, Any],
    timezone: str = "UTC",
) -> dict[str, Any]:
    end, scale, taper = _scenario_values(values, today)
    wellness = [
        row
        for row in snapshot.get("recent_wellness", [])
        if str(row.get("id") or "").startswith((today - timedelta(days=1)).isoformat())
    ]
    latest = wellness[-1] if wellness else {}
    ctl, atl = number(latest.get("ctl")), number(latest.get("atl"))
    basis = {
        "as_of": (today - timedelta(days=1)).isoformat(),
        "ctl": ctl,
        "atl": atl,
        "source": "Intervals.icu recorded wellness",
    }
    activities, _ = canonical_rows(snapshot)
    completed_today = [
        row for row in activities if activity_day(row, timezone) == today.isoformat()
    ]
    base = {
        "method": "explicit-local-exponential-model-v1",
        "basis": basis,
        "parameters": {"ctl_days": 42, "atl_days": 7},
        "assumptions": "Local standard time constants, not verified provider configuration. Unplanned days are modeled as zero planned load. Missing planned load blocks both scenarios. CTL/TSB do not predict performance, health or race time.",
        "input_sha256": hashlib.sha256(
            json.dumps(
                {
                    "snapshot": snapshot.get("synced_at"),
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
        <= str(row.get("start_date_local") or row.get("date") or "")[:10]
        <= end.isoformat()
    ]
    if any(number(row.get("icu_training_load")) is None for row in calendar):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Mindestens einer geplanten Einheit fehlt die Belastung.",
        }
    if any(number(row.get("icu_training_load")) is None for row in completed_today):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Eine heute absolvierte Einheit hat keine bekannte Belastung.",
        }
    actual_today_load = sum(float(row["icu_training_load"]) for row in completed_today)
    curves = [
        _scenario_curve(
            calendar,
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
        "apply": "Request an adaptive preview using current planning state, then explicitly approve. Simulation does not change local or remote workouts.",
    }


def _preparation_weeks(eligible: list[dict], today: date, timezone: str) -> list[dict]:
    weeks = []
    for offset in range(12):
        start = today - timedelta(days=83 - 7 * offset)
        end = start + timedelta(days=6)
        measured = [
            row
            for row in eligible
            if start.isoformat() <= activity_day(row, timezone) <= end.isoformat()
        ]
        durations = [
            value
            for row in measured
            if (value := number(row.get("moving_time"))) is not None
        ]
        distances = [
            value
            for row in measured
            if (value := number(row.get("distance"))) is not None
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
        scale = float(values.get("load_scale", 1))
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


def _scenario_curve(
    calendar: list[dict],
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
            float(row["icu_training_load"])
            for row in calendar
            if str(row.get("start_date_local") or row.get("date") or "").startswith(
                day.isoformat()
            )
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
