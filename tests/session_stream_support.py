"""Synthetic 1 Hz run and ride streams with laps for execution tests."""

from __future__ import annotations

from typing import Any


def synthetic_session(
    segments: list[tuple[str, int, float, tuple[float, float]]],
    *,
    sport: str = "run",
    output: str = "velocity_smooth",
    cadence: float | None = 85.0,
    kinds: bool = True,
) -> dict[str, Any]:
    """1 Hz streams from (kind, seconds, output, (start hr, end hr)) segments."""
    times: list[int] = []
    values: list[float] = []
    heart: list[float] = []
    laps: list[dict[str, Any]] = []
    clock = 0
    for kind, seconds, value, (hr_start, hr_end) in segments:
        laps.append(
            {
                "start_time": float(clock),
                "end_time": float(clock + seconds),
                "kind": kind if kinds else "lap",
                "distance_m": None,
            }
        )
        for second in range(seconds):
            times.append(clock + second)
            values.append(value)
            heart.append(hr_start + (hr_end - hr_start) * second / max(1, seconds - 1))
        clock += seconds
    times.append(clock)
    values.append(values[-1])
    heart.append(heart[-1])
    streams: dict[str, Any] = {
        "time": times,
        output: values,
        "heartrate": heart,
        "moving": [True] * len(times),
    }
    if cadence is not None:
        streams["cadence"] = [cadence] * len(times)
    return {"sport": sport, "streams": streams, "laps": laps}
