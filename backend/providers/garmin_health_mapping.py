"""Map Garmin health sections to canonical observations.

``map_garmin_health`` reads the collected Garmin snapshot: a mapping from section
name to payload, where a payload is one record (a dict) or a list of records.
Mapping is pure and never raises on malformed provider data. Each problem becomes
a ``MappingIssue`` that names the record index and the field only, never the
raw value.

Mapped sections and their canonical kinds:

* ``sleep``: SLEEP_DURATION (seconds) and SLEEP_SCORE.
* ``hrv``: HRV_RMSSD from the last-night average. The weekly average covers a
  different window, so it is not used as a stand-in.
* ``resting_hr``: RESTING_HR.
* ``readiness``: READINESS.
* ``max_metrics``: VO2MAX from the generic, cycling and running objects.
* ``running_threshold``: THRESHOLD_PACE in m/s (the raw Garmin speed, not the
  seconds-per-kilometre value that ``garmin_metrics._garmin_pace_seconds`` shows),
  THRESHOLD_HR for running and THRESHOLD_HR for cycling. Its ``power`` object is
  reported as UNSUPPORTED: ``garmin_metrics`` labels it running watts, but Garmin's
  lactate-threshold power is cycling-based, so no sport is assigned.
* ``cycling_ftp`` and ``cycling_ftp_history``: FTP for cycling.
* ``weight``: WEIGHT in kilograms, converted from the declared unit, and
  BODY_FAT in percent.

Time rule: observations are dated by ``calendarDate``, the field the collector
guarantees on dated records. No mapped health section carries a timestamp, so
``observed_at`` stays None and ``parse_provider_datetime`` is not needed.
``running_threshold`` has no date. The collector requests it as the latest value
on the sync day, so its observation day is the athlete-zone date of
``retrieved_at``.

Alias precedence: the first present, non-empty name in each field's tuple wins.
The tuples follow today's readers in ``backend/performance`` (``recovery_context``,
``planning_recovery``, ``garmin_weight``, ``garmin_metrics``).

Weight units: ``gram``/``g`` are divided by 1000, ``kilogram``/``kg`` are kept,
and ``pound``/``lb`` are converted. A missing or unrecognised unit is reported as
UNKNOWN_VALUE and never guessed. The reader's magnitude guess (values above 300
are grams) is deliberately not copied.

Ignored without an issue: sections with no canonical kind in this wave
(``activities``, ``gear``, ``daily_stats``, ``training_status``,
``heart_rate_zones``, ``race_predictions``, ``endurance_score``,
``running_tolerance``) and unknown keys. Body battery (charged and drained only,
no level) and the device-keyed ``daily_training_status`` and
``training_load_balance`` each yield one UNSUPPORTED issue per section.

Source kinds: sensor values (sleep duration, HRV, resting heart rate, scale weight
and body fat) are DEVICE_MEASURED. Garmin's calculations (sleep score, readiness,
VO2max, thresholds, FTP) are PROVIDER_REPORTED. The source record id is
``<section>:<calendarDate>``, with ``:<object>`` appended for nested objects, for
example ``max_metrics:2026-10-10:cycling``.

Plausibility: a value must be strictly positive and inside ``METRIC_BOUNDS``.
Zero is rejected for every metric because none of these values is legitimately
zero; a zero score is treated as a sentinel.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Final

from backend.canonical.local_time import local_date
from backend.canonical.mapping import (
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_number,
)
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.validation import METRIC_BOUNDS
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)

MAPPER_VERSION: Final = 1
GARMIN_LABEL: Final = "Garmin Connect"

_DATE_FIELD: Final = "calendarDate"
_DAY_TEXT_LENGTH: Final = 10  # "YYYY-MM-DD"
_DEVICE: Final = SourceKind.DEVICE_MEASURED
_PROVIDER: Final = SourceKind.PROVIDER_REPORTED
_GRAMS_PER_KILOGRAM: Final = 1000.0
_KG_PER_POUND: Final = 0.45359237
_GRAM_UNITS: Final = frozenset({"gram", "grams", "g"})
_KILOGRAM_UNITS: Final = frozenset({"kilogram", "kilograms", "kg"})
_POUND_UNITS: Final = frozenset({"pound", "pounds", "lb", "lbs"})
_WEIGHT_UNIT_FIELDS: Final = ("unitKey", "unit", "weightUnit")
_WEIGHT: Final = "weight"
_RUNNING_THRESHOLD: Final = "running_threshold"
_UNSUPPORTED_SECTIONS: Final = frozenset(
    {"body_battery", "daily_training_status", "training_load_balance"}
)


@dataclass(frozen=True, slots=True)
class _Field:
    """One numeric field. ``names`` are aliases in precedence order."""

    names: tuple[str, ...]
    kind: MetricKind
    source_kind: SourceKind
    sport: Sport | None = None


@dataclass(frozen=True, slots=True)
class _Group:
    """Fields read from the record itself (``key`` None) or from a nested object."""

    key: str | None
    fields: tuple[_Field, ...]


@dataclass(frozen=True, slots=True)
class _Entry:
    """Where one record's observations come from."""

    ref: str
    day: date
    record_id: str


