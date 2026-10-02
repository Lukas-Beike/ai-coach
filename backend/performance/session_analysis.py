"""Full-resolution session metrics with conservative eligibility rules."""

from __future__ import annotations

import math
import re
from typing import Any

METHOD = "time-weighted-session-analysis-v1"


def _number(value: Any) -> float | None:
    return (
        float(value) if type(value) in {int, float} and math.isfinite(value) else None
    )


def _samples(
    activity: dict[str, Any], sensor: str, start: float, end: float
) -> list[tuple[float, float, float]]:
    streams = activity.get("streams") or {}
    times = streams.get("time") or []
    values = streams.get(sensor) or []
    moving = streams.get("moving")
    samples: list[tuple[float, float, float]] = []
    if len(values) != len(times):
        return samples
    for index in range(len(times) - 1):
        left = max(float(times[index]), start)
        right = min(float(times[index + 1]), end)
        value = _number(values[index])
        if right <= left or times[index + 1] - times[index] > 5 or value is None:
            continue
        if moving and (index >= len(moving) or moving[index] not in {True}):
            continue
        samples.append((left, right - left, value))
    return samples


def _target(
    step: dict[str, Any], basis: dict[str, Any]
) -> tuple[str, float, float, str] | None:
    text = str(step.get("target") or "").upper()
    if step.get("ramp") or text.startswith("Z"):
        return None
    if step.get("kind") == "pace" and ":" in text:
        parts = re.findall(r"(\d+):([0-5]\d)", text)
        distances = {
            "/KM": 1000,
            "/MI": 1609.344,
            "/100M": 100,
            "/100Y": 91.44,
            "/500M": 500,
            "/400M": 400,
            "/250M": 250,
        }
        distance = next(
            (value for unit, value in distances.items() if unit in text), 1000
        )
        speeds = [
            distance / (int(minutes) * 60 + int(seconds))
            for minutes, seconds in parts
            if int(minutes) * 60 + int(seconds) > 0
        ]
        if not speeds:
            return None
        sensor, values, unit = "velocity_smooth", speeds, "m/s"
    else:
        values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
        if not values:
            return None
        if step.get("kind") == "power":
            sensor, unit = "watts", "W"
            if "%" in text:
                ftp = _number(basis.get("icu_ftp"))
                if ftp is None or ftp <= 0:
                    return None
                values = [value * ftp / 100 for value in values]
        elif step.get("kind") == "hr" and "BPM" in text:
            sensor, unit = "heartrate", "bpm"
        else:
            return None
    low, high = min(values), max(values)
    if len(values) == 1:
        low, high = low * 0.95, high * 1.05
    return sensor, low, high, unit


def interval_quality(
    activity: dict[str, Any], targets: dict[str, Any] | None
) -> dict[str, Any]:
    base = {
        "method": METHOD,
        "source": "derived from Intervals.icu original streams and frozen local targets",
        "tolerance": "Authored ranges; single point targets use an explicit +/-5% measurement band. Missing samples, stopped timer and gaps over 5 seconds are excluded.",
    }
    if not targets or not targets.get("steps"):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Kein eindeutig gepaartes, gespeichertes Trainingsziel vorhanden.",
        }
    steps = targets["steps"]
    laps = activity.get("laps") or []
    if (
        not laps
        or len(laps) > len(steps)
        or any("duration" not in step for step in steps)
    ):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Runden fehlen oder die zeitbasierte Zuordnung ist mehrdeutig. Distanzschritte werden noch nicht bewertet.",
        }
    results = []
    previous_end = -1.0
    for index, lap in enumerate(laps):
        start, end = _number(lap.get("start_time")), _number(lap.get("end_time"))
        duration = steps[index]["duration"]
        if (
            start is None
            or end is None
            or end <= start
            or start < previous_end
            or abs((end - start) - duration) > max(5, duration * 0.1)
        ):
            return {
                **base,
                "status": "insufficient_data",
                "reason": "Die Runden lassen sich nicht eindeutig den geplanten Schritten zuordnen.",
            }
        previous_end = end
        target = _target(steps[index], targets.get("basis") or {})
        if target is None:
            results.append(
                {
                    "step": index + 1,
                    "target": steps[index]["target"],
                    "status": "insufficient_data",
                    "reason": "Historische Zielbasis fehlt oder Zieltyp wird noch nicht unterstützt.",
                }
            )
            continue
        sensor, low, high, unit = target
        samples = _samples(activity, sensor, start, end)
        measured = sum(weight for _, weight, _ in samples)
        mean = (
            sum(weight * value for _, weight, value in samples) / measured
            if measured
            else None
        )
        in_range = sum(weight for _, weight, value in samples if low <= value <= high)
        adequate = measured / (end - start) >= 0.8
        midpoint = (low + high) / 2
        results.append(
            {
                "step": index + 1,
                "target": steps[index]["target"],
                "unit": unit,
                "start": start,
                "end": end,
                "target_low": low,
                "target_high": high,
                "status": "ok" if adequate else "insufficient_data",
                "measured_seconds": round(measured, 1),
                "coverage": round(measured / (end - start), 3),
                "mean": round(mean, 2) if adequate and mean is not None else None,
                "seconds_in_target": round(in_range, 1) if adequate else None,
                "average_deviation_percent": round(
                    100 * (mean - midpoint) / midpoint, 2
                )
                if adequate and mean is not None and midpoint > 0
                else None,
            }
        )
    groups = []
    for target_text in dict.fromkeys(str(row["target"]) for row in results):
        repeats = [
            row
            for row in results
            if row["target"] == target_text
            and row.get("status") == "ok"
            and row.get("mean")
            and row["mean"] > 0
        ]
        if (
            len(repeats) >= 2
            and max(row["end"] - row["start"] for row in repeats)
            / min(row["end"] - row["start"] for row in repeats)
            <= 1.1
        ):
            groups.append(
                {
                    "target": target_text,
                    "repetitions": len(repeats),
                    "fade_percent": round(
                        100
                        * (repeats[0]["mean"] - repeats[-1]["mean"])
                        / repeats[0]["mean"],
                        2,
                    ),
                }
            )
    return {
        **base,
        "status": "ok"
        if len(laps) == len(steps) and all(row["status"] == "ok" for row in results)
        else "partial",
        "planned_steps": len(steps),
        "aligned_steps": len(laps),
        "missing_steps": len(steps) - len(laps),
        "steps": results,
        "repeat_groups": groups,
        "target_snapshot": {
            key: targets.get(key)
            for key in ("planned_unit_id", "observed_at", "basis", "matching")
        },
    }


