"""Record where canonical reads differ from the legacy performance readers.

Each synthetic case feeds the same Intervals.icu snapshot and Garmin payload to
two paths. The legacy path runs the builders in ``backend.performance``: current
metrics, recovery context, load context and body history. The canonical path
projects both snapshots and reads them with ``select_current`` or, for the body
series, a per-provider first-by-day view. Every compared field whose normalized
value differs becomes one ledger row, keyed by case, field and point.

Values are normalized before comparison: numbers compare as floats, so 42 and
42.0 are equal, and dates compare as ISO text. Units are not converted. A sleep
duration in seconds against legacy hours is therefore a row, and the canonical
value is recorded as stored. A field with no rows in any case is switchable: its
consumer could read the canonical value without changing its output. Source
labels are recorded for the current metrics but never compared.

The recorded ledger is ``tests/fixtures/consumer_parity_ledger.json``. Running
``python tests/canonical_consumer_parity.py`` compares the computed ledger with
it and exits non-zero on any difference. ``--snapshot`` records the computed
ledger, but refuses to record new or changed rows; removed rows may be recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Final

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance.body import (
    GARMIN_SOURCE,
    INTERVALS_SOURCE,
    body_history,
)
from backend.performance.current_metrics import (
    current_performance_metrics,
)
from backend.performance.garmin_metrics import (
    garmin_performance_metrics,
)
from backend.performance.load_context import performance_load_context
from backend.performance.recovery_context import (
    performance_recovery_context,
)
from backend.performance.source_policy import select_current
from backend.providers.snapshot_projection import (
    project_garmin_snapshot,
    project_intervals_snapshot,
)

ZONE: Final[tzinfo] = UTC
RETRIEVED_AT: Final = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
TODAY: Final = date(2026, 10, 12)
LEDGER_PATH: Final = (
    Path(__file__).resolve().parent / "fixtures" / "consumer_parity_ledger.json"
)
REGENERATE_COMMAND: Final = "python tests/canonical_consumer_parity.py --snapshot"
LEDGER_DESCRIPTION: Final = (
    "Consumer parity ledger: rows where the canonical read path (projection plus "
    "select_current or the per-provider daily view) differs from the legacy "
    "performance readers on the same synthetic inputs. A field without rows is "
    "switchable. Rows may only be removed; record them with the regeneration "
    "command, which refuses new or changed rows."
)
_BODY_WINDOWS: Final = (("14d", 14), ("12w", 84))
_BODY_SOURCES: Final[Mapping[str, ProviderId]] = {
    INTERVALS_SOURCE: ProviderId.INTERVALS,
    GARMIN_SOURCE: ProviderId.GARMIN,
}


@dataclass(frozen=True, slots=True)
class CurrentField:
    """A current metric: canonical kind and sport against a legacy output key."""

    name: str
    kind: MetricKind
    sport: Sport | None
    legacy_key: str


@dataclass(frozen=True, slots=True)
class KindField:
    """A recovery value: canonical kind against a legacy recovery key.

    ``day`` compares the observed date of the selected observation instead of
    its value.
    """

    name: str
    kind: MetricKind
    legacy_key: str
    day: bool = False


CURRENT_FIELDS: Final[tuple[CurrentField, ...]] = (
    CurrentField("weight_kg", MetricKind.WEIGHT, None, "weight_kg"),
    CurrentField("body_fat_pct", MetricKind.BODY_FAT, None, "body_fat_pct"),
    CurrentField("cycling_ftp_watts", MetricKind.FTP, Sport.RIDE, "cycling_ftp_watts"),
    CurrentField(
        "run_threshold_watts", MetricKind.FTP, Sport.RUN, "run_threshold_watts"
    ),
    CurrentField(
        "bike_threshold_hr_bpm",
        MetricKind.THRESHOLD_HR,
        Sport.RIDE,
        "bike_threshold_hr_bpm",
    ),
    CurrentField(
        "run_threshold_hr_bpm",
        MetricKind.THRESHOLD_HR,
        Sport.RUN,
        "run_threshold_hr_bpm",
    ),
    CurrentField(
        "run_threshold_pace",
        MetricKind.THRESHOLD_PACE,
        Sport.RUN,
        "run_threshold_pace_seconds_per_km",
    ),
    CurrentField(
        "cycling_vo2max_ml_kg_min",
        MetricKind.VO2MAX,
        Sport.RIDE,
        "cycling_vo2max_ml_kg_min",
    ),
    CurrentField(
        "running_vo2max_ml_kg_min",
        MetricKind.VO2MAX,
        Sport.RUN,
        "running_vo2max_ml_kg_min",
    ),
    CurrentField(
        "cycling_max_hr_bpm", MetricKind.MAX_HR, Sport.RIDE, "cycling_max_hr_bpm"
    ),
    CurrentField(
        "running_max_hr_bpm", MetricKind.MAX_HR, Sport.RUN, "running_max_hr_bpm"
    ),
)
RECOVERY_FIELDS: Final[tuple[KindField, ...]] = (
    KindField("sleep_hours", MetricKind.SLEEP_DURATION, "sleep_hours"),
    KindField("sleep_score", MetricKind.SLEEP_SCORE, "sleep_score"),
    KindField("resting_hr", MetricKind.RESTING_HR, "resting_hr"),
    KindField("resting_hr_date", MetricKind.RESTING_HR, "resting_hr_date", day=True),
    KindField("readiness", MetricKind.READINESS, "readiness"),
)
LOAD_FIELDS: Final[tuple[KindField, ...]] = (
    KindField("ctl", MetricKind.CTL, "ctl"),
    KindField("atl", MetricKind.ATL, "atl"),
)
BODY_FIELDS: Final[tuple[KindField, ...]] = (
    KindField("body_weight_kg_series", MetricKind.WEIGHT, "weight_kg"),
    KindField("body_fat_pct_series", MetricKind.BODY_FAT, "body_fat_pct"),
)
FIELD_NAMES: Final[tuple[str, ...]] = (
    *(field.name for field in CURRENT_FIELDS),
    *(field.name for field in RECOVERY_FIELDS),
    *(field.name for field in LOAD_FIELDS),
    *(field.name for field in BODY_FIELDS),
)


@dataclass(frozen=True, slots=True)
class Case:
    """Synthetic stored inputs shared by the legacy and canonical paths."""

    name: str
    intervals: dict[str, Any]
    garmin: dict[str, Any]
    profile: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Pair:
    """One compared value: the legacy output and the canonical read."""

    field: str
    point: str
    legacy: object
    canonical: object


@dataclass(frozen=True, slots=True)
class Label:
    """Source labels for one current field, recorded but never compared."""

    field: str
    legacy_source: object
    canonical_provider: object


@dataclass(frozen=True, slots=True)
class CaseResult:
    pairs: tuple[Pair, ...]
    labels: tuple[Label, ...]


def _garmin_complete() -> dict[str, Any]:
    day = "2026-10-11"
    return {
        "synced_at": "2026-10-12T06:00:00+00:00",
        "weight": [
            {"calendarDate": day, "weight": 80.4, "bodyFat": 15.2},
            {"calendarDate": day, "weight": 80.1},
        ],
        "sleep": [{"calendarDate": day, "sleepTimeSeconds": 26400, "sleepScore": 84}],
        "resting_hr": [{"calendarDate": day, "restingHeartRate": 45}],
        "hrv": [{"calendarDate": day, "hrvLastNight": 66}],
        "readiness": [{"calendarDate": day, "score": 70}],
        "max_metrics": [
            {
                "calendarDate": day,
                "generic": {"vo2MaxPreciseValue": 56.1},
                "cycling": {"vo2MaxPreciseValue": 58.0},
                "running": {"vo2MaxPreciseValue": 53.5},
            }
        ],
        "cycling_ftp": [{"calendarDate": day, "functionalThresholdPower": 262}],
        "cycling_ftp_history": [
            {"calendarDate": "2026-10-12", "functionalThresholdPower": 268}
        ],
        "running_threshold": [
            {
                "speed_and_heart_rate": {
                    "speed": 3.9,
                    "heartRate": 171,
                    "heartRateCycling": 166,
                },
                "power": {"functionalThresholdPower": 215},
            }
        ],
        "heart_rate_zones": [
            {"sport": "cycling", "maxHeartRateUsed": 184},
            {"sport": "running", "maxHeartRateUsed": 188},
        ],
    }


def _intervals_complete() -> dict[str, Any]:
    return {
        "synced_at": "2026-10-12T06:00:00+00:00",
        "athlete": {
            "id": "athlete-1",
            "sport_settings": [
                {
                    "id": 1,
                    "types": ["Ride"],
                    "ftp": 265,
                    "lthr": 168,
                    "max_hr": 186,
                    "vo2max": 57.5,
                },
                {
                    "id": 2,
                    "types": ["Run"],
                    "threshold_pace": 3.9,
                    "lthr": 172,
                    "max_hr": 190,
                    "vo2max": 54.0,
                },
            ],
        },
        "recent_wellness": [
            {"id": "2026-10-10", "weight": 80.9, "restingHR": 47, "sleepSecs": 25200},
            {
                "id": "2026-10-11",
                "weight": 80.6,
                "bodyFat": 12.5,
                "restingHR": 46,
                "hrv": 62.0,
                "sleepSecs": 27000,
                "sleepScore": 81,
                "readiness": 74,
                "ctl": 58.2,
                "atl": 61.4,
            },
        ],
        "recent_activities": [],
    }


def _build_cases() -> tuple[Case, ...]:
    intervals_only = _intervals_complete()
    intervals_only["athlete"]["sport_settings"] = [
        {"id": 1, "types": ["Ride"], "ftp": 265, "lthr": 168, "vo2max": 57.5},
        {
            "id": 2,
            "types": ["Run"],
            "threshold_pace": 3.9,
            "lthr": 172,
            "vo2max": 54.0,
        },
    ]
    intervals_only["recent_activities"] = [
        {
            "id": "ride-1",
            "type": "Ride",
            "start_date_local": "2026-10-10T08:00:00",
            "max_heartrate": 181,
        },
        {
            "id": "run-1",
            "type": "Run",
            "start_date_local": "2026-10-09T07:00:00",
            "max_heartrate": 176,
        },
    ]
    sparse = {
        "synced_at": "2026-10-12T06:00:00+00:00",
        "athlete": {"id": "athlete-2", "weight": "79.9"},
        "recent_wellness": [
            {
                "id": "2026-10-11",
                "weight": "80,4",
                "restingHR": 47,
                "ctl": "58,2",
                "atl": 61.0,
            }
        ],
        "recent_activities": [],
    }
    sparse_garmin = {
        "sleep": [
            {"calendarDate": "2026-10-11", "sleepTimeSeconds": 0, "sleepScore": 0}
        ],
        "resting_hr": [{"calendarDate": "2026-10-11", "restingHeartRate": 12}],
    }
    return (
        Case("complete", _intervals_complete(), _garmin_complete(), {}),
        Case("intervals_only", intervals_only, {}, {}),
        Case(
            "sparse_profile",
            sparse,
            sparse_garmin,
            {"weight_kg": 78.0, "body_fat_pct": 14.0},
        ),
        Case(
            "garmin_only",
            {"athlete": {}, "recent_wellness": []},
            _garmin_complete(),
            {},
        ),
    )


CASES: Final[tuple[Case, ...]] = _build_cases()


def _normalize(value: object) -> object:
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _same(left: object, right: object) -> bool:
    return _normalize(left) == _normalize(right)


def _wellness_rows(intervals: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = intervals.get("recent_wellness")
    return (
        [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    )


def _latest_wellness(intervals: Mapping[str, Any]) -> dict[str, Any]:
    return max(
        _wellness_rows(intervals),
        key=lambda row: str(row.get("id") or ""),
        default={},
    )


def _latest_wellness_day(latest: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(latest.get("id")))
    except ValueError:
        return None


def _observations(case: Case) -> tuple[Observation, ...]:
    _, intervals = project_intervals_snapshot(
        case.intervals, zone=ZONE, retrieved_at=RETRIEVED_AT
    )
    _, garmin = project_garmin_snapshot(
        case.garmin, zone=ZONE, retrieved_at=RETRIEVED_AT
    )
    return (*intervals.records, *garmin.records)


def _value(observation: Observation | None) -> object:
    return None if observation is None else observation.value.value


def _day_value(observation: Observation | None) -> object:
    return None if observation is None else observation.observed_on.isoformat()


def _provider(observation: Observation | None) -> object:
    if observation is None or observation.provenance.provider is None:
        return None
    return observation.provenance.provider.value


def _current_results(
    case: Case,
    observations: Sequence[Observation],
    latest_day: date | None,
) -> tuple[list[Pair], list[Label]]:
    garmin_metrics = garmin_performance_metrics(case.garmin, TODAY)
    legacy = current_performance_metrics(case.intervals, case.profile, garmin_metrics)
    pairs: list[Pair] = []
    labels: list[Label] = []
    for spec in CURRENT_FIELDS:
        observation = select_current(
            observations,
            spec.kind,
            sport=spec.sport,
            latest_wellness_day=latest_day,
        )
        output = legacy[spec.legacy_key]
        pairs.append(Pair(spec.name, "current", output["value"], _value(observation)))
        labels.append(Label(spec.name, output["source"], _provider(observation)))
    return pairs, labels


def _recovery_pairs(
    case: Case,
    observations: Sequence[Observation],
    latest_day: date | None,
) -> list[Pair]:
    legacy = performance_recovery_context(
        case.garmin,
        _latest_wellness(case.intervals),
        _wellness_rows(case.intervals),
        TODAY,
    )
    pairs: list[Pair] = []
    for spec in RECOVERY_FIELDS:
        observation = select_current(
            observations, spec.kind, latest_wellness_day=latest_day
        )
        canonical = _day_value(observation) if spec.day else _value(observation)
        pairs.append(Pair(spec.name, "current", legacy[spec.legacy_key], canonical))
    return pairs


def _load_pairs(
    case: Case,
    observations: Sequence[Observation],
    latest_day: date | None,
) -> list[Pair]:
    legacy = performance_load_context(
        case.intervals.get("recent_activities", []),
        _wellness_rows(case.intervals),
        _latest_wellness(case.intervals),
        TODAY,
    )["load"]
    pairs: list[Pair] = []
    for spec in LOAD_FIELDS:
        observation = select_current(
            observations, spec.kind, latest_wellness_day=latest_day
        )
        pairs.append(
            Pair(spec.name, "current", legacy[spec.legacy_key], _value(observation))
        )
    return pairs


def _is_athlete_record(observation: Observation) -> bool:
    """Return True for Intervals values taken from the athlete record.

    Mirrors the source policy rule: a wellness observation's record id is its own
    ISO day, so any other Intervals record id is an athlete-level value that is not
    a dated body measurement.
    """
    return observation.provenance.provider is ProviderId.INTERVALS and (
        observation.provenance.source_record_id != observation.observed_on.isoformat()
    )


def _daily_by_provider(
    observations: Sequence[Observation], kind: MetricKind, start: date
) -> dict[ProviderId, dict[date, object]]:
    """Last dated observation per provider and day in the window, as legacy body.

    Legacy body history overwrites on a repeated day, so the last record wins here
    too. Athlete-record values are excluded because they are not body measurements.
    """
    result: dict[ProviderId, dict[date, object]] = {}
    for observation in observations:
        provider = observation.provenance.provider
        if (
            provider is None
            or observation.kind is not kind
            or _is_athlete_record(observation)
            or not start <= observation.observed_on <= TODAY
        ):
            continue
        result.setdefault(provider, {})[observation.observed_on] = (
            observation.value.value
        )
    return result


def _series_pairs(
    field: str,
    window: str,
    days: int,
    series: Sequence[Mapping[str, Any]],
    canonical_days: Mapping[ProviderId, Mapping[date, object]],
) -> list[Pair]:
    start = TODAY - timedelta(days=days - 1)
    legacy_by_source = {
        entry["source"]: {point["date"]: point["value"] for point in entry["points"]}
        for entry in series
    }
    pairs: list[Pair] = []
    for source, provider in _BODY_SOURCES.items():
        legacy_days = legacy_by_source.get(source, {})
        provider_days = canonical_days.get(provider, {})
        for index in range(days):
            day = start + timedelta(days=index)
            pairs.append(
                Pair(
                    field,
                    f"{window}:{provider.value}:{day.isoformat()}",
                    legacy_days.get(day.isoformat()),
                    provider_days.get(day),
                )
            )
    return pairs


def _body_pairs(case: Case, observations: Sequence[Observation]) -> list[Pair]:
    windows = body_history(case.intervals, case.garmin, TODAY)["windows"]
    pairs: list[Pair] = []
    for window, days in _BODY_WINDOWS:
        metrics = windows[window]["metrics"]
        start = TODAY - timedelta(days=days - 1)
        for spec, legacy_key in (
            (BODY_FIELDS[0], "weight_kg"),
            (BODY_FIELDS[1], "body_fat_pct"),
        ):
            canonical = _daily_by_provider(observations, spec.kind, start)
            pairs.extend(
                _series_pairs(spec.name, window, days, metrics[legacy_key], canonical)
            )
    return pairs


def _evaluate(case: Case) -> CaseResult:
    observations = _observations(case)
    latest_day = _latest_wellness_day(_latest_wellness(case.intervals))
    current_pairs, labels = _current_results(case, observations, latest_day)
    pairs = [
        *current_pairs,
        *_recovery_pairs(case, observations, latest_day),
        *_load_pairs(case, observations, latest_day),
        *_body_pairs(case, observations),
    ]
    return CaseResult(tuple(pairs), tuple(labels))


def _row(case: str, pair: Pair) -> dict[str, Any]:
    return {
        "case": case,
        "field": pair.field,
        "point": pair.point,
        "legacy": _normalize(pair.legacy),
        "canonical": _normalize(pair.canonical),
    }


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row["case"]), str(row["field"]), str(row["point"]))


def _describe(row: Mapping[str, Any]) -> str:
    return (
        f"{row['case']} {row['field']} {row['point']!r}: "
        f"legacy {row['legacy']!r}, canonical {row['canonical']!r}"
    )


def _collect(case: Case, result: CaseResult, state: dict[str, Any]) -> None:
    for pair in result.pairs:
        state["compared"][pair.field] += 1
        if _same(pair.legacy, pair.canonical):
            if pair.legacy is not None:
                state["matched"][pair.field] += 1
        else:
            state["rows"].append(_row(case.name, pair))
            state["differing"][pair.field] += 1
    for label in result.labels:
        state["labels"].append(
            {
                "case": case.name,
                "field": label.field,
                "legacy_source": _normalize(label.legacy_source),
                "canonical_provider": _normalize(label.canonical_provider),
            }
        )


def compute_ledger() -> dict[str, Any]:
    state: dict[str, Any] = {
        "compared": dict.fromkeys(FIELD_NAMES, 0),
        "matched": dict.fromkeys(FIELD_NAMES, 0),
        "differing": dict.fromkeys(FIELD_NAMES, 0),
        "rows": [],
        "labels": [],
    }
    for case in CASES:
        _collect(case, _evaluate(case), state)
    fields = {
        name: {
            "compared": state["compared"][name],
            "matched": state["matched"][name],
            "rows": state["differing"][name],
            "switchable": state["differing"][name] == 0,
        }
        for name in FIELD_NAMES
    }
    return {
        "description": LEDGER_DESCRIPTION,
        "regeneration": REGENERATE_COMMAND,
        "cases": [case.name for case in CASES],
        "fields": fields,
        "rows": sorted(state["rows"], key=_row_key),
        "labels": state["labels"],
    }


def _rows_by_key(
    ledger: Mapping[str, Any],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {_row_key(row): dict(row) for row in ledger.get("rows", [])}


def ledger_refusals(
    baseline: Mapping[str, Any] | None, current: Mapping[str, Any]
) -> list[str]:
    """Return why a snapshot must not be recorded; an empty list means allowed.

    A ``None`` baseline means the committed file does not exist yet, which is only
    the bootstrap case. Once a baseline exists, new or changed rows are refused.
    Removed rows are allowed.
    """
    if not any(summary["compared"] for summary in current["fields"].values()):
        return ["the ledger compared no fields; refusing to record an empty ledger"]
    if baseline is None:
        return []
    recorded = _rows_by_key(baseline)
    refusals: list[str] = []
    for row in current["rows"]:
        previous = recorded.get(_row_key(row))
        if previous is None:
            refusals.append(f"refusing to record growth: new {_describe(row)}")
        elif previous != row:
            refusals.append(f"refusing to record growth: changed {_describe(row)}")
    return refusals


def compare_ledger(
    recorded: Mapping[str, Any], computed: Mapping[str, Any]
) -> list[str]:
    """Return one message per row that differs, plus any summary or label mismatch."""
    recorded_rows = _rows_by_key(recorded)
    computed_rows = _rows_by_key(computed)
    messages: list[str] = []
    for key in sorted(set(recorded_rows) | set(computed_rows)):
        before = recorded_rows.get(key)
        after = computed_rows.get(key)
        if before is None and after is not None:
            messages.append(f"new: {_describe(after)}")
        elif after is None and before is not None:
            messages.append(f"obsolete: {_describe(before)}")
        elif before != after:
            messages.append(f"changed: {_describe(computed_rows[key])}")
    if recorded.get("fields") != computed.get("fields"):
        messages.append("field summary differs from the recorded ledger")
    if recorded.get("labels") != computed.get("labels"):
        messages.append("source labels differ from the recorded ledger")
    return messages


def render_ledger(ledger: Mapping[str, Any]) -> str:
    return json.dumps(ledger, indent=2, ensure_ascii=False) + "\n"


def load_ledger(path: Path = LEDGER_PATH) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def write_ledger(ledger: Mapping[str, Any], path: Path = LEDGER_PATH) -> None:
    # Fixed LF endings keep the snapshot byte-identical on Windows and Linux.
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_ledger(ledger))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="record the computed ledger, refusing new or changed rows",
    )
    arguments = parser.parse_args(argv)
    current = compute_ledger()
    if arguments.snapshot:
        baseline = load_ledger() if LEDGER_PATH.exists() else None
        refusals = ledger_refusals(baseline, current)
        if refusals:
            for refusal in refusals:
                print(refusal)
            return 1
        write_ledger(current)
        print(f"Wrote {len(current['rows'])} ledger rows to {LEDGER_PATH}.")
        return 0
    messages = compare_ledger(load_ledger(), current)
    if not messages:
        print("Consumer parity ledger matches the recorded ledger.")
        return 0
    for message in messages:
        print(message)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
