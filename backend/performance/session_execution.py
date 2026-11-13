"""How one run or ride was executed, lap by lap, from its own streams.

The Coach judges a session against its plan; these values give it the
numbers it cannot reliably read from thousands of raw samples: the structure
(interval or continuous), each work lap with its first and second half and
its closing heart rate, each recovery with its heart-rate drop after 60 s,
the first and second half of a continuous session, and sensor-quality flags.
Everything is descriptive and comes from the session itself; nothing is
compared with other sessions or with norms. Pure: no I/O, inputs unchanged.
"""

from __future__ import annotations

import bisect
import itertools
import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any, Final

from backend.athlete.measurements import finite_float as _number

METHOD: Final = "session-execution-v1"
SCOPE: Final = (
    "Descriptive execution of this one session from its own streams and laps. "
    "Output is pace in s/km for runs and power in W for rides (speed in km/h "
    "for rides without power). Every change_pct is computed on speed or power, "
    "later minus earlier in percent: negative means slower or less power. "
    "Heart rate is not judged for work laps under 120 s (short). "
    "start_change_pct is the first 30 s against the rest of a rep (positive: "
    "started faster). variability_pct is the spread of the output after the "
    "first 10 s in percent of its mean. Stride length is speed over step rate. "
    "lap_pace comes from the lap distance and is steadier than GPS pace for "
    "short reps. erg_like marks an indoor ride whose power the trainer held. "
    "start_s is a lap's start on the clock of the session's streams. "
    "heart_rate_drop_60s is the drop from the highest heart rate in the first "
    "15 s of a recovery to the mean 55-65 s into it."
)
SHORT_REP_S: Final = 120.0
# The opening of a rep: its first 30 s against the rest shows a too-fast start.
START_S: Final = 30.0
START_REP_S: Final = 90.0
# Variability leaves out the first 10 s of acceleration.
SETTLE_S: Final = 10.0
ERG_VARIABILITY_PCT: Final = 3.0
# Shorter laps are lap-button slips; short work or rest laps of 15 s stay.
MIN_LAP_S: Final = 5.0
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
# Heart rate locked onto step cadence: close to it, following its changes.
CADENCE_LOCK_BPM: Final = 4.0
CADENCE_LOCK_SHARE: Final = 0.5
CADENCE_LOCK_MIN_SPM: Final = 140.0
CADENCE_LOCK_MIN_SPREAD_SPM: Final = 3.0
CADENCE_LOCK_MIN_CORRELATION: Final = 0.8

_WORK: Final = "work"
_RECOVERY: Final = "recovery"
_WARMUP: Final = "warmup"
_COOLDOWN: Final = "cooldown"
_LAP: Final = "lap"


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
    channel = _output_channel(sport, streams, len(times))
    reason = _missing_input(times, channel)
    if reason is not None or channel is None:
        return {**base, "status": "insufficient_data", "reason": reason}
    reader = _Reader(sport, streams, channel)
    laps, origin = _classified_laps(activity.get("laps") or [], reader)
    structure = "continuous" if origin == "no_work_laps" else "interval"
    result: dict[str, Any] = {
        **base,
        "status": "ok",
        "output": reader.output_name,
        "output_unit": reader.output_unit,
        "structure": structure,
        "structure_origin": origin,
        "data_quality": _data_quality(sport, streams),
        "duration_s": round(float(times[-1] - times[0])),
    }
    for kind, key in ((_WARMUP, "warmup"), (_COOLDOWN, "cooldown")):
        part = [lap for lap in laps if lap["kind"] == kind]
        if part:
            result[key] = reader.part(part[0]["start"], part[-1]["end"])
    if activity.get("lap_source"):
        result["lap_source"] = activity["lap_source"]
    if structure == "interval":
        result.update(_intervals(laps, reader))
        if _erg_like(activity, reader, result["reps"]):
            # Power held by the trainer says little; heart rate and cadence do.
            result["erg_like"] = True
    else:
        result["halves"] = _halves(laps, reader, float(times[0]), float(times[-1]))
    return result


