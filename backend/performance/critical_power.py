"""Critical Power and Critical Speed model estimates (evidence card M4).

Two-parameter models fitted to the best 3, 7 and 12 min efforts of the last 28
days from full-resolution streams (training-file protocol, card M4):
``work(t) = CP × t + W′`` for cycling and ``distance(t) = CS × t + D′`` for
running. The primary fit is least squares of work or distance on time; the
power-versus-1/t fit and leave-one-out fits are reported only as sensitivity.
Every limit below was fixed on the card before any real-data fit. The result is
always an experimental model estimate and never feeds FTP or zones.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Final

METHOD_ID: Final = "critical-power-speed"
METHOD_VERSION: Final = 1
WINDOW_DAYS: Final = 28
EFFORT_SECONDS: Final = (180, 420, 720)
# Efforts in one session count separately only with this much recovery between.
MIN_RECOVERY_SECONDS: Final = 1800
MAX_RELATIVE_RESIDUAL: Final = 0.03
PLAUSIBLE: Final = {
    "ride": {"intercept": (1000.0, 50000.0), "slope": (50.0, 600.0)},
    "run": {"intercept": (10.0, 500.0), "slope": (1.5, 7.0)},
}
_FIELDS: Final = {
    "ride": ("watts", "cp_watts", "w_prime_joules", 1, 0),
    "run": ("speed_mps", "cs_mps", "d_prime_meters", 3, 1),
}
SCOPE: Final = (
    "Experimentelle Modellschätzung aus den besten 3-, 7- und 12-Minuten-"
    "Belastungen der letzten 28 Tage (Trainingsdatei-Protokoll, Karte M4); "
    "Ausbelastung, Testabsicht, Sensor und Kalibrierung sind unbekannt. CP/CS "
    "ist keine FTP, Schwelle, MLSS oder Zonengrenze; W′/D′ ist keine gemessene "
    "anaerobe Kapazität; keine Langstreckenprognose."
)


def critical_power_speed(
    records: Sequence[dict[str, Any]], today: date, *, input_fingerprint: str
) -> dict[str, Any]:
    """Fit cycling CP per environment and outdoor running CS from session curves.

    ``records`` are the session curve records of the 28-day window.
    """
    fits = [
        _fit(records, "ride", "outdoor", today),
        _fit(records, "ride", "indoor", today),
        _fit(records, "run", "outdoor", today),
    ]
    return {
        "method": METHOD_ID,
        "method_version": METHOD_VERSION,
        "card": "M4",
        "classification": "model estimate",
        "status": "experimental",
        "window_days": WINDOW_DAYS,
        "protocol": "best 180, 420 and 720 s from training files",
        "fit": "least squares of work or distance on time",
        "test_intent": "unknown",
        "sensor": "unknown",
        "calibration": "unknown",
        "input_fingerprint": input_fingerprint,
        "fits": fits,
        "scope": SCOPE,
    }


def fit_line(
    durations: Sequence[float], values: Sequence[float]
) -> tuple[float, float]:
    """Least-squares ``value = slope × t + intercept``; returns (slope, intercept)."""
    count = len(durations)
    mean_t = sum(durations) / count
    mean_v = sum(values) / count
    spread = sum((t - mean_t) ** 2 for t in durations)
    slope = (
        sum((t - mean_t) * (v - mean_v) for t, v in zip(durations, values, strict=True))
        / spread
    )
    return slope, mean_v - slope * mean_t


def _fit(
    records: Sequence[dict[str, Any]], sport: str, environment: str, today: date
) -> dict[str, Any]:
    field, slope_key, intercept_key, slope_digits, intercept_digits = _FIELDS[sport]
    efforts = _select_efforts(records, sport, environment, field)
    result: dict[str, Any] = {
        "sport": sport,
        "environment": environment,
        "efforts": efforts,
    }
    if len(efforts) < len(EFFORT_SECONDS):
        return {
            **result,
            "status": "insufficient_data",
            "reason": "Weniger als drei unabhängige 3-, 7- und 12-Minuten-Belastungen in 28 Tagen.",
        }
    result["data_age_days"] = (
        today - min(date.fromisoformat(str(effort["date"])) for effort in efforts)
    ).days
    durations = [float(effort["duration_seconds"]) for effort in efforts]
    rates = [float(effort[field]) for effort in efforts]
    # Work in J or distance in m: the mean power or speed times the duration.
    amounts = [rate * t for rate, t in zip(rates, durations, strict=True)]
    slope, intercept = fit_line(durations, amounts)
    if slope <= 0 or intercept <= 0:
        return {
            **result,
            "status": "withheld",
            "reason": "Nicht positiver Modellparameter.",
        }
    residuals = [
        abs(amount - (slope * t + intercept)) / amount
        for amount, t in zip(amounts, durations, strict=True)
    ]
    if max(residuals) > MAX_RELATIVE_RESIDUAL:
        return {**result, "status": "withheld", "reason": "Modellabweichung über 3 %."}
    leave_one_out = []
    for left_out in range(len(efforts)):
        kept = [index for index in range(len(efforts)) if index != left_out]
        loo_slope, loo_intercept = fit_line(
            [durations[index] for index in kept], [amounts[index] for index in kept]
        )
        if loo_slope <= 0 or loo_intercept <= 0:
            return {
                **result,
                "status": "withheld",
                "reason": "Ohne eine Belastung ergibt sich ein nicht positiver Parameter.",
            }
        leave_one_out.append(
            {
                "left_out_seconds": int(durations[left_out]),
                slope_key: round(loo_slope, slope_digits),
                intercept_key: round(loo_intercept, intercept_digits),
            }
        )
    limits = PLAUSIBLE[sport]
    if not (
        limits["slope"][0] <= slope <= limits["slope"][1]
        and limits["intercept"][0] <= intercept <= limits["intercept"][1]
    ):
        return {
            **result,
            "status": "withheld",
            "reason": "Parameter außerhalb des Plausibilitätsbereichs.",
        }
    inverse_intercept, inverse_slope = _inverse_time_fit(durations, rates)
    return {
        **result,
        "status": "ok",
        slope_key: round(slope, slope_digits),
        intercept_key: round(intercept, intercept_digits),
        "residuals": [
            {"duration_seconds": int(t), "relative": round(residual, 4)}
            for t, residual in zip(durations, residuals, strict=True)
        ],
        "sensitivity": {
            "inverse_time": {
                slope_key: round(inverse_intercept, slope_digits),
                intercept_key: round(inverse_slope, intercept_digits),
            },
            "leave_one_out": leave_one_out,
        },
    }


def _inverse_time_fit(
    durations: Sequence[float], rates: Sequence[float]
) -> tuple[float, float]:
    """Least-squares ``rate = CP + W′ / t``; returns (CP, W′)."""
    w_prime, critical = fit_line([1 / t for t in durations], rates)
    return critical, w_prime


def _select_efforts(
    records: Sequence[dict[str, Any]], sport: str, environment: str, field: str
) -> list[dict[str, Any]]:
    """Pick the best effort per duration, longest first, keeping efforts independent.

    Each later pick is the best candidate that comes from another session or
    lies at least 30 min apart from every earlier pick of the same session.
    """
    profile_key, points_key = (
        ("power_profile", "duration_curve")
        if sport == "ride"
        else ("running_profile", "speed")
    )
    chosen: list[dict[str, Any]] = []
    for duration in sorted(EFFORT_SECONDS, reverse=True):
        candidates = [
            {
                "duration_seconds": duration,
                field: point[field],
                "start_seconds": point.get("start_seconds"),
                "activity_id": row.get("activity_id"),
                "date": row.get("date"),
                "source": row.get("source"),
            }
            for row in records
            if row.get("sport") == sport and row.get("environment") == environment
            for point in (row.get(profile_key) or {}).get(points_key, [])
            if point.get("duration_seconds") == duration
            and point.get(field) is not None
            and point.get("start_seconds") is not None
        ]
        candidates.sort(
            key=lambda item: (
                -float(item[field]),
                str(item["date"] or ""),
                str(item["activity_id"] or ""),
            )
        )
        pick = next(
            (
                item
                for item in candidates
                if all(_independent(item, other) for other in chosen)
            ),
            None,
        )
        if pick is not None:
            chosen.append(pick)
    return sorted(chosen, key=lambda item: item["duration_seconds"])


def _independent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["activity_id"] != right["activity_id"]:
        return True
    first, second = sorted((left, right), key=lambda item: float(item["start_seconds"]))
    gap = float(second["start_seconds"]) - (
        float(first["start_seconds"]) + first["duration_seconds"]
    )
    return gap >= MIN_RECOVERY_SECONDS