_VO2MAX_NAMES: Final = ("vo2MaxPreciseValue",)

_GROUPED_SECTIONS: Final[Mapping[str, tuple[_Group, ...]]] = {
    "sleep": (
        _Group(
            None,
            (
                _Field(
                    ("sleepTimeSeconds", "sleepDuration"),
                    MetricKind.SLEEP_DURATION,
                    _DEVICE,
                ),
                _Field(
                    ("sleepScore", "overallSleepScore"),
                    MetricKind.SLEEP_SCORE,
                    _PROVIDER,
                ),
            ),
        ),
    ),
    "hrv": (
        _Group(
            None,
            (_Field(("hrvLastNight", "lastNightAvg"), MetricKind.HRV_RMSSD, _DEVICE),),
        ),
    ),
    "resting_hr": (
        _Group(
            None,
            (
                _Field(
                    ("restingHeartRate", "restingHR", "resting_heart_rate"),
                    MetricKind.RESTING_HR,
                    _DEVICE,
                ),
            ),
        ),
    ),
    "readiness": (
        _Group(None, (_Field(("score",), MetricKind.READINESS, _PROVIDER),)),
    ),
    "max_metrics": (
        _Group(
            "generic",
            (_Field(_VO2MAX_NAMES, MetricKind.VO2MAX, _PROVIDER),),
        ),
        _Group(
            "cycling",
            (_Field(_VO2MAX_NAMES, MetricKind.VO2MAX, _PROVIDER, Sport.RIDE),),
        ),
        _Group(
            "running",
            (_Field(_VO2MAX_NAMES, MetricKind.VO2MAX, _PROVIDER, Sport.RUN),),
        ),
    ),
    "cycling_ftp": (
        _Group(
            None,
            (
                _Field(
                    ("functionalThresholdPower", "ftp"),
                    MetricKind.FTP,
                    _PROVIDER,
                    Sport.RIDE,
                ),
            ),
        ),
    ),
    "cycling_ftp_history": (
        _Group(
            None,
            (
                _Field(
                    ("functionalThresholdPower", "ftp"),
                    MetricKind.FTP,
                    _PROVIDER,
                    Sport.RIDE,
                ),
            ),
        ),
    ),
}

_BODY_FAT_GROUP: Final = _Group(
    None,
    (
        _Field(
            (
                "bodyFat",
                "body_fat",
                "bodyFatPercent",
                "bodyFatPercentage",
                "fatPercent",
            ),
            MetricKind.BODY_FAT,
            _DEVICE,
        ),
    ),
)

_THRESHOLD_GROUP: Final = _Group(
    "speed_and_heart_rate",
    (
        _Field(("speed",), MetricKind.THRESHOLD_PACE, _PROVIDER, Sport.RUN),
        _Field(("heartRate",), MetricKind.THRESHOLD_HR, _PROVIDER, Sport.RUN),
        _Field(("heartRateCycling",), MetricKind.THRESHOLD_HR, _PROVIDER, Sport.RIDE),
    ),
)

