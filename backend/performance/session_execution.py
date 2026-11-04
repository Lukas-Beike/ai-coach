"""How one run or ride was executed, lap by lap, from its own streams.

The Coach judges a session against its plan; these values give it the
numbers it cannot reliably read from thousands of raw samples: the structure
(intervals or continuous), each work lap with its first and second half and
its closing heart rate, each recovery with its heart-rate drop after 60 s,
the first and second half of a continuous session, and sensor-quality flags.
Everything is descriptive and comes from the session itself; nothing is
compared with other sessions or with norms. Pure: no I/O, inputs unchanged.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any, Final

METHOD: Final = "session-execution-v1"
SCOPE: Final = (
    "Descriptive execution of this one session from its own streams and laps. "
    "Output is pace in s/km for runs and power in W for rides (speed in km/h "
    "for rides without power). change_pct is later minus earlier output in "
    "percent: negative means slower or less power. Heart rate is not judged "
    "for work laps under 120 s (short). heart_rate_drop_60s is the drop from "
    "the highest heart rate in the first 15 s of a recovery to the mean "
    "55-65 s into it."
)
SHORT_REP_S: Final = 120.0
MIN_LAP_S: Final = 20.0
MIN_SESSION_S: Final = 600.0
WARMUP_EXCLUDED_S: Final = 600.0
MAX_GAP_S: Final = 5.0
MAX_REPS: Final = 40
# Lap outputs split into work and recovery when the largest gap between sorted
# lap outputs is at least this share of the faster side.
WORK_GAP_SHARE: Final = 0.15
RUN_CADENCE_FACTOR: Final = 2.0
HR_SPIKE_BPM: Final = 20.0
HR_SPIKE_SHARE: Final = 0.02
SPEED_JUMP_MPS: Final = 2.5
SPEED_JUMP_SHARE: Final = 0.01
CADENCE_LOCK_BPM: Final = 4.0
CADENCE_LOCK_SHARE: Final = 0.5
CADENCE_LOCK_MIN_SPM: Final = 140.0

_WORK: Final = "work"
_RECOVERY: Final = "recovery"
_WARMUP: Final = "warmup"
_COOLDOWN: Final = "cooldown"


def session_execution(
    activity: Mapping[str, Any], *, source_label: str = ""
) -> dict[str, Any]:
    """Return the lap-by-lap execution of one run or ride, or why it has none."""
    base = {"method": METHOD, "scope": SCOPE, "source": source_label}
    sport = activity.get("sport")
    if sport not in {"run", "ride"}:
        return {**base, "status": "not_applicable", "reason": "Nur Lauf und Rad."}
    streams = activity.get("streams") or {}
    times = streams.get("time") or []
    if (
        len(times) < 2
        or _number(times[-1]) is None
        or times[-1] - times[0] < MIN_SESSION_S
    ):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Zu kurze oder fehlende Messreihe.",
        }
    channel = _output_channel(sport, streams, len(times))
    if channel is None:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Tempo oder Leistung fehlt.",
        }
    reader = _Reader(sport, streams, channel)
    laps = _classified_laps(activity.get("laps") or [], reader)
    structure = (
        "intervals" if sum(lap["kind"] == _WORK for lap in laps) >= 2 else "continuous"
    )
    result: dict[str, Any] = {
        **base,
        "status": "ok",
        "output": reader.output_name,
        "output_unit": reader.output_unit,
        "structure": structure,
        "structure_origin": _structure_origin(laps, structure),
        "data_quality": _data_quality(sport, streams),
        "duration_s": round(float(times[-1] - times[0])),
    }
    for kind, key in ((_WARMUP, "warmup"), (_COOLDOWN, "cooldown")):
        part = [lap for lap in laps if lap["kind"] == kind]
        if part:
            result[key] = reader.part(part[0]["start"], part[-1]["end"])
    if structure == "intervals":
        result.update(_intervals(laps, reader))
    else:
        result["halves"] = _halves(laps, reader, float(times[0]), float(times[-1]))
    return result


class _Reader:
    """Time-weighted means of the session's channels over a time window."""

    def __init__(self, sport: str, streams: Mapping[str, Any], channel: str) -> None:
        self._times = [_number(value) for value in streams["time"]]
        self._streams = streams
        self._channel = channel
        self._run = sport == "run"
        if channel == "watts":
            self.output_name, self.output_unit = "power", "W"
        elif self._run:
            self.output_name, self.output_unit = "pace", "s/km"
        else:
            self.output_name, self.output_unit = "speed", "km/h"

    def mean(
        self, key: str, start: float, end: float, *, moving_only: bool = True
    ) -> float | None:
        values = self._streams.get(key)
        if not isinstance(values, list) or len(values) != len(self._times):
            return None
        moving = self._streams.get("moving")
        moving = (
            moving if isinstance(moving, list) and len(moving) == len(values) else None
        )
        total = weight = 0.0
        for index in range(len(self._times) - 1):
            left, right = self._times[index], self._times[index + 1]
            value = _number(values[index])
            if left is None or right is None or value is None:
                continue
            if right - left > MAX_GAP_S:
                continue
            if moving_only and moving is not None and moving[index] is not True:
                continue
            span = min(right, end) - max(left, start)
            if span <= 0:
                continue
            total += value * span
            weight += span
        return total / weight if weight > 0 else None

    def peak(self, key: str, start: float, end: float) -> float | None:
        values = self._streams.get(key)
        if not isinstance(values, list) or len(values) != len(self._times):
            return None
        found = [
            number
            for time, value in zip(self._times, values, strict=True)
            if time is not None and start <= time <= end
            if (number := _number(value)) is not None
        ]
        return max(found) if found else None

    def output(self, start: float, end: float) -> float | None:
        """Mean output; speed is averaged first, then shown as pace or km/h."""
        value = self.mean(self._channel, start, end)
        if value is None or value <= 0:
            return None
        if self._channel == "watts":
            return round(value)
        if self._run:
            return round(1000.0 / value)
        return round(value * 3.6, 1)

    def raw_output(self, start: float, end: float) -> float | None:
        value = self.mean(self._channel, start, end)
        return value if value is not None and value > 0 else None

    def cadence(self, start: float, end: float) -> float | None:
        value = self.mean("cadence", start, end)
        if value is None or value <= 0:
            return None
        return round(value * (RUN_CADENCE_FACTOR if self._run else 1.0))

    def heart_rate(self, start: float, end: float) -> float | None:
        value = self.mean("heartrate", start, end, moving_only=False)
        return None if value is None else round(value)

    def part(self, start: float, end: float) -> dict[str, Any]:
        return _drop_none(
            {
                "duration_s": round(end - start),
                "output": self.output(start, end),
                "heart_rate_avg": self.heart_rate(start, end),
                "cadence": self.cadence(start, end),
            }
        )


