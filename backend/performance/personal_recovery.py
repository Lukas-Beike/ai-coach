"""Personal recovery distributions, separated by provider and measurement field."""

import math
from datetime import date, timedelta
from statistics import median, quantiles
from typing import Any

from backend.performance.recovery import (
    dated_garmin_recovery_records,
    garmin_recovery_metric,
)


def _number(value: Any) -> float | None:
    return (
        float(value) if type(value) in {int, float} and math.isfinite(value) else None
    )


def personal_recovery(
    wellness: list[dict[str, Any]],
    garmin: dict[str, Any],
    profile: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    cutoff = (today - timedelta(days=42)).isoformat()
    history_start = (today - timedelta(days=today.weekday(), weeks=7)).isoformat()
    current_day = today.isoformat()
    groups: dict[tuple[str, str, str], dict[str, float]] = {}

    def add(
        day: str, source: str, metric: str, field: str, value: Any, scale: float = 1
    ) -> None:
        number = _number(value)
        if number is None or number <= 0 or not history_start <= day <= current_day:
            return
        number /= scale
        if (
            metric == "sleep"
            and number > 24
            or metric == "resting_hr"
            and not 20 <= number <= 230
        ):
            return
        groups.setdefault((source, metric, field), {})[day] = number

    for row in wellness:
        day = str(row.get("id") or row.get("date") or "")[:10]
        add(day, "Intervals.icu", "sleep", "sleepSecs", row.get("sleepSecs"), 3600)
        add(day, "Intervals.icu", "resting_hr", "restingHR", row.get("restingHR"))
        # Unknown HRV measurement methods cannot support a homogeneous baseline.
        if row.get("hrv_method") in {"RMSSD", "SDNN"}:
            add(day, "Intervals.icu", "hrv", str(row["hrv_method"]), row.get("hrv"))
    specifications = (
        ("sleep", "sleep", "sleepTimeSeconds", 3600),
        ("resting_hr", "resting_hr", "restingHeartRate", 1),
        ("hrv", "hrv", "lastNightAvg", 1),
    )
    for section, metric, field, scale in specifications:
        for day, record in sorted(
            dated_garmin_recovery_records(garmin.get(section)), key=lambda item: item[0]
        ):
            if not history_start <= day <= current_day:
                continue
            value, observed = garmin_recovery_metric(
                {section: [record]}, section, (field,)
            )
            if observed == day:
                add(day, "Garmin Connect", metric, field, value, scale)
    baselines = []
    for (source, metric, field), records in sorted(groups.items()):
        observed = max(records)
        # Today's value never influences its own normal range.
        prior = [value for day, value in records.items() if cutoff <= day < observed]
        latest = records[observed]
        current = observed >= (today - timedelta(days=1)).isoformat()
        baseline: dict[str, Any] = {
            "source": source,
            "metric": metric,
            "measurement": field,
            "value": latest,
            "observed_at": observed,
            "window_days": 42,
            "nights": len(prior),
            "unit": {"sleep": "h", "hrv": "ms", "resting_hr": "bpm"}[metric],
            "status": "insufficient_data",
            "history": [
                {"date": day, "value": value} for day, value in sorted(records.items())
            ],
        }
        if len(prior) >= 14 and current:
            lower, _, upper = quantiles(prior, n=4, method="inclusive")
            baseline.update(
                status="provisional" if len(prior) < 28 else "ok",
                median=median(prior),
                lower=lower,
                upper=upper,
                position="below"
                if latest < lower
                else "above"
                if latest > upper
                else "within",
            )
        else:
            baseline["reason"] = (
                "Messung veraltet."
                if not current
                else "Mindestens 14 frühere passende Nächte erforderlich."
            )
        baselines.append(baseline)
    try:
        target = float(profile.get("sleep_target_hours") or "nan")
    except (ValueError, TypeError):
        target = float("nan")
    deficits = []
    if math.isfinite(target) and 4 <= target <= 12:
        for (source, metric, field), records in sorted(groups.items()):
            if metric != "sleep":
                continue
            selected = {
                day: value
                for day, value in records.items()
                if (today - timedelta(days=6)).isoformat() <= day <= current_day
            }
            deficits.append(
                {
                    "source": source,
                    "measurement": field,
                    "known_nights": len(selected),
                    "target_hours": target,
                    "deficit_hours": round(
                        sum(max(0, target - value) for value in selected.values()), 2
                    ),
                    "status": "ok" if len(selected) == 7 else "partial",
                }
            )
    return {
        "method": "personal-quartiles-v1",
        "as_of": current_day,
        "baselines": baselines,
        "sleep_deficits": deficits,
        "sleep_target_hours": target if math.isfinite(target) else None,
        "regularity": {
            "status": "insufficient_data",
            "reason": "Keine geprüften datierten Schlafbeginn- und Endzeiten verfügbar.",
        },
        "note": "Persönliche Quartile beschreiben Abweichungen, keine medizinische Trainingsfreigabe. Krankheit und Schmerzen separat berücksichtigen. Quellen und Messfelder werden nicht gemischt; lange Nächte gleichen Defizite nicht rechnerisch aus.",
    }