_SECTION_ORDER: Final = (
    "sleep",
    "hrv",
    "resting_hr",
    "readiness",
    "max_metrics",
    _RUNNING_THRESHOLD,
    "cycling_ftp",
    "cycling_ftp_history",
    _WEIGHT,
    "body_battery",
    "daily_training_status",
    "training_load_balance",
)


def _first_value(record: Mapping[str, object], names: tuple[str, ...]) -> object | None:
    """Return the first present, non-empty alias, or None when none is present."""
    for name in names:
        value = record.get(name)
        if value is not None and value != "":
            return value
    return None


def _parse_day(text: object) -> date | None:
    """Parse a strict ``YYYY-MM-DD`` calendar date, or return None."""
    if not isinstance(text, str) or len(text) != _DAY_TEXT_LENGTH:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _entry(name: str, ref: str, day: date, suffix: str | None = None) -> _Entry:
    base = f"{name}:{day.isoformat()}"
    return _Entry(ref, day, base if suffix is None else f"{base}:{suffix}")


def _weight_kg(number: float, unit: object) -> float | None:
    """Convert a weight in its declared unit to kilograms, or None when unknown."""
    if not isinstance(unit, str):
        return None
    key = unit.strip().casefold()
    if key in _GRAM_UNITS:
        return number / _GRAMS_PER_KILOGRAM
    if key in _KILOGRAM_UNITS:
        return number
    if key in _POUND_UNITS:
        return number * _KG_PER_POUND
    return None


def _within_bounds(kind: MetricKind, number: float) -> bool:
    lower, upper = METRIC_BOUNDS[kind]
    return 0 < number and lower <= number <= upper