def _intervals(laps: Sequence[Mapping[str, Any]], reader: _Reader) -> dict[str, Any]:
    reps: list[dict[str, Any]] = []
    recoveries: list[dict[str, Any]] = []
    works = [lap for lap in laps if lap["kind"] == _WORK][:MAX_REPS]
    following = {
        id(lap): laps[index + 1] if index + 1 < len(laps) else None
        for index, lap in enumerate(laps)
    }
    for number, lap in enumerate(works, start=1):
        start, end = lap["start"], lap["end"]
        middle = (start + end) / 2
        duration = end - start
        first, second = reader.raw_output(start, middle), reader.raw_output(middle, end)
        rep = {
            "rep": number,
            "duration_s": round(duration),
            "distance_m": lap.get("distance_m"),
            "output": reader.output(start, end),
            "output_first_half": reader.output(start, middle),
            "output_second_half": reader.output(middle, end),
            "within_rep_change_pct": _change_pct(first, second),
            "heart_rate_avg": reader.heart_rate(start, end),
            "heart_rate_end": reader.heart_rate(max(start, end - 10.0), end),
            "cadence": reader.cadence(start, end),
            "short": duration < SHORT_REP_S,
        }
        reps.append(_drop_none(rep))
        recovery = following[id(lap)]
        if recovery is not None and recovery["kind"] == _RECOVERY:
            recoveries.append({"after_rep": number, **_recovery(recovery, reader)})
    raw = [reader.raw_output(lap["start"], lap["end"]) for lap in works]
    known = [value for value in raw if value is not None]
    summary: dict[str, Any] = {"rep_count": len(works)}
    if len(known) >= 2:
        summary["first_to_last_change_pct"] = _change_pct(known[0], known[-1])
        summary["output_spread_pct"] = round(
            (max(known) - min(known)) / statistics.fmean(known) * 100, 1
        )
    long_reps = [rep for rep in reps if not rep["short"] and "heart_rate_end" in rep]
    if len(long_reps) >= 2:
        summary["heart_rate_end_first"] = long_reps[0]["heart_rate_end"]
        summary["heart_rate_end_last"] = long_reps[-1]["heart_rate_end"]
    drops = [
        item["heart_rate_drop_60s"]
        for item in recoveries
        if "heart_rate_drop_60s" in item
    ]
    if len(drops) >= 2:
        summary["recovery_drop_first"] = drops[0]
        summary["recovery_drop_last"] = drops[-1]
    return {"reps": reps, "recoveries": recoveries, "rep_summary": summary}


