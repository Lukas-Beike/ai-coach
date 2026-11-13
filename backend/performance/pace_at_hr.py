"""Pace at a fixed heart-rate band of steady, flat-ish runs (block trend).

A session contributes seconds and distance per 5 bpm heart-rate bin from its
full-resolution streams: after a 10-minute warm-up, moving, gap-free samples
whose slope is within ``FLAT_GRADE_PCT``. With a grade stream (or an altitude
and distance stream, slope over ``GRADE_SPAN_M``) the speed is grade-adjusted
(Minetti et al. 2002 cost of running); an outdoor run without either is
unknown terrain. Trail runs and sessions that are mostly hilly or without heart
rate, speed or enough duration give no value. The block trend picks one fixed
10 bpm band for all sessions of an environment and compares the earlier and
later half; a session without a value is unknown, never zero. No I/O.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from backend.canonical.activity_summary import summary_is_indoor
from backend.performance.grade_adjustment import grade_adjusted, grade_stream
from backend.performance.power_profile import METHOD_ID, METHOD_VERSION
from backend.performance.session_analysis import _samples
from backend.providers.source_labels import SESSION_SOURCES_LABEL

# v2: treadmill and virtual runs are flat and never grade-adjusted.
METHOD: Final = "pace-at-heart-rate-v2"
WARMUP_S: Final = 600
MIN_DURATION_S: Final = 1800
BIN_BPM: Final = 5
BAND_BINS: Final = 2
FLAT_GRADE_PCT: Final = 3.0
MIN_FLAT_SHARE: Final = 0.8
MIN_BAND_S: Final = 600
MAX_SPEED_CV: Final = 0.15
MIN_SESSIONS: Final = 2
SCOPE = (
    "Pace in a fixed heart-rate band on steady, flat-ish outdoor or indoor runs "
    "after a 10-minute warm-up; grade-adjusted where a slope is known. Heat, "
    "fatigue, hydration and caffeine move heart rate; no fitness claim."
)


def _ineligible(activity: Mapping[str, Any]) -> str | None:
    streams = activity.get("streams") or {}
    times = streams.get("time") or []
    if activity.get("sport") != "run" or activity.get("trail"):
        return "Keine Straßen- oder Bahn-Laufaktivität."
    if len(times) < 2 or times[-1] - times[0] < MIN_DURATION_S:
        return "Zu kurze oder fehlende Messreihe."
    for key in ("velocity_smooth", "heartrate"):
        if len(streams.get(key) or []) != len(times):
            return "Geschwindigkeit oder Puls fehlt."
    return None


def _paired(
    activity: Mapping[str, Any], grades: list[float | None] | None
) -> list[tuple[float, float, float, float | None]]:
    """(weight, speed, heart rate, grade) of moving samples after the warm-up."""
    times = activity["streams"]["time"]
    start, end = float(times[0]) + WARMUP_S, float(times[-1])
    view = {"streams": {**activity["streams"], "grade_pct": grades or []}}
    speed = _samples(view, "velocity_smooth", start, end)
    pulse = {t: (w, v) for t, w, v in _samples(view, "heartrate", start, end)}
    slope = {t: v for t, _, v in _samples(view, "grade_pct", start, end)}
    return [
        (min(weight, pulse[t][0]), value, pulse[t][1], slope.get(t))
        for t, weight, value in speed
        if value > 0 and t in pulse and 30 <= pulse[t][1] <= 240
    ]


def _bins(
    paired: Sequence[tuple[float, float, float, float | None]], graded: bool
) -> tuple[dict[int, dict[str, float]], float]:
    """Seconds, distance and squared speed per heart-rate bin of flat samples."""
    bins: dict[int, dict[str, float]] = defaultdict(
        lambda: {"seconds": 0.0, "distance_m": 0.0, "speed_sq": 0.0}
    )
    flat = 0.0
    for weight, speed, pulse, grade in paired:
        if graded and (grade is None or abs(grade) > FLAT_GRADE_PCT):
            continue
        level = grade_adjusted(speed, grade) if graded and grade is not None else speed
        entry = bins[int(pulse // BIN_BPM) * BIN_BPM]
        entry["seconds"] += weight
        entry["distance_m"] += level * weight
        entry["speed_sq"] += level * level * weight
        flat += weight
    return dict(bins), flat


def pace_at_heart_rate(
    activity: Mapping[str, Any], *, source_label: str = SESSION_SOURCES_LABEL
) -> dict[str, Any]:
    """Heart-rate bins of one run, or why it gives none (unknown, never zero)."""
    base = {
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "curve_method": METHOD_ID,
        "source": f"{source_label} original speed/heart-rate streams",
        "scope": SCOPE,
    }
    reason = _ineligible(activity)
    if reason is not None:
        return {**base, "status": "insufficient_data", "reason": reason, "bins": {}}
    # Treadmill and virtual runs have no terrain; a virtual course's altitude
    # or barometric drift never grade-adjusts or filters their pace.
    indoor = summary_is_indoor(activity)
    grades = None if indoor else grade_stream(activity["streams"])
    if grades is None and not indoor:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Gelände unbekannt: Steigung oder Höhe fehlt.",
            "bins": {},
        }
    paired = _paired(activity, grades)
    bins, flat = _bins(paired, grades is not None)
    total = sum(
        weight for weight, _, _, grade in paired if grades is None or grade is not None
    )
    known = sum(weight for weight, *_ in paired)
    if grades is not None and total < MIN_FLAT_SHARE * known:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Gelände unbekannt: Steigung lückenhaft.",
            "bins": {},
        }
    if not total or flat / total < MIN_FLAT_SHARE:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Zu hügelig oder zu wenig Puls- und Geschwindigkeitsdaten.",
            "bins": {},
        }
    return {
        **base,
        "status": "ok",
        "grade_adjusted": grades is not None,
        "flat_share": round(flat / total, 3),
        "bins": {str(low): values for low, values in sorted(bins.items())},
    }


POWER_METHOD: Final = "power-at-heart-rate-v1"
# The heart rate trails power by up to a minute: each heart-rate sample is
# paired with the mean power of the minute before it.
POWER_SMOOTH_S: Final = 60
_SPEED_KEYS: Final = ("distance_m", "speed_sq")
_POWER_KEYS: Final = ("work_j", "watts_sq")


def _smoothed_power(
    samples: Sequence[tuple[float, float, float]],
) -> dict[float, tuple[float, float]]:
    """(mean power of the last minute, own power) per sample start time."""
    smoothed: dict[float, tuple[float, float]] = {}
    total = weight = 0.0
    first = 0
    for time, width, watts in samples:
        total += width * watts
        weight += width
        while samples[first][0] < time - POWER_SMOOTH_S:
            total -= samples[first][1] * samples[first][2]
            weight -= samples[first][1]
            first += 1
        smoothed[time] = (total / weight if weight > 0 else 0.0, watts)
    return smoothed


def power_at_heart_rate(
    activity: Mapping[str, Any], *, source_label: str = SESSION_SOURCES_LABEL
) -> dict[str, Any]:
    """Seconds, work and squared power per heart-rate bin of one ride.

    After a 10-minute warm-up, moving gap-free samples with pedalling (own power
    above zero) count; power is the mean of the minute before each heart-rate
    sample. Unknown stays unknown, never zero.
    """
    base = {
        "method": POWER_METHOD,
        "source": f"{source_label} original watts/heart-rate streams",
    }
    streams = activity.get("streams") or {}
    times = streams.get("time") or []
    if activity.get("sport") != "ride":
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Keine Radfahrt.",
            "bins": {},
        }
    if (
        len(times) < 2
        or times[-1] - times[0] < MIN_DURATION_S
        or any(
            len(streams.get(key) or []) != len(times) for key in ("watts", "heartrate")
        )
    ):
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Zu kurz, oder Leistung oder Puls fehlt.",
            "bins": {},
        }
    start, end = float(times[0]) + WARMUP_S, float(times[-1])
    power = _smoothed_power(
        [
            s
            for s in _samples(dict(activity), "watts", start - POWER_SMOOTH_S, end)
            if s[2] >= 0
        ]
    )
    bins: dict[int, dict[str, float]] = defaultdict(
        lambda: {"seconds": 0.0, "work_j": 0.0, "watts_sq": 0.0}
    )
    for time, weight, pulse in _samples(dict(activity), "heartrate", start, end):
        mean, own = power.get(time, (0.0, 0.0))
        if own <= 0 or mean <= 0 or not 30 <= pulse <= 240:
            continue
        entry = bins[int(pulse // BIN_BPM) * BIN_BPM]
        entry["seconds"] += weight
        entry["work_j"] += mean * weight
        entry["watts_sq"] += mean * mean * weight
    if not bins:
        return {
            **base,
            "status": "insufficient_data",
            "reason": "Keine Abschnitte mit Leistung und Puls.",
            "bins": {},
        }
    return {
        **base,
        "status": "ok",
        "bins": {str(low): values for low, values in sorted(bins.items())},
    }


LT1_DAYS: Final = 60
LT1_MIN_SESSIONS: Final = 3


def output_at_heart_rate(
    records: Sequence[Mapping[str, Any]], sport: str, heart_rate: float, today: date
) -> float | None:
    """Run pace (s/km) or ride power (W) at a heart rate from own steady sessions.

    The band is the 10 bpm band of the 5 bpm bins whose centre is nearest to
    ``heart_rate``. Each session of the last ``LT1_DAYS`` days with at least 10
    steady minutes in it gives its time-weighted pace or power; the value is the
    median over at least ``LT1_MIN_SESSIONS`` sessions, outdoor runs before
    indoor ones. None without enough sessions (athlete decision 2026-11-12, #2427).
    """
    low = BIN_BPM * round((heart_rate - (BAND_BINS * BIN_BPM - 1) / 2) / BIN_BPM)
    first = (today - timedelta(days=LT1_DAYS - 1)).isoformat()
    profile_key, keys = (
        ("pace_at_hr_profile", _SPEED_KEYS)
        if sport == "run"
        else ("power_at_hr_profile", _POWER_KEYS)
    )
    for environment in ("outdoor", "indoor") if sport == "run" else (None,):
        values = [
            totals[1] / totals[0]
            for row in records
            if row.get("sport") == sport
            and environment in (None, row.get("environment"))
            and first <= str(row.get("date") or "") <= today.isoformat()
            and (row.get(profile_key) or {}).get("status") == "ok"
            and (totals := _band_totals(row[profile_key], low, keys))
        ]
        if len(values) >= LT1_MIN_SESSIONS:
            median = statistics.median(values)
            return 1000 / median if sport == "run" else median
    return None


def _band_totals(
    profile: Mapping[str, Any],
    low: int,
    keys: tuple[str, str] = _SPEED_KEYS,
) -> tuple[float, float, float] | None:
    """Seconds, output total and squared output of a steady session in the band."""
    bins: Mapping[str, Any] = profile.get("bins") or {}
    parts = [
        part
        for step in range(BAND_BINS)
        if (part := bins.get(str(low + step * BIN_BPM)))
    ]
    seconds = sum(part["seconds"] for part in parts)
    if seconds < MIN_BAND_S:
        return None
    distance = sum(part[keys[0]] for part in parts)
    squares = sum(part[keys[1]] for part in parts)
    mean = distance / seconds
    spread = math.sqrt(max(squares / seconds - mean * mean, 0.0))
    if mean <= 0 or spread / mean > MAX_SPEED_CV:
        return None
    return seconds, distance, squares


def _best_band(
    profiles: Sequence[tuple[bool, Mapping[str, Any]]],
) -> int | None:
    """Low edge of the band that qualifies the most sessions in the weaker half.

    ``profiles`` pairs "in the later half" with a session profile; ties go to
    more sessions, then more time, so one band serves both halves when possible.
    """
    lows = {
        int(low) - step * BIN_BPM
        for _, profile in profiles
        for low in (profile.get("bins") or {})
        for step in range(BAND_BINS)
    }
    scored = []
    for low in lows:
        found = [
            (later, totals)
            for later, profile in profiles
            if (totals := _band_totals(profile, low))
        ]
        halves = [
            sum(1 for later, _ in found if later is flag) for flag in (False, True)
        ]
        if found:
            scored.append(
                (min(halves), len(found), sum(item[1][0] for item in found), -low)
            )
    return -max(scored)[3] if scored else None


def _pace(seconds: float, distance: float) -> float:
    return round(1000 * seconds / distance, 1)


def _half(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    seconds = sum(row["seconds"] for row in rows)
    distance = sum(row["distance_m"] for row in rows)
    return {
        "sessions": len(rows),
        "pace_s_per_km": _pace(seconds, distance) if rows else None,
    }


def _environment_trend(
    records: Sequence[Mapping[str, Any]], halves: Mapping[str, tuple[date, date]]
) -> dict[str, Any]:
    middle = halves["later"][0].isoformat()
    first = halves["earlier"][0].isoformat()
    last = halves["later"][1].isoformat()
    # Curve records span the whole profile window; only the block counts.
    profiles = [
        (row, row["pace_at_hr_profile"])
        for row in records
        if first <= str(row.get("date") or "") <= last
        and (row.get("pace_at_hr_profile") or {}).get("status") == "ok"
    ]
    low = _best_band(
        [(str(row.get("date")) >= middle, profile) for row, profile in profiles]
    )
    sessions = []
    for row, profile in sorted(profiles, key=lambda item: str(item[0].get("date"))):
        totals = None if low is None else _band_totals(profile, low)
        if totals:
            sessions.append(
                {
                    "date": row.get("date"),
                    "activity_id": row.get("activity_id"),
                    "seconds": round(totals[0]),
                    "distance_m": round(totals[1]),
                    "pace_s_per_km": _pace(totals[0], totals[1]),
                    "grade_adjusted": bool(profile.get("grade_adjusted")),
                }
            )
    parts = {
        name: _half(
            [
                row
                for row in sessions
                if lo.isoformat() <= str(row["date"]) <= hi.isoformat()
            ]
        )
        for name, (lo, hi) in halves.items()
    }
    both = all(part["sessions"] for part in parts.values())
    later, earlier = parts["later"]["pace_s_per_km"], parts["earlier"]["pace_s_per_km"]
    return {
        "records": len(records),
        "usable_sessions": len(sessions),
        "status": "ok"
        if both and len(sessions) >= MIN_SESSIONS
        else "insufficient_data",
        "heart_rate_band_bpm": None
        if low is None
        else [low, low + BAND_BINS * BIN_BPM - 1],
        "sources": sorted({p["source"] for _, p in profiles if p.get("source")}),
        "sessions": sessions,
        **parts,
        "change_s_per_km": round(later - earlier, 1) if both else None,
    }


def pace_at_heart_rate_trend(
    records: Sequence[Mapping[str, Any]], start: date, middle: date, end: date
) -> dict[str, Any]:
    """Earlier-versus-later pace in one fixed heart-rate band per environment."""
    halves = {"earlier": (start, middle - timedelta(days=1)), "later": (middle, end)}
    return {
        "method": METHOD,
        "unit": "s/km",
        "scope": SCOPE,
        "run": {
            environment: _environment_trend(
                [
                    row
                    for row in records
                    if row.get("sport") == "run"
                    and row.get("environment") == environment
                ],
                halves,
            )
            for environment in ("outdoor", "indoor")
        },
    }


COMPARE_DAYS: Final = 42
MIN_COMPARABLE: Final = 3


def _not_covered(base: Mapping[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    return {**base, "status": "not_covered", "reason": reason, **extra}


def _shared_band(
    own: Mapping[str, Any], peers: Sequence[Mapping[str, Any]]
) -> tuple[int, tuple[float, float, float], list[tuple[float, float, float]]] | None:
    """The 10 bpm band with the most steady comparable runs that also holds this run."""
    lows = {
        int(low) - step * BIN_BPM
        for low in own.get("bins") or {}
        for step in range(BAND_BINS)
    }
    scored = []
    for low in lows:
        mine = _band_totals(own, low)
        if mine is None:
            continue
        found = [totals for peer in peers if (totals := _band_totals(peer, low))]
        scored.append(((len(found), mine[0], -low), low, mine, found))
    if not scored:
        return None
    _, low, mine, found = max(scored, key=lambda item: item[0])
    return low, mine, found


def session_comparison(
    records: Sequence[Mapping[str, Any]], activity_key: str
) -> dict[str, Any]:
    """Pace of one run in a heart-rate band against comparable steady runs.

    Comparable: earlier runs of the last ``COMPARE_DAYS`` days with the same
    environment and grade handling that have steady pace in the same band, the
    eligibility of the block trend. Too few of them, or an ineligible run, is
    ``not_covered`` with the reason, never zero.
    """
    base = {"method": METHOD, "unit": "s/km", "scope": SCOPE}
    own_row = next((r for r in records if r.get("activity_id") == activity_key), None)
    own = (own_row or {}).get("pace_at_hr_profile") or {}
    if own.get("status") != "ok" or own_row is None:
        return _not_covered(
            base,
            own.get("reason")
            or "Keine Messreihe in voller Auflösung für diese Aktivität.",
        )
    day = str(own_row.get("date") or "")
    try:
        first = (date.fromisoformat(day) - timedelta(days=COMPARE_DAYS)).isoformat()
    except ValueError:
        return _not_covered(base, "Datum der Aktivität unbekannt.")
    peers = [
        row["pace_at_hr_profile"]
        for row in records
        if row is not own_row
        and row.get("sport") == "run"
        and row.get("environment") == own_row.get("environment")
        and first <= str(row.get("date") or "") < day
        and (row.get("pace_at_hr_profile") or {}).get("status") == "ok"
        and bool(row["pace_at_hr_profile"].get("grade_adjusted"))
        == bool(own.get("grade_adjusted"))
    ]
    shared = _shared_band(own, peers)
    sources = {own.get("source")}
    if shared is None:
        return _not_covered(base, "Kein gleichmäßiges Tempo in einem Pulsband.")
    low, mine, found = shared
    sources |= {p.get("source") for p in peers if _band_totals(p, low)}
    window = {"window_days": COMPARE_DAYS, "count": len(found)}
    if len(found) < MIN_COMPARABLE:
        return _not_covered(
            base,
            f"Nur {len(found)} vergleichbare Läufe, mindestens {MIN_COMPARABLE} nötig.",
            comparable=window,
        )
    median = statistics.median(
        _pace(seconds, distance) for seconds, distance, _ in found
    )
    pace = _pace(mine[0], mine[1])
    return {
        **base,
        "status": "ok",
        "source": own.get("source"),
        "sources": sorted(str(item) for item in sources if item),
        "heart_rate_band_bpm": [low, low + BAND_BINS * BIN_BPM - 1],
        "grade_adjusted": bool(own.get("grade_adjusted")),
        "session": {"seconds": round(mine[0]), "pace_s_per_km": pace},
        "comparable": {**window, "median_pace_s_per_km": median},
        "difference_s_per_km": round(pace - median, 1),
        "direction": "positive difference = slower than comparable runs",
    }
