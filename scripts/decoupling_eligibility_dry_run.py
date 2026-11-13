"""Dry run of the aerobic decoupling eligibility (card M8, #1773) on a COPY of the database.

The script opens the copy with the key in ``APP_PASSWORD`` (never printed), as
the application does. Inside one transaction it upgrades the schema if needed,
reads every live ride and road run of the last ``--days`` (365) days with merged
full-resolution streams through the input path of the stored session metrics,
evaluates the eligibility gates of the session analysis (``aerobic_analysis``)
and candidate variability rules, and rolls everything back: the file is left
unchanged. It prints a counts-only JSON report to stdout per sport and
environment: sessions per gate, pass counts per rule and quartile summaries of
the variability measures. No ids, names, dates or single-session values.

Rules, with every other gate unchanged: the current rule is a coefficient of
variation (CV) of the output at most 15 % on the ~1 s samples of each half;
candidates use 30 s or 60 s rolling means; for rides also the variability index
(VI, normalized power over average power) of each half at most 1.05 or 1.10.
All of them read the samples the analysis pairs with heart rate (gaps, stops and
non-positive output excluded), so VI here is the VI of moving, pedalling time.
``trim`` removes the final 10 minutes symmetric to the warm-up and needs 20
minutes between the trims, like the 30-minute minimum with the warm-up.

Run it on a disposable copy only, in a container without network access::

    docker build -t pacecraft:local .
    docker network create --internal pacecraft-dry-run
    docker run --rm --network pacecraft-dry-run -e APP_PASSWORD \\
      -v "<copy directory>:/copy" \\
      -v "<repository>/scripts/decoupling_eligibility_dry_run.py:/app/scripts/decoupling_eligibility_dry_run.py:ro" \\
      pacecraft:local python -m scripts.decoupling_eligibility_dry_run /copy/intervals-coach.db

``-e APP_PASSWORD`` passes the variable from the calling shell without writing
its value on the command line. The copy directory must be writable for SQLite's
temporary WAL files; the database file itself is not modified.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_summary import activity_summaries
from backend.athlete.profile import timezone_name
from backend.canonical.activity_summary import summary_is_indoor, summary_local_date
from backend.db import activity_detail_store, row_factory
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import configure_cipher
from backend.performance.session_analysis import (
    _aerobic_output,
    _aerobic_sensor,
    _samples,
    aerobic_analysis,
)
from backend.performance.session_metrics import wants_metrics
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.session_metrics import _analysis_activity

DEFAULT_DAYS = 365
WARMUP_S = 600.0
COOLDOWN_S = 600.0
MIN_SESSION_S = 1800.0
MIN_TRIMMED_SPAN_S = MIN_SESSION_S - WARMUP_S
MIN_COVERAGE = 0.85
MAX_HALF_DIFFERENCE = 0.10
WINDOWS_S = (1, 30, 60)
PERCENTILES = (25, 50, 75, 90)
_INTERVALS = "intervals"
_GATES = ("not_road_run", "short", "terrain_unknown", "coverage")

# (timestamp, weight in seconds, output) of one half; heart rate is paired away.
Sample = tuple[float, float, float]
Series = Sequence[tuple[float, float]]


class _RolledBack(Exception):
    """Carries the report out of the transaction, which it rolls back."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("dry run rolled back")
        self.report = report


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


def _group_key(summary: Mapping[str, Any]) -> str:
    environment = "indoor" if summary_is_indoor(summary) else "outdoor"
    return f"{summary['sport']}/{environment}"


def _profile(db: Any, key_values: KeyValueRepository) -> dict[str, Any]:
    try:
        value = json.loads(key_values.get(db, "profile") or "{}")
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def _summaries(
    db: Any, zone: ZoneInfo, cutoff: date
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sessions = {
        session_id: records
        for session_id, records in CanonicalTableReader().activity_sessions(
            db, start=cutoff - timedelta(days=1)
        )
        if records
    }
    wanted = [
        dict(summary)
        for summary in activity_summaries(sessions.items(), zone)
        if wants_metrics(summary) and summary_local_date(summary) >= cutoff.isoformat()
    ]
    return wanted, sessions


def _with_streams(
    db: Any, summaries: Sequence[Mapping[str, Any]], sessions: Mapping[str, Any]
) -> set[str]:
    """The sessions the stored metrics decode: own full streams, not Intervals.icu."""
    keys = activity_detail_store.full_stream_keys(
        db, [str(summary["id"]) for summary in summaries]
    )
    return {
        session_id
        for session_id, own in keys.items()
        if session_id in sessions and any(key.provider != _INTERVALS for key in own)
    }


def _tally(db: Any, zone: ZoneInfo, cutoff: date) -> dict[str, GroupTally]:
    summaries, sessions = _summaries(db, zone, cutoff)
    streamed = _with_streams(db, summaries, sessions)
    groups = {
        f"{sport}/{environment}": GroupTally(sport)
        for sport in ("ride", "run")
        for environment in ("outdoor", "indoor")
    }
    for summary in summaries:
        group = groups[_group_key(summary)]
        group.counts["sessions"] += 1
        session_id = str(summary["id"])
        if session_id not in streamed:
            group.counts["without_streams"] += 1
            continue
        group.add(evaluate(_analysis_activity(db, session_id, sessions[session_id])))
    return groups


def _report(db: Any, days: int, today: date) -> dict[str, Any]:
    key_values = KeyValueRepository(lambda: "")
    zone = ZoneInfo(timezone_name(_profile(db, key_values).get("timezone")))
    groups = _tally(db, zone, today - timedelta(days=days))
    return {
        "rolled_back": True,
        "days": days,
        "groups": {
            key: {
                "sessions": group.counts["sessions"],
                "without_streams": group.counts["without_streams"],
                **group.report(),
            }
            for key, group in groups.items()
        },
    }


def dry_run(
    path: Path,
    password: str,
    *,
    backend: Any,
    configure: Callable[[Any, str], None] | None = configure_cipher,
    days: int = DEFAULT_DAYS,
    today: date | None = None,
) -> dict[str, Any]:
    """Evaluate ``path`` inside one transaction, roll back, and return the report."""
    if not path.is_file():
        raise FileNotFoundError("database copy not found")
    manager = DatabaseManager(
        path,
        backend,
        password=password,
        configure=configure,
        row_factory=row_factory,
        reader_count=1,
        persist_connections=False,
    )
    try:
        with manager.unit_of_work() as db:
            migrate_schema(db)
            day = today or datetime.now(UTC).date()
            raise _RolledBack(_report(db, days, day))
    except _RolledBack as rolled_back:
        return rolled_back.report
    finally:
        manager.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database", type=Path, help="path to a COPY of the database")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="look-back days")
    arguments = parser.parse_args(argv)
    password = os.environ.get("APP_PASSWORD", "")
    if len(password) < 12:
        print("APP_PASSWORD must be set (at least 12 characters).", file=sys.stderr)
        return 2
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
    except ImportError:
        print("SQLCipher is required; run the script in the image.", file=sys.stderr)
        return 2
    report = dry_run(
        arguments.database, password, backend=sqlcipher, days=arguments.days
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