def _missing_input(times: Sequence[Any], channel: str | None) -> str | None:
    """Why the streams cannot describe the session, or None when they can."""
    if (
        len(times) < 2
        or _number(times[0]) is None
        or _number(times[-1]) is None
        or times[-1] - times[0] < MIN_SESSION_S
    ):
        return "Zu kurze oder fehlende Messreihe."
    if channel is None:
        return "Tempo oder Leistung fehlt."
    return None


def _erg_like(
    activity: Mapping[str, Any], reader: _Reader, reps: Sequence[Mapping[str, Any]]
) -> bool:
    """An indoor ride whose work laps all held power within a few percent."""
    variabilities = [rep.get("variability_pct") for rep in reps]
    return (
        reader.output_name == "power"
        and activity.get("environment") in {"indoor", "virtual"}
        and bool(variabilities)
        and all(v is not None and v < ERG_VARIABILITY_PCT for v in variabilities)
    )


class _Window:
    """Prefix sums of one channel's valid sample intervals for fast window means."""

    def __init__(self, lefts: list[float], rights: list[float], values: list[float]):
        self.lefts = lefts
        self.rights = rights
        self.values = values
        self.weights = [
            0.0,
            *itertools.accumulate(r - l for l, r in zip(lefts, rights, strict=True)),
        ]
        self.sums = [
            0.0,
            *itertools.accumulate(
                (r - l) * v for l, r, v in zip(lefts, rights, values, strict=True)
            ),
        ]
        self.squares = [
            0.0,
            *itertools.accumulate(
                (r - l) * v * v for l, r, v in zip(lefts, rights, values, strict=True)
            ),
        ]

    def mean(self, start: float, end: float) -> float | None:
        stats = self.stats(start, end)
        return None if stats is None else stats[0]

    def stats(self, start: float, end: float) -> tuple[float, float] | None:
        """Time-weighted mean and standard deviation over the window."""
        first = bisect.bisect_right(self.rights, start)
        last = bisect.bisect_left(self.lefts, end)
        if first >= last:
            return None
        weight = self.weights[last] - self.weights[first]
        total = self.sums[last] - self.sums[first]
        squares = self.squares[last] - self.squares[first]
        # Trim the parts of the edge intervals outside the window.
        head = max(0.0, start - self.lefts[first])
        tail = max(0.0, self.rights[last - 1] - end)
        first_value, last_value = self.values[first], self.values[last - 1]
        weight -= head + tail
        total -= head * first_value + tail * last_value
        squares -= head * first_value**2 + tail * last_value**2
        if weight <= 0:
            return None
        mean = total / weight
        return mean, math.sqrt(max(0.0, squares / weight - mean * mean))