class _HealthMapping:
    """Collects the observations and issues of one ``map_garmin_health`` call."""

    def __init__(self, zone: tzinfo, retrieved_at: datetime) -> None:
        self._retrieved_at = retrieved_at
        self._sync_day = local_date(retrieved_at, zone)
        self.observations: list[Observation] = []
        self.issues: list[MappingIssue] = []

    def map_sections(self, sections: object) -> None:
        if not isinstance(sections, Mapping):
            self._issue(None, "sections", IssueReason.INVALID_TYPE)
            return
        for name in _SECTION_ORDER:
            if name in sections:
                self._map_section(name, sections[name])

    def _map_section(self, name: str, payload: object) -> None:
        if payload is None:
            return
        if name in _UNSUPPORTED_SECTIONS:
            self._issue(None, name, IssueReason.UNSUPPORTED)
        elif name == _WEIGHT:
            self._map_weight(payload)
        elif name == _RUNNING_THRESHOLD:
            self._map_running_threshold(payload)
        else:
            self._map_grouped(name, payload, _GROUPED_SECTIONS[name])

    def _map_grouped(
        self, name: str, payload: object, groups: tuple[_Group, ...]
    ) -> None:
        for ref, record in self._records(name, payload):
            day = self._record_day(record, ref, fallback=None)
            if day is not None:
                for group in groups:
                    self._map_group(name, record, group, ref, day)

    def _map_weight(self, payload: object) -> None:
        for ref, record in self._records(_WEIGHT, payload):
            day = self._record_day(record, ref, fallback=None)
            if day is not None:
                self._map_weight_kg(record, _entry(_WEIGHT, ref, day))
                self._map_group(_WEIGHT, record, _BODY_FAT_GROUP, ref, day)

    def _map_weight_kg(self, record: Mapping[str, object], entry: _Entry) -> None:
        number = self._number(record, ("weight",), entry.ref)
        if number is None:
            return
        kilograms = _weight_kg(number, _first_value(record, _WEIGHT_UNIT_FIELDS))
        if kilograms is None:
            self._issue(entry.ref, "weight", IssueReason.UNKNOWN_VALUE)
            return
        self._emit(entry, MetricKind.WEIGHT, kilograms, "weight", _DEVICE)

    def _map_running_threshold(self, payload: object) -> None:
        for ref, record in self._records(_RUNNING_THRESHOLD, payload):
            day = self._record_day(record, ref, fallback=self._sync_day)
            if day is not None:
                self._map_group(_RUNNING_THRESHOLD, record, _THRESHOLD_GROUP, ref, day)
                self._report_power(record, ref)

    def _report_power(self, record: Mapping[str, object], ref: str) -> None:
        power = record.get("power")
        if power is None:
            return
        if not isinstance(power, Mapping):
            self._issue(ref, "power", IssueReason.INVALID_TYPE)
        elif _first_value(power, ("functionalThresholdPower",)) is not None:
            self._issue(ref, "power.functionalThresholdPower", IssueReason.UNSUPPORTED)

    def _map_group(
        self,
        name: str,
        record: Mapping[str, object],
        group: _Group,
        ref: str,
        day: date,
    ) -> None:
        source: object = record if group.key is None else record.get(group.key)
        if source is None:
            return
        if not isinstance(source, Mapping):
            self._issue(ref, group.key or name, IssueReason.INVALID_TYPE)
            return
        entry = _entry(name, ref, day, group.key)
        for field in group.fields:
            number = self._number(source, field.names, ref)
            if number is not None:
                self._emit(
                    entry,
                    field.kind,
                    number,
                    field.names[0],
                    field.source_kind,
                    field.sport,
                )

    def _records(
        self, name: str, payload: object
    ) -> list[tuple[str, Mapping[str, object]]]:
        items: object = [payload] if isinstance(payload, Mapping) else payload
        if not isinstance(items, list):
            self._issue(None, name, IssueReason.INVALID_TYPE)
            return []
        rows: list[tuple[str, Mapping[str, object]]] = []
        for index, item in enumerate(items):
            ref = f"{name}[{index}]"
            if isinstance(item, Mapping):
                rows.append((ref, item))
            else:
                self._issue(ref, name, IssueReason.INVALID_TYPE)
        return rows

    def _record_day(
        self, record: Mapping[str, object], ref: str, *, fallback: date | None
    ) -> date | None:
        raw = _first_value(record, (_DATE_FIELD,))
        if raw is None:
            if fallback is None:
                self._issue(ref, _DATE_FIELD, IssueReason.MISSING)
            return fallback
        day = _parse_day(raw)
        if day is None:
            self._issue(ref, _DATE_FIELD, IssueReason.INVALID_TYPE)
        return day

    def _number(
        self, record: Mapping[str, object], names: tuple[str, ...], ref: str
    ) -> float | None:
        raw = _first_value(record, names)
        if raw is None:
            return None
        number = coerce_number(raw)
        if number is None:
            self._issue(ref, names[0], IssueReason.INVALID_NUMBER)
        return number

    def _emit(
        self,
        entry: _Entry,
        kind: MetricKind,
        number: float,
        field: str,
        source_kind: SourceKind,
        sport: Sport | None = None,
    ) -> None:
        if not _within_bounds(kind, number):
            self._issue(entry.ref, field, IssueReason.OUT_OF_RANGE)
            return
        provenance = Provenance(
            provider=ProviderId.GARMIN,
            source_kind=source_kind,
            source_record_id=entry.record_id,
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=self._retrieved_at,
            label=GARMIN_LABEL,
        )
        self.observations.append(
            Observation(
                kind=kind,
                value=MetricValue(number, kind.unit),
                observed_on=entry.day,
                observed_at=None,
                provenance=provenance,
                sport=sport,
            )
        )

    def _issue(self, record_ref: str | None, field: str, reason: IssueReason) -> None:
        self.issues.append(MappingIssue(record_ref, field, reason))


def map_garmin_health(
    sections: object, *, zone: tzinfo, retrieved_at: datetime
) -> MappingResult[Observation]:
    """Map the Garmin health sections of one snapshot to observations.

    ``zone`` is the athlete's zone, used to date ``running_threshold`` by the sync
    day. ``retrieved_at`` must be timezone-aware; a naive value is a programming
    error and raises ValueError. A non-mapping ``sections`` value yields an empty
    result with one INVALID_TYPE issue.
    """
    if retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    mapping = _HealthMapping(zone, retrieved_at)
    mapping.map_sections(sections)
    return MappingResult(
        records=tuple(mapping.observations), issues=tuple(mapping.issues)
    )