def aerobic_analysis(activity: dict[str, Any]) -> dict[str, Any]:
    provider = _number(activity.get("decoupling"))
    base = {
        "method": METHOD,
        "provider_decoupling": {
            "value": provider,
            "unit": "%",
            "source": "Intervals.icu",
        },
        "source": "derived from Intervals.icu original streams",
        "warmup_excluded_seconds": 600,
        "eligibility": "At least 20 minutes after a 10-minute warm-up; >=85% paired data coverage; output variation <=15%; gaps >5 seconds, stops and non-positive output excluded. No universal fitness cutoff.",
    }
    kind = str(activity.get("type") or activity.get("sport") or "")
    sensor = (
        "watts"
        if kind in {"Ride", "VirtualRide"}
        else "velocity_smooth"
        if kind in {"Run", "VirtualRun"}
        else None
    )
    times = (activity.get("streams") or {}).get("time") or []
    if sensor is None or len(times) < 2 or times[-1] - times[0] < 1800:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Geeignete Sportart oder ausreichend lange Messreihe fehlt.",
        }
    start, end = float(times[0]) + 600, float(times[-1])
    output = _samples(activity, sensor, start, end)
    hr = {
        timestamp: (weight, value)
        for timestamp, weight, value in _samples(activity, "heartrate", start, end)
    }
    paired = [
        (timestamp, min(weight, hr[timestamp][0]), value, hr[timestamp][1])
        for timestamp, weight, value in output
        if value > 0 and timestamp in hr and 30 <= hr[timestamp][1] <= 240
    ]
    midpoint = (start + end) / 2
    halves = []
    for left, right in ((start, midpoint), (midpoint, end)):
        samples = [
            (
                max(0, min(timestamp + weight, right) - max(timestamp, left)),
                value,
                pulse,
            )
            for timestamp, weight, value, pulse in paired
        ]
        duration = sum(weight for weight, _, _ in samples)
        if duration < (right - left) * 0.85:
            return {
                **base,
                "status": "insufficient_data",
                "reason": "Zu wenig lückenfreie, bewegte Messzeit mit Leistung/Geschwindigkeit und Puls.",
            }
        mean = sum(weight * value for weight, value, _ in samples) / duration
        pulse = sum(weight * pulse for weight, _, pulse in samples) / duration
        variance = (
            sum(weight * (value - mean) ** 2 for weight, value, _ in samples) / duration
        )
        cv = math.sqrt(variance) / mean
        if cv > 0.15:
            return {
                **base,
                "status": "insufficient_data",
                "reason": "Die Belastung ist für einen gleichmäßigen Ausdauervergleich zu variabel.",
            }
        halves.append(
            {
                "start": left,
                "end": right,
                "measured_seconds": duration,
                "mean_output": mean,
                "mean_hr": pulse,
                "efficiency": mean / pulse,
                "variation": cv,
            }
        )
    if abs(halves[1]["mean_output"] / halves[0]["mean_output"] - 1) > 0.1:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Die Belastung der frühen und späten Hälfte ist nicht ausreichend vergleichbar.",
        }
    drift = (
        100
        * (halves[0]["efficiency"] - halves[1]["efficiency"])
        / halves[0]["efficiency"]
    )
    return {
        **base,
        "status": "ok",
        "unit": "W/bpm" if sensor == "watts" else "(m/s)/bpm",
        "sensor": sensor,
        "efficiency": round(
            sum(half["mean_output"] for half in halves)
            / sum(half["mean_hr"] for half in halves),
            4,
        ),
        "drift_percent": round(drift, 2),
        "halves": [
            {key: round(value, 4) for key, value in half.items()} for half in halves
        ],
        "long_session": end - times[0] >= 5400,
        "interpretation": "A steady-output efficiency comparison, not a medical readiness score or measured running economy. Temperature, terrain and indoor/outdoor conditions can affect the result.",
    }