class _Reader:
    """Time-weighted means of the session's channels over a time window."""

    def __init__(self, sport: str, streams: Mapping[str, Any], channel: str) -> None:
        self._times = [_number(value) for value in streams["time"]]
        self._sorted_times = [
            time if time is not None else -math.inf for time in self._times
        ]
        self._streams = streams
        self._channel = channel
        self._run = sport == "run"
        self._windows: dict[tuple[str, bool], _Window | None] = {}
        if channel == "watts":
            self.output_name, self.output_unit = "power", "W"
        elif self._run:
            self.output_name, self.output_unit = "pace", "s/km"
        else:
            self.output_name, self.output_unit = "speed", "km/h"

    def _window(self, key: str, moving_only: bool) -> _Window | None:
        cached = (key, moving_only)
        if cached not in self._windows:
            self._windows[cached] = self._build(key, moving_only)
        return self._windows[cached]

    def _build(self, key: str, moving_only: bool) -> _Window | None:
        values = self._streams.get(key)
        if not isinstance(values, list) or len(values) != len(self._times):
            return None
        moving = self._streams.get("moving")
        if not (isinstance(moving, list) and len(moving) == len(values)):
            moving = None
        lefts: list[float] = []
        rights: list[float] = []
        kept: list[float] = []
        for index in range(len(self._times) - 1):
            left, right = self._times[index], self._times[index + 1]
            value = _number(values[index])
            if left is None or right is None or value is None:
                continue
            if not 0 < right - left <= MAX_GAP_S:
                continue
            if moving_only and moving is not None and moving[index] is not True:
                continue
            lefts.append(left)
            rights.append(right)
            kept.append(value)
        return _Window(lefts, rights, kept) if kept else None

    def mean(
        self, key: str, start: float, end: float, *, moving_only: bool = True
    ) -> float | None:
        window = self._window(key, moving_only)
        return None if window is None else window.mean(start, end)

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
        return round(max(found)) if found else None

    def variability_pct(self, start: float, end: float) -> float | None:
        """Spread of the output within the window, in percent of its mean."""
        window = self._window(self._channel, True)
        stats = None if window is None else window.stats(start, end)
        if stats is None or stats[0] <= 0:
            return None
        return round(stats[1] / stats[0] * 100, 1)

    def stride_length(self, start: float, end: float) -> float | None:
        """Mean metres per step of a run: speed over step rate."""
        if not self._run:
            return None
        speed = self.mean("velocity_smooth", start, end)
        cadence = self.mean("cadence", start, end)
        if speed is None or cadence is None or speed <= 0 or cadence <= 0:
            return None
        return round(speed / (cadence * RUN_CADENCE_FACTOR / 60.0), 2)

    def elevation_change(self, start: float, end: float) -> float | None:
        """Altitude at the window end minus at its start, in metres."""
        values = self._streams.get("altitude")
        if not isinstance(values, list) or len(values) != len(self._times):
            return None
        first, last = self._value_at(values, start), self._value_at(values, end)
        if first is None or last is None:
            return None
        return round(last - first, 1)

    def _value_at(self, values: Sequence[Any], moment: float) -> float | None:
        times = self._sorted_times
        index = min(bisect.bisect_left(times, moment), len(times) - 1)
        for candidate in (index, index - 1):
            if 0 <= candidate < len(values):
                number = _number(values[candidate])
                if number is not None:
                    return number
        return None

    def raw_output(self, start: float, end: float) -> float | None:
        """Mean moving speed (m/s) or power (W) over the window."""
        value = self.mean(self._channel, start, end)
        return value if value is not None and value > 0 else None

    def shown(self, raw: float | None) -> float | None:
        """Speed shown as pace (runs) or km/h; power as watts."""
        if raw is None:
            return None
        if self._channel == "watts":
            return round(raw)
        if self._run:
            return round(1000.0 / raw)
        return round(raw * 3.6, 1)

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
                "output": self.shown(self.raw_output(start, end)),
                "heart_rate_avg": self.heart_rate(start, end),
                "cadence": self.cadence(start, end),
            }
        )


def _intervals(laps: Sequence[Mapping[str, Any]], reader: _Reader) -> dict[str, Any]:
    works = [index for index, lap in enumerate(laps) if lap["kind"] == _WORK]
    raw = [reader.raw_output(laps[i]["start"], laps[i]["end"]) for i in works]
    reps: list[dict[str, Any]] = []
    recoveries: list[dict[str, Any]] = []
    for number, index in enumerate(works[:MAX_REPS], start=1):
        reps.append(_rep(number, laps[index], raw[number - 1], reader))
        rest = _rest_after(laps, index)
        if rest is not None:
            recoveries.append({"after_rep": number, **_recovery(rest, reader)})
    return {
        "reps": reps,
        "recoveries": recoveries,
        "rep_summary": _rep_summary(len(works), raw, reps, recoveries),
    }


