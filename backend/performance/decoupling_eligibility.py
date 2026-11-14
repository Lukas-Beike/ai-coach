"""Decoupling eligibility of card M8 (#1773, #1832): counts-only pass rates per rule.

Reads every live ride and road run of the last ``days`` (365) days with merged
full-resolution streams through the input path of the stored session metrics,
evaluates the eligibility gates of the session analysis (``aerobic_analysis``)
and candidate variability rules, and reports per sport and environment:
sessions per gate, pass counts per rule and quartile summaries of the
variability measures. No ids, names, dates or single-session values.

Rules, with every other gate unchanged: the current rule is a coefficient of
variation (CV) of the output at most 15 % on the ~1 s samples of each half;
candidates use 30 s or 60 s rolling means; for rides also the variability index
(VI, normalized power over average power) of each half at most 1.05 or 1.10.
All of them read the samples the analysis pairs with heart rate (gaps, stops and
non-positive output excluded), so VI here is the VI of moving, pedalling time.
``trim`` removes the final 10 minutes symmetric to the warm-up and needs 20
minutes between the trims, like the 30-minute minimum with the warm-up.

``scripts/decoupling_eligibility_dry_run.py`` runs it on a database copy; the
diagnostics section ``decoupling_eligibility`` (#2779) builds it in the
background (``DecouplingEligibility``) until the M8 rule is decided (#2780).
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_summary import activity_summaries
from backend.athlete.profile import timezone_name
from backend.canonical.activity_summary import summary_is_indoor, summary_local_date
from backend.db import activity_detail_store
from backend.db.repositories import KeyValueRepository
from backend.performance.mean_max_curve import SessionCurveReader
from backend.performance.session_analysis import (
    _aerobic_output,
    _aerobic_sensor,
    _samples,
    aerobic_analysis,
)
from backend.performance.session_metrics import wants_metrics

DEFAULT_DAYS = 365
WARMUP_S = 600.0
COOLDOWN_S = 600.0
MIN_SESSION_S = 1800.0
MIN_TRIMMED_SPAN_S = MIN_SESSION_S - WARMUP_S
MIN_COVERAGE = 0.85
MAX_HALF_DIFFERENCE = 0.10
WINDOWS_S = (1, 30, 60)
PERCENTILES = (25, 50, 75, 90)
_GATES = ("not_road_run", "short", "terrain_unknown", "coverage")

# (timestamp, weight in seconds, output) of one half; heart rate is paired away.
Sample = tuple[float, float, float]
Series = Sequence[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class Half:
    """The variability measures of one half; ``None`` where not computable."""

    mean_output: float
    cv: Mapping[int, float | None]
    vi: float | None


@dataclass(frozen=True, slots=True)
class Outcome:
    """Coverage, halves and half difference of one analysed span."""

    gate: str | None
    halves: tuple[Half, Half] | None = None
    differs: bool = False


@dataclass(frozen=True, slots=True)
class Evaluation:
    """One session: its structural gate, the span as analysed, and trimmed."""

    gate: str | None
    full: Outcome | None = None
    trimmed: Outcome | None = None
    production_ok: bool = False


def _weighted_cv(series: Series) -> float | None:
    total = sum(weight for weight, _ in series)
    if total <= 0:
        return None
    mean = sum(weight * value for weight, value in series) / total
    if mean <= 0:
        return None
    variance = sum(weight * (value - mean) ** 2 for weight, value in series) / total
    return math.sqrt(variance) / mean


def _rolling(samples: Sequence[Sample], window: float) -> list[tuple[float, float]]:
    """Time-weighted rolling means that end at a sample and span the full window."""
    result: list[tuple[float, float]] = []
    queue: deque[Sample] = deque()
    weights = products = 0.0
    for sample in samples:
        stamp, weight, value = sample
        queue.append(sample)
        weights += weight
        products += weight * value
        while queue[0][0] <= stamp - window:
            _, old_weight, old_value = queue.popleft()
            weights -= old_weight
            products -= old_weight * old_value
        if stamp + weight - samples[0][0] >= window:
            result.append((weight, products / weights))
    return result


def _normalized_ratio(rolling: Series, mean_output: float) -> float | None:
    """NP (fourth-power mean of the 30 s rolling means) over the mean output."""
    total = sum(weight for weight, _ in rolling)
    if total <= 0 or mean_output <= 0:
        return None
    fourth = sum(weight * value**4 for weight, value in rolling) / total
    return fourth**0.25 / mean_output


def _half(samples: Sequence[Sample], *, power: bool) -> Half:
    series = [(weight, value) for _, weight, value in samples]
    duration = sum(weight for weight, _ in series)
    mean = sum(weight * value for weight, value in series) / duration
    rolled = {window: _rolling(samples, window) for window in WINDOWS_S[1:]}
    cv = {1: _weighted_cv(series)} | {w: _weighted_cv(r) for w, r in rolled.items()}
    vi = _normalized_ratio(rolled[30], mean) if power else None
    return Half(mean, cv, vi)


def _clip(
    paired: Sequence[tuple[float, float, float, float]], left: float, right: float
) -> list[Sample]:
    clipped: list[Sample] = []
    for stamp, weight, value, _ in paired:
        inside = min(stamp + weight, right) - max(stamp, left)
        if inside > 0:
            clipped.append((stamp, inside, value))
    return clipped


def _paired(
    activity: dict[str, Any], sensor: str, start: float, end: float
) -> list[tuple[float, float, float, float]]:
    """Output paired with heart rate on the same samples, as the analysis does."""
    pulse = {
        stamp: (weight, value)
        for stamp, weight, value in _samples(activity, "heartrate", start, end)
    }
    return [
        (stamp, min(weight, pulse[stamp][0]), value, pulse[stamp][1])
        for stamp, weight, value in _samples(activity, sensor, start, end)
        if value > 0 and stamp in pulse and 30 <= pulse[stamp][1] <= 240
    ]


def _outcome(
    activity: dict[str, Any], sensor: str, start: float, end: float
) -> Outcome:
    paired = _paired(activity, sensor, start, end)
    middle = (start + end) / 2
    halves: list[Half] = []
    for left, right in ((start, middle), (middle, end)):
        samples = _clip(paired, left, right)
        covered = sum(weight for _, weight, _ in samples)
        if covered < (right - left) * MIN_COVERAGE:
            return Outcome("coverage")
        halves.append(_half(samples, power=sensor == "watts"))
    first, second = halves
    differs = abs(second.mean_output / first.mean_output - 1) > MAX_HALF_DIFFERENCE
    return Outcome(None, (first, second), differs)


def _structure(
    activity: dict[str, Any],
) -> tuple[str | None, dict[str, Any], str, list[float]]:
    """The first structural gate, else the output view, its stream and the times."""
    sensor = _aerobic_sensor(activity)
    times = (activity.get("streams") or {}).get("time") or []
    if sensor is None:
        return "not_road_run", activity, "", times
    if len(times) < 2 or times[-1] - times[0] < MIN_SESSION_S:
        return "short", activity, sensor, times
    selected = _aerobic_output(activity, sensor)
    if selected is None:
        return "terrain_unknown", activity, sensor, times
    return None, selected[0], selected[1], times


def evaluate(activity: dict[str, Any]) -> Evaluation:
    """Evaluate one merged analysis input against every gate and span."""
    gate, view, sensor, times = _structure(activity)
    production_ok = (
        aerobic_analysis(dict(activity), source_label="").get("status") == "ok"
    )
    if gate is not None:
        return Evaluation(gate, production_ok=production_ok)
    start, end = float(times[0]) + WARMUP_S, float(times[-1])
    trimmed_end = end - COOLDOWN_S
    trimmed = (
        _outcome(view, sensor, start, trimmed_end)
        if trimmed_end - start >= MIN_TRIMMED_SPAN_S
        else None
    )
    return Evaluation(None, _outcome(view, sensor, start, end), trimmed, production_ok)


def _cv_rule(window: int) -> Callable[[Half], bool]:
    return lambda half: (value := half.cv[window]) is not None and value <= 0.15


def _vi_rule(limit: float) -> Callable[[Half], bool]:
    return lambda half: half.vi is not None and half.vi <= limit


CURRENT = "cv_1s_15"
RULES: dict[str, Callable[[Half], bool]] = {
    CURRENT: _cv_rule(1),
    "cv_30s_15": _cv_rule(30),
    "cv_60s_15": _cv_rule(60),
    "vi_30s_105": _vi_rule(1.05),
    "vi_30s_110": _vi_rule(1.10),
}
RIDE_ONLY_RULES = frozenset({"vi_30s_105", "vi_30s_110"})


def passes(outcome: Outcome | None, rule: str) -> bool:
    """Whether every other gate and the rule hold for both halves."""
    if outcome is None or outcome.gate is not None or outcome.differs:
        return False
    return outcome.halves is not None and all(
        RULES[rule](half) for half in outcome.halves
    )


def _percentile(ordered: Sequence[float], percent: int) -> float:
    position = (len(ordered) - 1) * percent / 100
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(values)
    result: dict[str, Any] = {"n": len(ordered)}
    for percent in PERCENTILES:
        result[f"p{percent}"] = (
            round(_percentile(ordered, percent), 3) if ordered else None
        )
    return result


def _worst(values: Sequence[float | None]) -> float | None:
    """The larger half value; ``None`` when either half has none."""
    known = [value for value in values if value is not None]
    return max(known) if len(known) == len(values) and known else None


class GroupTally:
    """Content-free counts and variability measures of one sport and environment."""

    def __init__(self, sport: str) -> None:
        self.sport = sport
        self.counts: Counter[str] = Counter()
        names = [*(f"cv_{window}s" for window in WINDOWS_S), "vi_30s"]
        self.measures: dict[str, list[float]] = {name: [] for name in names}

    def add(self, evaluation: Evaluation) -> None:
        self.counts["evaluated"] += 1
        self.counts["production_mismatch"] += evaluation.production_ok != passes(
            evaluation.full, CURRENT
        )
        if evaluation.gate is not None:
            self.counts[f"fail_{evaluation.gate}"] += 1
            return
        self._add_outcome(evaluation.full)
        for name in ("cv_1s_15", "cv_30s_15"):
            self.counts[f"trim_pass_{name}"] += passes(evaluation.trimmed, name)
        self.counts["trim_evaluable"] += evaluation.trimmed is not None and (
            evaluation.trimmed.gate is None
        )

    def _add_outcome(self, outcome: Outcome | None) -> None:
        assert outcome is not None
        if outcome.gate is not None:
            self.counts[f"fail_{outcome.gate}"] += 1
            return
        self.counts["past_coverage"] += 1
        if not passes(Outcome(None, outcome.halves), CURRENT):
            self.counts["fail_variable_output_current_rule"] += 1
        elif outcome.differs:
            self.counts["fail_halves_differ"] += 1
        for rule in RULES:
            self.counts[f"pass_{rule}"] += passes(outcome, rule)
        self._add_measures(outcome.halves or ())

    def _add_measures(self, halves: Sequence[Half]) -> None:
        for window in WINDOWS_S:
            self._keep(f"cv_{window}s", _worst([h.cv[window] for h in halves]))
        self._keep("vi_30s", _worst([h.vi for h in halves]))

    def _keep(self, name: str, value: float | None) -> None:
        if value is not None:
            self.measures[name].append(value)

    def report(self) -> dict[str, Any]:
        keys = ["evaluated", "production_mismatch", *(f"fail_{g}" for g in _GATES)]
        keys += ["fail_variable_output_current_rule", "fail_halves_differ"]
        keys += ["past_coverage", *(f"pass_{rule}" for rule in self._rules())]
        keys += ["trim_evaluable", "trim_pass_cv_1s_15", "trim_pass_cv_30s_15"]
        measures = [
            name for name in self.measures if self.sport == "ride" or "vi" not in name
        ]
        return {
            "counts": {key: self.counts[key] for key in keys},
            "max_half_distribution": {
                name: _distribution(self.measures[name]) for name in measures
            },
        }

    def _rules(self) -> list[str]:
        return [
            rule
            for rule in RULES
            if self.sport == "ride" or rule not in RIDE_ONLY_RULES
        ]


@dataclass(frozen=True, slots=True)
class Selection:
    """The sessions of the window, their records, and those with own full streams."""

    days: int
    summaries: list[dict[str, Any]]
    sessions: dict[str, Any]
    streamed: frozenset[str]


def select(
    db: Any,
    activity_sessions: Callable[..., Any],
    key_values: KeyValueRepository,
    today: date,
    days: int = DEFAULT_DAYS,
) -> Selection:
    """The live rides and runs of the last ``days`` days in the athlete's time zone.

    ``activity_sessions`` is ``CanonicalTableReader().activity_sessions``.
    Streamed are the sessions the stored metrics decode: own full streams,
    not Intervals.icu.
    """
    try:
        profile = json.loads(key_values.get(db, "profile") or "{}")
    except ValueError:
        profile = {}
    timezone = profile.get("timezone") if isinstance(profile, dict) else None
    cutoff = today - timedelta(days=days)
    sessions = {
        session_id: records
        for session_id, records in activity_sessions(
            db, start=cutoff - timedelta(days=1)
        )
        if records
    }
    summaries = [
        dict(summary)
        for summary in activity_summaries(
            sessions.items(), ZoneInfo(timezone_name(timezone))
        )
        if wants_metrics(summary) and summary_local_date(summary) >= cutoff.isoformat()
    ]
    keys = activity_detail_store.full_stream_keys(
        db, [str(summary["id"]) for summary in summaries]
    )
    streamed = frozenset(key for key in keys if key in sessions)
    return Selection(days, summaries, sessions, streamed)


def report(
    selection: Selection, evaluate_session: Callable[[str], Evaluation]
) -> dict[str, Any]:
    """The counts-only report; ``evaluate_session`` reads and evaluates one session."""
    groups = {
        f"{sport}/{environment}": GroupTally(sport)
        for sport in ("ride", "run")
        for environment in ("outdoor", "indoor")
    }
    for summary in selection.summaries:
        environment = "indoor" if summary_is_indoor(summary) else "outdoor"
        group = groups[f"{summary['sport']}/{environment}"]
        group.counts["sessions"] += 1
        session_id = str(summary["id"])
        if session_id not in selection.streamed:
            group.counts["without_streams"] += 1
            continue
        group.add(evaluate_session(session_id))
    return {
        "days": selection.days,
        "groups": {
            key: {
                "sessions": group.counts["sessions"],
                "without_streams": group.counts["without_streams"],
                **group.report(),
            }
            for key, group in groups.items()
        },
    }


class DecouplingEligibility:
    """The report for the diagnostics, built off the request path (#2779).

    The request reads only the session list; a changed list or stored input
    (``SessionCurveReader.background_records`` in a reader of its own) starts
    one background build that reads one session per read snapshot and, outside
    it, pauses as long as that session's own work took (#2761), so request
    threads keep the interpreter. ``pending`` before the first build,
    ``failed`` after a failed one.
    """

    def __init__(
        self,
        database_manager: Callable[[], Any],
        activity_sessions: Callable[..., Any],
        analysis_input: Callable[[Any, str, Any], dict[str, Any]],
        key_values: KeyValueRepository,
        today: Callable[[], date],
        slot: SessionCurveReader,
        *,
        pause: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.thread_time,
    ) -> None:
        self._database_manager = database_manager
        self._activity_sessions = activity_sessions
        self._analysis_input = analysis_input
        self._key_values = key_values
        self._today = today
        self._slot = slot
        self._pause = pause
        self._clock = clock

    def section(self) -> dict[str, Any]:
        manager = self._database_manager()
        with manager.read_snapshot() as db:
            selection = select(
                db, self._activity_sessions, self._key_values, self._today()
            )

            def evaluate_session(session_id: str) -> Evaluation:
                started = self._clock()
                with manager.read_snapshot() as one:
                    activity = self._analysis_input(
                        one, session_id, selection.sessions[session_id]
                    )
                evaluation = evaluate(activity)
                self._pause(self._clock() - started)
                return evaluation

            session_ids = [str(summary["id"]) for summary in selection.summaries]
            try:
                built = self._slot.background_records(
                    db,
                    session_ids,
                    ("decoupling_eligibility", selection.days),
                    lambda: [report(selection, evaluate_session)],
                )
            except RuntimeError:
                return {"status": "failed"}
        if built is None:
            return {"status": "pending"}
        records, current = built
        return {"status": "ready", "current": current, **records[0]}