def _recovery(lap: Mapping[str, Any], reader: _Reader) -> dict[str, Any]:
    start, end = lap["start"], lap["end"]
    item: dict[str, Any] = {
        "duration_s": round(end - start),
        "output": reader.output(start, end),
        "heart_rate_avg": reader.heart_rate(start, end),
    }
    if end - start >= 65.0:
        peak = reader.peak("heartrate", start, start + 15.0)
        later = reader.mean("heartrate", start + 55.0, start + 65.0, moving_only=False)
        if peak is not None and later is not None:
            item["heart_rate_start"] = round(peak)
            item["heart_rate_after_60s"] = round(later)
            item["heart_rate_drop_60s"] = round(peak - later)
    return _drop_none(item)


def _halves(
    laps: Sequence[Mapping[str, Any]], reader: _Reader, first: float, last: float
) -> dict[str, Any]:
    """First and second half of the main part, without warm-up and cool-down."""
    start, end = first, last
    warmups = [lap for lap in laps if lap["kind"] == _WARMUP]
    cooldowns = [lap for lap in laps if lap["kind"] == _COOLDOWN]
    if warmups:
        start = warmups[-1]["end"]
    elif last - first >= WARMUP_EXCLUDED_S * 3:
        start = first + WARMUP_EXCLUDED_S
    if cooldowns:
        end = cooldowns[0]["start"]
    if end - start < MIN_SESSION_S:
        return {"status": "insufficient_data", "reason": "Hauptteil zu kurz."}
    middle = (start + end) / 2
    halves = {"first": reader.part(start, middle), "second": reader.part(middle, end)}
    first_hr = halves["first"].get("heart_rate_avg")
    second_hr = halves["second"].get("heart_rate_avg")
    result: dict[str, Any] = {
        "status": "ok",
        "main_part_s": round(end - start),
        **halves,
        "change_pct": _change_pct(
            reader.raw_output(start, middle), reader.raw_output(middle, end)
        ),
    }
    if first_hr is not None and second_hr is not None:
        result["heart_rate_change_bpm"] = second_hr - first_hr
    first_cadence = halves["first"].get("cadence")
    second_cadence = halves["second"].get("cadence")
    if first_cadence is not None and second_cadence is not None:
        result["cadence_change"] = second_cadence - first_cadence
    return _drop_none(result)


def _classified_laps(
    raw: Sequence[Mapping[str, Any]], reader: _Reader
) -> list[dict[str, Any]]:
    """Laps with a work, recovery, warm-up or cool-down role, in time order."""
    laps: list[dict[str, Any]] = [
        {
            "start": float(lap["start_time"]),
            "end": float(lap["end_time"]),
            "kind": lap.get("kind") or "lap",
            "distance_m": lap.get("distance_m"),
        }
        for lap in raw
        if _number(lap.get("start_time")) is not None
        and _number(lap.get("end_time")) is not None
        and float(lap["end_time"]) - float(lap["start_time"]) >= MIN_LAP_S
    ]
    laps.sort(key=lambda lap: lap["start"])
    works = [index for index, lap in enumerate(laps) if lap["kind"] == _WORK]
    if works:
        # Provider-labelled intervals: unlabelled laps before the first work lap
        # warm up, after the last cool down, and between them recover.
        for index, lap in enumerate(laps):
            if lap["kind"] != "lap":
                continue
            if index < works[0]:
                lap["kind"] = _WARMUP
            elif index > works[-1]:
                lap["kind"] = _COOLDOWN
            else:
                lap["kind"] = _RECOVERY
        return laps
    return _inferred(laps, reader)