def _rep(
    number: int, lap: Mapping[str, Any], raw: float | None, reader: _Reader
) -> dict[str, Any]:
    """One work lap: output, its halves and opening, heart rate, cadence, terrain."""
    start, end = lap["start"], lap["end"]
    middle = (start + end) / 2
    duration = end - start
    first, second = reader.raw_output(start, middle), reader.raw_output(middle, end)
    distance = _number(lap.get("distance_m"))
    opening = (
        _change_pct(
            reader.raw_output(start + START_S, end),
            reader.raw_output(start, start + START_S),
        )
        if duration >= START_REP_S
        else None
    )
    lap_pace = (
        round(duration / distance * 1000)
        if reader.output_name == "pace" and distance
        else None
    )
    return _drop_none(
        {
            "rep": number,
            "start_s": round(start),
            "duration_s": round(duration),
            "distance_m": lap.get("distance_m"),
            "output": reader.shown(raw),
            "lap_pace": lap_pace,
            "output_first_half": reader.shown(first),
            "output_second_half": reader.shown(second),
            "within_rep_change_pct": _change_pct(first, second),
            "start_change_pct": opening,
            "variability_pct": reader.variability_pct(
                min(start + SETTLE_S, middle), end
            ),
            "heart_rate_avg": reader.heart_rate(start, end),
            "heart_rate_first_half": reader.heart_rate(start, middle),
            "heart_rate_second_half": reader.heart_rate(middle, end),
            "heart_rate_peak": reader.peak("heartrate", start, end),
            "heart_rate_end": reader.heart_rate(max(start, end - 10.0), end),
            "cadence": reader.cadence(start, end),
            "cadence_first_half": reader.cadence(start, middle),
            "cadence_second_half": reader.cadence(middle, end),
            "stride_length_m": reader.stride_length(start, end),
            "stride_length_first_half_m": reader.stride_length(start, middle),
            "stride_length_second_half_m": reader.stride_length(middle, end),
            "elevation_change_m": reader.elevation_change(start, end),
            "short": duration < SHORT_REP_S,
        }
    )


