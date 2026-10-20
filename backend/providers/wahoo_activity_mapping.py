"""Map Wahoo Cloud workouts to canonical activity records.

The mapper is pure: it performs no I/O, logs nothing and never raises on
malformed provider input. A workout without a usable id or start time is
dropped with an issue. Any other malformed field becomes None with an issue, so
one bad field never drops a record. Issues name the record id and the field
only, never the provider value, and unknown fields are never copied.

Field rules:

* id: a positive integer (or its digit text) becomes the activity id.
* start: ``starts`` is an ISO 8601 instant in UTC. Text without an offset is
  read as UTC, as the Wahoo API documents. The athlete-local date is derived by
  the plan from the athlete zone, not from the workout's own ``time_zone``.
* duration: the summary's ``duration_active_accum`` before ``duration_total_accum``.
  The workout's own ``minutes`` is the PLANNED duration and is never used.
* distance (m), average heart rate, average power, ascent, average cadence,
  normalized power, energy and moving duration come from the summary, which
  arrives as decimal text and may be null until Wahoo has processed the workout.
  A missing summary is not an error. A zero cadence, normalized power, energy or
  training stress score means "not measured" and becomes None; a zero ascent is
  a real flat course and stays 0.
* sport and environment come from ``workout_type_id``. An id this table does
  not know maps to ``Sport.OTHER`` with an unknown environment.
* load: ``power_bike_tss_last`` is a Training Stress Score, modelled as
  ``LoadModel.TSS`` so it is never mixed with another provider's load. Without a
  positive value the load stays unknown.

Calories, speed and the workout file location stay out of the canonical record.
The stored raw record drops the summary ``file`` object, which carries a
download URL; see ``raw_workout_for_storage``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, tzinfo
from typing import Final

from backend.canonical.local_time import parse_provider_datetime
from backend.canonical.mapping import (
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_number,
)
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.validation import (
    HEART_RATE_BOUNDS,
    MAX_ACTIVITY_CADENCE_RPM,
    MAX_ACTIVITY_DISTANCE_M,
    MAX_ACTIVITY_DURATION_S,
    MAX_ACTIVITY_ELEVATION_M,
    MAX_ACTIVITY_ENERGY_KJ,
    MAX_ACTIVITY_LOAD,
    MAX_ACTIVITY_POWER_W,
)
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)

MAPPER_VERSION: Final = 2
WAHOO_LABEL: Final = "Wahoo"
MAX_NAME_LENGTH: Final = 200
MAX_WORKOUT_ID: Final = 2**63 - 1
# Same minimum as the other activity mappers: a zero duration is not usable.
_MIN_DURATION_S: Final = 1.0

_MOVING_DURATION_KEYS: Final = ("duration_active_accum",)
_TOTAL_DURATION_KEYS: Final = ("duration_total_accum",)
_DISTANCE_KEYS: Final = ("distance_accum",)
_AVERAGE_HR_KEYS: Final = ("heart_rate_avg",)
_AVERAGE_POWER_KEYS: Final = ("power_avg",)
_ELEVATION_KEYS: Final = ("ascent_accum",)
_CADENCE_KEYS: Final = ("cadence_avg",)
_NORMALIZED_POWER_KEYS: Final = ("power_bike_np_last",)
_WORK_JOULES_KEYS: Final = ("work_accum",)
_TSS_KEYS: Final = ("power_bike_tss_last",)
_SUMMARY_FILE_KEY: Final = "file"
_JOULES_PER_KJ: Final = 1000.0

_OUTDOOR: Final = Environment.OUTDOOR
_INDOOR: Final = Environment.INDOOR
_VIRTUAL: Final = Environment.VIRTUAL
_UNKNOWN: Final = Environment.UNKNOWN


def _entries(
    sport: Sport, environment: Environment, ids: tuple[int, ...]
) -> dict[int, tuple[Sport, Environment]]:
    return {type_id: (sport, environment) for type_id in ids}


# Wahoo workout_type_id values, from the Wahoo Cloud API documentation. Generic
# types (workout, fitness equipment, cardio class, unknown) are OTHER because
# they name no sport. Motorised and sail/board types are OTHER as well.
WAHOO_WORKOUT_TYPES: Final[Mapping[int, tuple[Sport, Environment]]] = {
    **_entries(Sport.RIDE, _OUTDOOR, (0, 11, 13, 15, 16)),
    **_entries(Sport.RIDE, _INDOOR, (12, 21, 49, 61)),
    **_entries(Sport.RIDE, _VIRTUAL, (68,)),
    **_entries(Sport.RIDE, _UNKNOWN, (14, 64, 70)),
    **_entries(Sport.RUN, _OUTDOOR, (1, 3, 4, 67)),
    **_entries(Sport.RUN, _INDOOR, (5,)),
    **_entries(Sport.RUN, _VIRTUAL, (71,)),
    **_entries(Sport.WALK, _OUTDOOR, (6, 7, 8)),
    **_entries(Sport.WALK, _INDOOR, (56,)),
    **_entries(Sport.HIKE, _OUTDOOR, (9, 10)),
    **_entries(Sport.SWIM, _INDOOR, (25,)),
    **_entries(Sport.SWIM, _OUTDOOR, (26,)),
    **_entries(Sport.ROW, _INDOOR, (22,)),
    **_entries(Sport.ROW, _UNKNOWN, (39,)),
    **_entries(Sport.NORDIC_SKI, _OUTDOOR, (30,)),
    **_entries(Sport.ALPINE_SKI, _OUTDOOR, (29,)),
    **_entries(Sport.YOGA, _UNKNOWN, (66,)),
    **_entries(Sport.OTHER, _INDOOR, (19, 20, 23, 44)),
    **_entries(
        Sport.OTHER,
        _UNKNOWN,
        (2, 17, 18, 27, 28, 31, 32, 33, 34, 35, 36, 37, 38, 40, 41)
        + (42, 43, 45, 46, 47, 62, 63, 65, 69, 255),
    ),
}


def _issue(ref: str | None, field: str, reason: IssueReason) -> MappingIssue:
    return MappingIssue(ref, field, reason)


def _positive(value: float | None) -> float | None:
    """Zero means "not measured" for cadence, power, energy and load."""
    return value if value else None


def wahoo_workout_id(row: Mapping[str, object]) -> str | None:
    """Return the canonical activity id of one workout row, or None when invalid."""
    return _WorkoutRow(row, []).workout_id()


def raw_workout_for_storage(row: object) -> object:
    """Return the workout as it is stored in the raw record.

    The summary ``file`` object carries a download URL, so it is never stored.
    Every other field is copied unchanged. A row without a summary ``file``, or
    one that is not an object, is returned as it is.
    """
    if not isinstance(row, Mapping):
        return row
    summary = row.get("workout_summary")
    if not isinstance(summary, Mapping) or _SUMMARY_FILE_KEY not in summary:
        return row
    stored = dict(row)
    stored["workout_summary"] = {
        key: value for key, value in summary.items() if key != _SUMMARY_FILE_KEY
    }
    return stored


class _WorkoutRow:
    """Reads the known fields of one workout and records an issue per fault."""

    def __init__(self, row: Mapping[str, object], issues: list[MappingIssue]) -> None:
        self._row = row
        self._issues = issues
        self._summary: Mapping[str, object] = {}
        self.record_ref: str | None = None

    def _fail(self, field: str, reason: IssueReason) -> None:
        self._issues.append(_issue(self.record_ref, field, reason))

    def workout_id(self) -> str | None:
        value = self._row.get("id")
        if value is None:
            self._fail("id", IssueReason.MISSING)
            return None
        if isinstance(value, str) and value.isascii() and value.isdigit():
            value = int(value) if len(value) <= 19 else -1
        if isinstance(value, bool) or not isinstance(value, int):
            self._fail("id", IssueReason.INVALID_TYPE)
            return None
        if not 0 < value <= MAX_WORKOUT_ID:
            self._fail("id", IssueReason.OUT_OF_RANGE)
            return None
        self.record_ref = str(value)
        return self.record_ref

    def started_at(self) -> datetime | None:
        value = self._row.get("starts")
        if value is None or (isinstance(value, str) and not value.strip()):
            self._fail("starts", IssueReason.MISSING)
            return None
        parsed = parse_provider_datetime(value, UTC)
        if parsed is None:
            self._fail("starts", IssueReason.INVALID_TYPE)
            return None
        return parsed

    def read_summary(self) -> None:
        summary = self._row.get("workout_summary")
        if summary is None:
            return
        if not isinstance(summary, Mapping):
            self._fail("workout_summary", IssueReason.INVALID_TYPE)
            return
        self._summary = summary

    def number(self, keys: tuple[str, ...], lower: float, upper: float) -> float | None:
        for key in keys:
            value = self._summary.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            number = coerce_number(value)
            if number is None:
                self._fail(key, IssueReason.INVALID_NUMBER)
            elif lower <= number <= upper:
                return number
            else:
                self._fail(key, IssueReason.OUT_OF_RANGE)
        return None

    def sport_and_environment(self) -> tuple[Sport, Environment]:
        value = self._row.get("workout_type_id")
        if value is None:
            self._fail("workout_type_id", IssueReason.MISSING)
            return Sport.OTHER, Environment.UNKNOWN
        if isinstance(value, str) and value.isascii() and value.isdigit():
            value = int(value) if len(value) <= 6 else -1
        if isinstance(value, bool) or not isinstance(value, int):
            self._fail("workout_type_id", IssueReason.INVALID_TYPE)
            return Sport.OTHER, Environment.UNKNOWN
        entry = WAHOO_WORKOUT_TYPES.get(value)
        if entry is None:
            self._fail("workout_type_id", IssueReason.UNKNOWN_VALUE)
            return Sport.OTHER, Environment.UNKNOWN
        return entry

    def name(self) -> str | None:
        value = self._row.get("name")
        if value is None:
            return None
        if not isinstance(value, str):
            self._fail("name", IssueReason.INVALID_TYPE)
            return None
        text = value.strip()
        return text[:MAX_NAME_LENGTH] if text else None


def _map_row(
    row: object, *, retrieved_at: datetime, issues: list[MappingIssue]
) -> ActivityRecord | None:
    if not isinstance(row, dict):
        issues.append(_issue(None, "row", IssueReason.INVALID_TYPE))
        return None
    reader = _WorkoutRow(row, issues)
    workout_id = reader.workout_id()
    started_at = reader.started_at()
    if workout_id is None or started_at is None:
        return None
    reader.read_summary()
    sport, environment = reader.sport_and_environment()
    moving_duration = reader.number(
        _MOVING_DURATION_KEYS, _MIN_DURATION_S, MAX_ACTIVITY_DURATION_S
    )
    duration = (
        moving_duration
        if moving_duration is not None
        else reader.number(
            _TOTAL_DURATION_KEYS, _MIN_DURATION_S, MAX_ACTIVITY_DURATION_S
        )
    )
    tss = _positive(reader.number(_TSS_KEYS, 0.0, MAX_ACTIVITY_LOAD))
    joules = reader.number(
        _WORK_JOULES_KEYS, 0.0, MAX_ACTIVITY_ENERGY_KJ * _JOULES_PER_KJ
    )
    return ActivityRecord(
        activity_id=workout_id,
        provenance=Provenance(
            provider=ProviderId.WAHOO,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=workout_id,
            recorded_by=RecordingOrigin.WAHOO,
            retrieved_at=retrieved_at,
            label=WAHOO_LABEL,
        ),
        sport=sport,
        environment=environment,
        started_at=started_at,
        duration_s=duration,
        distance_m=reader.number(_DISTANCE_KEYS, 0.0, MAX_ACTIVITY_DISTANCE_M),
        load=tss,
        load_model=LoadModel.TSS if tss is not None else LoadModel.UNKNOWN,
        avg_hr=reader.number(_AVERAGE_HR_KEYS, *HEART_RATE_BOUNDS),
        avg_power=reader.number(_AVERAGE_POWER_KEYS, 0.0, MAX_ACTIVITY_POWER_W),
        name=reader.name(),
        moving_duration_s=moving_duration,
        elevation_gain_m=reader.number(_ELEVATION_KEYS, 0.0, MAX_ACTIVITY_ELEVATION_M),
        normalized_power=_positive(
            reader.number(_NORMALIZED_POWER_KEYS, 0.0, MAX_ACTIVITY_POWER_W)
        ),
        avg_cadence=_positive(
            reader.number(_CADENCE_KEYS, 0.0, MAX_ACTIVITY_CADENCE_RPM)
        ),
        energy_kj=_positive(None if joules is None else joules / _JOULES_PER_KJ),
    )


def map_wahoo_activities(
    rows: object, *, zone: tzinfo, retrieved_at: datetime
) -> MappingResult[ActivityRecord]:
    """Map Wahoo workout rows; never raises on malformed row data.

    ``zone`` is accepted for the mapper signature shared with the other
    providers. Wahoo sends UTC instants, so no wall time needs localising here.
    ``retrieved_at`` must be timezone-aware.
    """
    del zone
    if retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    if not isinstance(rows, list):
        return MappingResult(issues=(_issue(None, "rows", IssueReason.INVALID_TYPE),))
    records: list[ActivityRecord] = []
    issues: list[MappingIssue] = []
    for row in rows:
        record = _map_row(row, retrieved_at=retrieved_at, issues=issues)
        if record is not None:
            records.append(record)
    return MappingResult(records=tuple(records), issues=tuple(issues))