def _inferred(laps: list[dict[str, Any]], reader: _Reader) -> list[dict[str, Any]]:
    """Mark faster laps as work when lap outputs split into two clear groups."""
    if len(laps) < 3:
        return laps
    outputs = [reader.raw_output(lap["start"], lap["end"]) for lap in laps]
    if any(value is None for value in outputs):
        return laps
    known = [float(value) for value in outputs if value is not None]
    ordered = sorted(known)
    gaps = [(ordered[i + 1] - ordered[i], i) for i in range(len(ordered) - 1)]
    gap, position = max(gaps)
    threshold = ordered[position + 1]
    if gap < WORK_GAP_SHARE * threshold:
        return laps
    work = [value >= threshold for value in known]
    if sum(work) < 2:
        return laps
    first = work.index(True)
    last = len(work) - 1 - work[::-1].index(True)
    for index, lap in enumerate(laps):
        if work[index]:
            lap["kind"] = _WORK
        elif index < first:
            lap["kind"] = _WARMUP
        elif index > last:
            lap["kind"] = _COOLDOWN
        else:
            lap["kind"] = _RECOVERY
    for lap in laps:
        lap["inferred"] = True
    return laps


def _structure_origin(laps: Sequence[Mapping[str, Any]], structure: str) -> str:
    if structure == "continuous":
        return "no_work_laps"
    if any(lap.get("inferred") for lap in laps):
        return "lap_output"
    return "lap_kinds"


def _data_quality(sport: str, streams: Mapping[str, Any]) -> dict[str, str]:
    """Flags for heart-rate spikes, cadence lock and GPS speed jumps."""
    times = [_number(value) for value in streams.get("time") or []]
    heart = _paired(times, streams.get("heartrate"))
    quality = {"heart_rate": "missing" if not heart else "ok"}
    if heart and _jump_share(heart, HR_SPIKE_BPM) > HR_SPIKE_SHARE:
        quality["heart_rate"] = "spikes"
    cadence = _paired(times, streams.get("cadence"))
    if sport == "run" and heart and cadence and _cadence_locked(heart, cadence):
        quality["heart_rate"] = "possible_cadence_lock"
    speed = _paired(times, streams.get("velocity_smooth"))
    quality["speed"] = "missing" if not speed else "ok"
    if speed and _jump_share(speed, SPEED_JUMP_MPS) > SPEED_JUMP_SHARE:
        quality["speed"] = "jumps"
    return quality


def _paired(times: Sequence[float | None], values: object) -> list[tuple[float, float]]:
    if not isinstance(values, list) or len(values) != len(times):
        return []
    return [
        (time, number)
        for time, value in zip(times, values, strict=True)
        if time is not None and (number := _number(value)) is not None
    ]


def _jump_share(points: Sequence[tuple[float, float]], jump: float) -> float:
    pairs = [
        abs(right - left)
        for (t0, left), (t1, right) in itertools.pairwise(points)
        if 0 < t1 - t0 <= 2.0
    ]
    if not pairs:
        return 0.0
    return sum(change > jump for change in pairs) / len(pairs)


def _cadence_locked(
    heart: Sequence[tuple[float, float]], cadence: Sequence[tuple[float, float]]
) -> bool:
    steps = {time: value * RUN_CADENCE_FACTOR for time, value in cadence}
    running = [
        abs(rate - steps[time])
        for time, rate in heart
        if time in steps and steps[time] >= CADENCE_LOCK_MIN_SPM
    ]
    if len(running) < 60:
        return False
    return (
        sum(gap <= CADENCE_LOCK_BPM for gap in running) / len(running)
        >= CADENCE_LOCK_SHARE
    )


def _output_channel(sport: str, streams: Mapping[str, Any], length: int) -> str | None:
    keys = ("watts", "velocity_smooth") if sport == "ride" else ("velocity_smooth",)
    for key in keys:
        values = streams.get(key)
        if (
            isinstance(values, list)
            and len(values) == length
            and any(
                (number := _number(value)) is not None and number > 0
                for value in values
            )
        ):
            return key
    return None


def _change_pct(earlier: float | None, later: float | None) -> float | None:
    if earlier is None or later is None or earlier <= 0:
        return None
    return round((later - earlier) / earlier * 100, 1)


def _number(value: Any) -> float | None:
    if type(value) in {int, float} and math.isfinite(value):
        return float(value)
    return None


def _drop_none(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}