def _rep_summary(
    count: int,
    raw: Sequence[float | None],
    reps: Sequence[Mapping[str, Any]],
    recoveries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Counts and first-against-last values over all work laps."""
    known = [value for value in raw if value is not None]
    summary: dict[str, Any] = {"rep_count": count}
    if count > MAX_REPS:
        summary["reps_listed"] = MAX_REPS
    if len(known) >= 2:
        summary["first_to_last_change_pct"] = _change_pct(known[0], known[-1])
        summary["output_spread_pct"] = round(
            (max(known) - min(known)) / statistics.fmean(known) * 100, 1
        )
    long_reps = [rep for rep in reps if not rep["short"] and "heart_rate_end" in rep]
    if len(long_reps) >= 2:
        summary["heart_rate_end_first"] = long_reps[0]["heart_rate_end"]
        summary["heart_rate_end_last"] = long_reps[-1]["heart_rate_end"]
    for key in ("cadence", "stride_length_m"):
        measured = [rep[key] for rep in reps if key in rep]
        if len(measured) >= 2:
            summary[f"{key}_first"] = measured[0]
            summary[f"{key}_last"] = measured[-1]
    variability = [rep["variability_pct"] for rep in reps if "variability_pct" in rep]
    if variability:
        summary["variability_pct_max"] = max(variability)
    drops = [
        item["heart_rate_drop_60s"]
        for item in recoveries
        if "heart_rate_drop_60s" in item
    ]
    if len(drops) >= 2:
        summary["recovery_drop_first"] = drops[0]
        summary["recovery_drop_last"] = drops[-1]
    return summary


def _rest_after(laps: Sequence[Mapping[str, Any]], index: int) -> dict[str, Any] | None:
    """The recovery after a work lap, joined over consecutive recovery laps."""
    following = []
    for lap in laps[index + 1 :]:
        if lap["kind"] != _RECOVERY:
            break
        following.append(lap)
    if not following:
        return None
    return {"start": following[0]["start"], "end": following[-1]["end"]}


def _recovery(lap: Mapping[str, Any], reader: _Reader) -> dict[str, Any]:
    start, end = lap["start"], lap["end"]
    item: dict[str, Any] = {
        "start_s": round(start),
        "duration_s": round(end - start),
        "output": reader.shown(reader.raw_output(start, end)),
        "heart_rate_avg": reader.heart_rate(start, end),
        "heart_rate_end": reader.heart_rate(max(start, end - 10.0), end),
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
    result: dict[str, Any] = {
        "status": "ok",
        "main_part_s": round(end - start),
        "main": reader.part(start, end),
        **halves,
        "change_pct": _change_pct(
            reader.raw_output(start, middle), reader.raw_output(middle, end)
        ),
    }
    for key, name in (
        ("heart_rate_avg", "heart_rate_change_bpm"),
        ("cadence", "cadence_change"),
    ):
        earlier, later = halves["first"].get(key), halves["second"].get(key)
        if earlier is not None and later is not None:
            result[name] = later - earlier
    return _drop_none(result)


def _classified_laps(
    raw: Sequence[Mapping[str, Any]], reader: _Reader
) -> tuple[list[dict[str, Any]], str]:
    """Laps with a work, recovery, warm-up or cool-down role, and their origin.

    Intervals need at least two work laps with a non-work lap between each
    pair; otherwise the session is continuous and keeps only the provider's
    own warm-up and cool-down labels.
    """
    laps: list[dict[str, Any]] = [
        {
            "start": float(lap["start_time"]),
            "end": float(lap["end_time"]),
            "kind": lap.get("kind") or _LAP,
            "distance_m": lap.get("distance_m"),
        }
        for lap in raw
        if _number(lap.get("start_time")) is not None
        and _number(lap.get("end_time")) is not None
        and float(lap["end_time"]) - float(lap["start_time"]) >= MIN_LAP_S
    ]
    laps.sort(key=lambda lap: float(lap["start"]))
    labelled = [lap["kind"] == _WORK for lap in laps]
    if _alternates(labelled):
        return _with_roles(laps, labelled), "lap_kinds"
    if not any(labelled):
        inferred = _faster_laps(laps, reader)
        if inferred is not None and _alternates(inferred):
            return _with_roles(laps, inferred), "lap_output"
    # Continuous: only the provider's own warm-up and cool-down labels stay.
    for lap in laps:
        if lap["kind"] not in {_WARMUP, _COOLDOWN}:
            lap["kind"] = _LAP
    return laps, "no_work_laps"


def _alternates(work: Sequence[bool]) -> bool:
    """At least two work laps, each pair separated by a non-work lap."""
    indexes = [index for index, flag in enumerate(work) if flag]
    return len(indexes) >= 2 and all(
        later - earlier > 1 for earlier, later in itertools.pairwise(indexes)
    )


def _with_roles(
    laps: list[dict[str, Any]], work: Sequence[bool]
) -> list[dict[str, Any]]:
    """Work laps; others before the first warm up, after the last cool down."""
    first = work.index(True)
    last = len(work) - 1 - list(reversed(work)).index(True)
    for index, lap in enumerate(laps):
        if work[index]:
            lap["kind"] = _WORK
        elif index < first:
            lap["kind"] = _WARMUP
        elif index > last:
            lap["kind"] = _COOLDOWN
        else:
            lap["kind"] = _RECOVERY
    return laps


def _faster_laps(
    laps: Sequence[Mapping[str, Any]], reader: _Reader
) -> list[bool] | None:
    """Faster laps when lap outputs split into two clear groups, else None.

    A lap without moving output (a standing rest) counts as the slowest.
    """
    if len(laps) < 3:
        return None
    outputs = [reader.raw_output(lap["start"], lap["end"]) or 0.0 for lap in laps]
    ordered = sorted(outputs)
    gap, position = max(
        (ordered[i + 1] - ordered[i], i) for i in range(len(ordered) - 1)
    )
    threshold = ordered[position + 1]
    if threshold <= 0 or gap < WORK_GAP_SHARE * threshold:
        return None
    return [value >= threshold for value in outputs]


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
    """Heart rate close to step cadence and following its changes."""
    steps = {time: value * RUN_CADENCE_FACTOR for time, value in cadence}
    pairs = [
        (rate, steps[time])
        for time, rate in heart
        if time in steps and steps[time] >= CADENCE_LOCK_MIN_SPM
    ]
    if len(pairs) < 60:
        return False
    rates = [rate for rate, _ in pairs]
    cadences = [step for _, step in pairs]
    close = sum(abs(rate - step) <= CADENCE_LOCK_BPM for rate, step in pairs)
    if close / len(pairs) < CADENCE_LOCK_SHARE:
        return False
    # Without cadence changes a close value is a coincidence, not a lock.
    if statistics.pstdev(cadences) < CADENCE_LOCK_MIN_SPREAD_SPM:
        return False
    if statistics.pstdev(rates) == 0:
        return False
    return statistics.correlation(rates, cadences) >= CADENCE_LOCK_MIN_CORRELATION


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


def _drop_none(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}


def comparison_metrics(execution: Mapping[str, Any]) -> dict[str, Any] | None:
    """The few numbers of one execution that comparable sessions are set against."""
    if execution.get("status") != "ok":
        return None
    quality = execution.get("data_quality") or {}
    base = {
        "structure": execution.get("structure"),
        "output_unit": execution.get("output_unit"),
        # The stream providers, so a sensor or provider change shows beside the values.
        "source": execution.get("source") or None,
        # Peers with doubtful heart rate or speed stay out of the medians.
        "data_quality_ok": all(
            value in {"ok", "missing"} for value in quality.values()
        ),
    }
    if execution.get("structure") == "continuous":
        halves = execution.get("halves") or {}
        main = halves.get("main") or {}
        if halves.get("status") != "ok" or main.get("output") is None:
            return None
        return _drop_none(
            {
                **base,
                "main_part_s": halves.get("main_part_s"),
                "output": main.get("output"),
                "heart_rate_avg": main.get("heart_rate_avg"),
                "heart_rate_change_bpm": halves.get("heart_rate_change_bpm"),
                "cadence": main.get("cadence"),
            }
        )
    reps = [rep for rep in execution.get("reps") or [] if rep.get("output") is not None]
    if len(reps) < 2:
        return None
    long_reps = [rep for rep in reps if not rep.get("short")]
    drops = [
        item["heart_rate_drop_60s"]
        for item in execution.get("recoveries") or []
        if "heart_rate_drop_60s" in item
    ]
    summary = execution.get("rep_summary") or {}
    return _drop_none(
        {
            **base,
            "rep_count": summary.get("rep_count", len(reps)),
            "median_rep_s": round(statistics.median(rep["duration_s"] for rep in reps)),
            "rep_output_mean": rounded_mean(rep["output"] for rep in reps),
            "heart_rate_end_mean": rounded_mean(
                rep["heart_rate_end"] for rep in long_reps if "heart_rate_end" in rep
            ),
            "recovery_drop_mean": rounded_mean(drops),
            "first_to_last_change_pct": summary.get("first_to_last_change_pct"),
            "cadence_mean": rounded_mean(
                rep["cadence"] for rep in reps if "cadence" in rep
            ),
        }
    )


def rounded_mean(values: Any) -> float | None:
    """Mean rounded like every comparison value (see ``rounded_metric``)."""
    numbers = [float(value) for value in values]
    return rounded_metric(statistics.fmean(numbers)) if numbers else None


def rounded_metric(value: float) -> float:
    """Whole numbers from 50 on (pace, watts, bpm), else one decimal."""
    return round(value) if abs(value) >= 50 else round(value, 1)
