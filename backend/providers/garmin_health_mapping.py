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
* ``heart_rate_zones``: MAX_HR for each sport category (cycling, running or
  generic). Every object under a record is read for ``maxHeartRateUsed``,
  ``maxHeartRate`` or ``maxHR``, with the legacy category terms and the legacy
  80 to 260 bpm window. Values above the canonical 250 bpm bound are reported
  OUT_OF_RANGE, so 251 to 260 bpm are not mapped.
* ``weight``, ``weigh_ins`` or ``weighIns`` (the first truthy one wins, as in the
  legacy ``or`` chain): WEIGHT in kilograms and BODY_FAT in percent. Nested records
  are searched with the legacy reader's depth, visit and list limits.

Time rule: most observations are dated by ``calendarDate``, the field the collector
guarantees on dated records. ``running_threshold`` has no date; the collector
requests it as the latest value on the sync day, so its observation day is the
athlete-zone date of ``retrieved_at``. Undated ``heart_rate_zones`` records use
the same sync day.

Weight and body fat follow the legacy reader ``backend/performance/garmin_weight``
for record shapes. A record's day is the first present of calendarDate,
summaryDate, date, timestampGMT or timestamp. Epoch milliseconds are read as a UTC
date, as the legacy reader does. A record with no date of its own inherits its
nearest dated ancestor's day. A present but unreadable ISO date is not inherited: a record under it with no
readable date of its own is reported as invalid, which differs from the legacy
reader that keeps the unreadable text as a day key. An epoch that cannot be
converted is inherited, as the legacy reader does. When the record carries a
timestamp
(timestampGMT, timestamp, measurementDate or date), ``observed_at`` holds it as an
aware datetime (UTC when naive), so consumers can choose the latest value per day.

Alias precedence: the first present, non-empty name in each field's tuple wins.
The tuples follow today's readers in ``backend/performance`` (``recovery_context``,
``planning_recovery``, ``garmin_weight``, ``garmin_metrics``).

Weight units: ``gram``/``grams``/``g`` are divided by 1000, ``kilogram``/
``kilograms``/``kg`` are kept, and any unit containing ``lb`` or ``pound`` is
converted from pounds. A record with no declared unit uses the legacy magnitude
guess: values above 300 are grams. A declared unit is never reinterpreted, and an
unknown or non-text unit is reported as UNKNOWN_VALUE. Weight must lie in 30 to
300 kg and body fat in 2 to 70 percent, the legacy bounds. Body fat units follow
the legacy reader: ``fraction`` and ``ratio`` are multiplied by 100, ``percent``,
``%`` or no unit are used as they are, and any other unit is UNKNOWN_VALUE.
Kilograms and percent are rounded to two decimals, as the legacy reader rounds.

Ignored without an issue: sections with no canonical kind in this wave (``activities``,
``gear``, ``daily_stats``, ``training_status``, ``race_predictions``,
``endurance_score``, ``running_tolerance``) and unknown keys. Body battery (charged and
drained only, no level) and the device-keyed ``daily_training_status`` and
``training_load_balance`` each yield one UNSUPPORTED issue per section.

Source kinds: sensor values (sleep duration, HRV, resting heart rate, scale weight
and body fat) are DEVICE_MEASURED. Garmin's calculations (sleep score, readiness,
VO2max, thresholds, FTP) are PROVIDER_REPORTED. The source record id is
``<section>:<calendarDate>``, with ``:<object>`` appended for nested objects, for
example ``max_metrics:2026-10-10:cycling``. Weight records use ``weight:<day>:<record
index>`` and body-fat records use ``body_fat:<day>:<record index>``, because one day can
hold several weigh-ins and a weigh-in and its body-fat value must not share an id.
Heart-rate zone maxima use ``heart_rate_zones:<day>:<record index>:<object index>``,
with the record index omitted for a single object.

Plausibility: a value must lie inside ``METRIC_BOUNDS``. Zero is rejected for every
metric except the sleep score, where Garmin's 0 is a measured score kept as
reported, as the legacy reader keeps it. Other zero measurements, such as a zero
sleep duration, are still rejected; the parity tests name the remaining
differences from the legacy readers.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import Final

from backend.canonical.local_time import local_date
from backend.canonical.mapping import (
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_comma_decimal_number,
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
from backend.providers.garmin_fields import (
    GARMIN_BODY_FAT_ALIASES,
    GARMIN_FTP_ALIASES,
    GARMIN_HRV_LAST_NIGHT_ALIASES,
    GARMIN_READINESS_ALIASES,
    GARMIN_RESTING_HR_ALIASES,
    GARMIN_SLEEP_DURATION_ALIASES,
    GARMIN_SLEEP_SCORE_ALIASES,
    GARMIN_VO2MAX_ALIASES,
    GARMIN_WEIGHT_UNIT_ALIASES,
)
from backend.providers.garmin_weight_walk import (
    BODY_FAT_SKIP_KEYS,
    WALK_DATE_KEYS,
    WEIGHT_SKIP_KEYS,
    alnum_key,
    walk_records,
    weight_payload,
)

MAPPER_VERSION: Final = 3
GARMIN_LABEL: Final = "Garmin Connect"

_DATE_FIELD: Final = "calendarDate"
_DAY_TEXT_LENGTH: Final = 10  # "YYYY-MM-DD"
_DEVICE: Final = SourceKind.DEVICE_MEASURED
_PROVIDER: Final = SourceKind.PROVIDER_REPORTED
_GRAMS_PER_KILOGRAM: Final = 1000.0
_GRAM_GUESS_THRESHOLD: Final = 300.0
_KG_PER_POUND: Final = 0.45359237
_GRAM_UNITS: Final = frozenset({"gram", "grams", "g"})
_KILOGRAM_UNITS: Final = frozenset({"kilogram", "kilograms", "kg"})
_WEIGHT: Final = "weight"
_BODY_FAT_RECORD: Final = "body_fat"
_WEIGHT_KEYS: Final = ("weightKg", "weight_kg", "weight")
_WEIGHT_UNIT_KEYS: Final = GARMIN_WEIGHT_UNIT_ALIASES
_WEIGHT_VALUE_KEYS: Final = ("weightKg", "weight_kg", "weight", "value")
_WEIGHT_MIN_KG: Final = 30.0
_WEIGHT_MAX_KG: Final = 300.0
_BODY_FAT_KEYS: Final = GARMIN_BODY_FAT_ALIASES
_BODY_FAT_UNIT_KEYS: Final = ("bodyFatUnit", "bodyFatUnitKey")
_BODY_FAT_INNER_UNIT_KEYS: Final = ("unitKey", "unit", "bodyFatUnit")
_BODY_FAT_VALUE_KEYS: Final = ("value", "val", "amount")
_BODY_FAT_MIN_PERCENT: Final = 2.0
_BODY_FAT_MAX_PERCENT: Final = 70.0
_WALK_TIMESTAMP_KEYS: Final = ("timestampGMT", "timestamp", "measurementDate", "date")
_EPOCH_MS_THRESHOLD: Final = 100_000_000_000
_TEXT_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_TEXT_DATETIME: Final = re.compile(r"\d{4}-\d{2}-\d{2}[T ].+")
_RUNNING_THRESHOLD: Final = "running_threshold"
_HEART_RATE_ZONES: Final = "heart_rate_zones"
_MAX_HR_KEYS: Final = ("maxHeartRateUsed", "maxHeartRate", "maxHR")
_MAX_HR_FLOOR: Final = 80.0
_HEART_RATE_SPORT_KEYS: Final = ("sport", "sportType", "activityType")
_HEART_RATE_LIST_LIMIT: Final = 100
_LATEST_WEIGHT_KEYS: Final = frozenset({"latestWeight"})
_UNSUPPORTED_SECTIONS: Final = frozenset(
    {"body_battery", "daily_training_status", "training_load_balance"}
)


@dataclass(frozen=True, slots=True)
class _InvalidDay:
    """A date field that was present but unreadable.

    Nested weight records inherit it, as the legacy reader inherits its garbage
    day key, so they are not emitted under an outer record's day.
    """


_INVALID_DAY: Final = _InvalidDay()
type _Day = date | _InvalidDay | None


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
    observed_at: datetime | None = None


_VO2MAX_NAMES: Final = GARMIN_VO2MAX_ALIASES

_GROUPED_SECTIONS: Final[Mapping[str, tuple[_Group, ...]]] = {
    "sleep": (
        _Group(
            None,
            (
                _Field(
                    GARMIN_SLEEP_DURATION_ALIASES,
                    MetricKind.SLEEP_DURATION,
                    _DEVICE,
                ),
                _Field(
                    GARMIN_SLEEP_SCORE_ALIASES,
                    MetricKind.SLEEP_SCORE,
                    _PROVIDER,
                ),
            ),
        ),
    ),
    "hrv": (
        _Group(
            None,
            (_Field(GARMIN_HRV_LAST_NIGHT_ALIASES, MetricKind.HRV_RMSSD, _DEVICE),),
        ),
    ),
    "resting_hr": (
        _Group(
            None,
            (
                _Field(
                    GARMIN_RESTING_HR_ALIASES,
                    MetricKind.RESTING_HR,
                    _DEVICE,
                ),
            ),
        ),
    ),
    "readiness": (
        _Group(
            None, (_Field(GARMIN_READINESS_ALIASES, MetricKind.READINESS, _PROVIDER),)
        ),
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
                    GARMIN_FTP_ALIASES,
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
                    GARMIN_FTP_ALIASES,
                    MetricKind.FTP,
                    _PROVIDER,
                    Sport.RIDE,
                ),
            ),
        ),
    ),
}

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
    _HEART_RATE_ZONES,
    _WEIGHT,
    "body_battery",
    "daily_training_status",
    "training_load_balance",
)
# Public name for the canonical plan, which keeps one raw record per section.
GARMIN_HEALTH_SECTION_NAMES: Final = _SECTION_ORDER


def _named_value(
    record: Mapping[str, object], names: tuple[str, ...]
) -> tuple[str, object] | None:
    """Return the first present, non-empty alias with its name, or None."""
    for name in names:
        value = record.get(name)
        if value is not None and value != "":
            return name, value
    return None


def _first_value(record: Mapping[str, object], names: tuple[str, ...]) -> object | None:
    """Return the first present, non-empty alias, or None when none is present."""
    named = _named_value(record, names)
    return None if named is None else named[1]


def _parse_day(text: object) -> date | None:
    """Parse a strict ``YYYY-MM-DD`` calendar date, or return None."""
    if not isinstance(text, str) or len(text) != _DAY_TEXT_LENGTH:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _entry(
    name: str,
    ref: str,
    day: date,
    suffix: str | None = None,
    observed_at: datetime | None = None,
    *,
    index: int | None = None,
) -> _Entry:
    base = f"{name}:{day.isoformat()}"
    if index is not None:
        base = f"{base}:{index}"
    record_id = base if suffix is None else f"{base}:{suffix}"
    return _Entry(ref, day, record_id, observed_at)


def _iso_day(text: str) -> date | None:
    """Calendar date of a date or datetime string, read as the legacy reader does."""
    value = text.replace("Z", "+00:00").strip()
    try:
        if _TEXT_DATE.fullmatch(value):
            return date.fromisoformat(value)
        if _TEXT_DATETIME.fullmatch(value):
            return datetime.fromisoformat(value).date()
    except ValueError:
        return None
    return None


def _epoch_day(milliseconds: float) -> date | None:
    try:
        return datetime.fromtimestamp(float(milliseconds) / 1000, UTC).date()
    except OverflowError, OSError, ValueError:
        return None


def _raw_day(raw: object) -> _Day:
    """Day of one date field. None means the field gives no day and is inherited."""
    if isinstance(raw, int | float) and raw > _EPOCH_MS_THRESHOLD:
        return _epoch_day(raw)
    day = _iso_day(str(raw))
    return _INVALID_DAY if day is None else day


def _own_day(record: Mapping[str, object]) -> _Day:
    """Day of a record's own date field, or None when it gives none to inherit."""
    raw = _first_value(record, WALK_DATE_KEYS)
    return None if raw is None else _raw_day(raw)


def _observed_at(record: Mapping[str, object]) -> datetime | None:
    """Aware timestamp of a weight record, or None when it has none."""
    raw = _first_value(record, _WALK_TIMESTAMP_KEYS)
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        scale = 1000 if raw > _EPOCH_MS_THRESHOLD else 1
        try:
            return datetime.fromtimestamp(float(raw) / scale, UTC)
        except OverflowError, OSError, ValueError:
            return None
    if isinstance(raw, str) and len(raw.strip()) > _DAY_TEXT_LENGTH:
        try:
            parsed = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _decimal(value: object) -> float | None:
    """Finite number from a number or text, with a comma accepted as decimal."""
    return coerce_comma_decimal_number(value)


def _weight_number(value: object) -> float | None:
    """Finite weight number without losing precision during unit conversion."""
    return _decimal(value)


def _is_blank_unit(unit: object) -> bool:
    """True when no unit is declared: empty, falsy, or whitespace-only text."""
    return not unit or (isinstance(unit, str) and not unit.strip())


def _weight_kg(number: float, unit: object) -> float | None:
    """Kilograms for a weight in its declared unit, or None when the unit is unknown."""
    if _is_blank_unit(unit):
        return (
            number / _GRAMS_PER_KILOGRAM if number > _GRAM_GUESS_THRESHOLD else number
        )
    if not isinstance(unit, str):
        return None
    key = alnum_key(unit)
    if "lb" in key or "pound" in key:
        return number * _KG_PER_POUND
    if key in _GRAM_UNITS:
        return number / _GRAMS_PER_KILOGRAM
    if key in _KILOGRAM_UNITS:
        return number
    return None


def _body_fat_percent(number: float, unit: object) -> float | None:
    """Percent for a body-fat value in its declared unit, or None when unknown."""
    if _is_blank_unit(unit):
        return number
    if not isinstance(unit, str):
        return None
    key = alnum_key(unit)
    if "fraction" in key or "ratio" in key:
        return number * 100
    if "percent" in key or "%" in unit:
        return number
    return None


def _measure(
    record: Mapping[str, object],
    keys: tuple[str, ...],
    unit_keys: tuple[str, ...],
    inner_unit_keys: tuple[str, ...],
    inner_value_keys: tuple[str, ...],
) -> tuple[str, object, object] | None:
    """Return (field, raw value, unit) for one measure, unwrapping a nested object.

    The unit of a nested object takes precedence over the record's own unit, as in
    the legacy ``or`` chain. A nested object without a value yields None.
    """
    named = _named_value(record, keys)
    if named is None:
        return None
    field, raw = named
    unit = _first_value(record, unit_keys)
    if isinstance(raw, Mapping):
        inner = _named_value(raw, inner_value_keys)
        if inner is None:
            return None
        unit = _first_value(raw, inner_unit_keys) or unit
        field = f"{field}.{inner[0]}"
        raw = inner[1]
    return field, raw, unit


def _within_bounds(kind: MetricKind, number: float) -> bool:
    lower, upper = METRIC_BOUNDS[kind]
    if kind is MetricKind.SLEEP_SCORE:
        # Garmin's 0 is a measured score; the legacy reader keeps it.
        return lower <= number <= upper
    return 0 < number and lower <= number <= upper


def _heart_rate_nodes(value: object) -> Iterator[Mapping[str, object]]:
    """Mappings under one record, the record first, in the legacy reader's order.

    Lists are read up to the legacy item limit. The walk keeps an explicit stack, so
    a deeply nested payload cannot exhaust the recursion limit.
    """
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, Mapping):
            yield item
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item[:_HEART_RATE_LIST_LIMIT]))


def _heart_rate_sport(value: object) -> Sport | None:
    """Sport of a heart-rate zone object, by the legacy reader's category terms."""
    key = alnum_key(value)
    if any(term in key for term in ("cycling", "cycl", "bike", "ride")):
        return Sport.RIDE
    if any(term in key for term in ("running", "run")):
        return Sport.RUN
    return None


def _top_level_items(payload: object) -> object:
    """A list payload within the legacy item limit; any other payload as it is."""
    return payload[:_HEART_RATE_LIST_LIMIT] if isinstance(payload, list) else payload


class _WeightWalk:
    """Searches a weight payload for weight or body-fat records, as the legacy reader.

    Each record the shared walk yields is a candidate. Traversal order, the depth,
    visit and list limits, and the skipped min, max and delta keys come from
    ``garmin_weight_walk``, the same walk the legacy reader uses. A weight record
    takes the index of the list item it sits under, when there is one, which keeps
    the legacy reader's order for latest-per-day selection.
    """

    def __init__(self, mapping: _HealthMapping, *, body_fat: bool) -> None:
        self._mapping = mapping
        self._body_fat = body_fat
        self._skip = BODY_FAT_SKIP_KEYS if body_fat else WEIGHT_SKIP_KEYS

    def run(self, payload: object) -> None:
        for walked in walk_records(
            payload,
            skip_keys=self._skip,
            resolve_day=_own_day,
            marker_keys=_LATEST_WEIGHT_KEYS,
        ):
            if self._body_fat:
                self._body_fat_candidate(walked.record, walked.day, walked.ordinal)
            else:
                index = (
                    walked.ordinal if walked.list_index is None else walked.list_index
                )
                self._weight_candidate(walked.record, walked.day, index, walked.marked)

    def _weight_candidate(
        self,
        record: Mapping[str, object],
        day: _Day,
        index: int,
        default_gram: bool,
    ) -> None:
        measure = _measure(
            record,
            _WEIGHT_KEYS,
            _WEIGHT_UNIT_KEYS,
            _WEIGHT_UNIT_KEYS,
            _WEIGHT_VALUE_KEYS,
        )
        ref = f"{_WEIGHT}[{index}]"
        if measure is None:
            # A weight object with no value still reports a bad date on its record.
            if _named_value(record, _WEIGHT_KEYS) is not None:
                self._record_day(day, ref, report=True)
            return
        field, raw, unit = measure
        if not unit and (default_gram or "." in field):
            unit = "gram"
        record_day = self._record_day(day, ref, report=True)
        if record_day is None:
            return
        number = _weight_number(raw)
        if number is None:
            self._mapping.issue(ref, field, IssueReason.INVALID_NUMBER)
            return
        kilograms = _weight_kg(number, unit)
        if kilograms is None:
            self._mapping.issue(ref, field, IssueReason.UNKNOWN_VALUE)
            return
        if not _WEIGHT_MIN_KG <= kilograms <= _WEIGHT_MAX_KG:
            self._mapping.issue(ref, field, IssueReason.OUT_OF_RANGE)
            return
        self._emit(
            record,
            record_day,
            index,
            ref,
            field,
            MetricKind.WEIGHT,
            kilograms,
        )

    def _body_fat_candidate(
        self, record: Mapping[str, object], day: _Day, index: int
    ) -> None:
        measure = _measure(
            record,
            _BODY_FAT_KEYS,
            _BODY_FAT_UNIT_KEYS,
            _BODY_FAT_INNER_UNIT_KEYS,
            _BODY_FAT_VALUE_KEYS,
        )
        if measure is None:
            return
        ref = f"{_WEIGHT}[{index}]"
        field, raw, unit = measure
        # A record that also carries a weight reports its date problems once,
        # through the weight walk.
        report = _named_value(record, _WEIGHT_KEYS) is None
        record_day = self._record_day(day, ref, report=report)
        if record_day is None:
            return
        number = _decimal(raw)
        if number is None:
            self._mapping.issue(ref, field, IssueReason.INVALID_NUMBER)
            return
        percent = _body_fat_percent(number, unit)
        if percent is None:
            self._mapping.issue(ref, field, IssueReason.UNKNOWN_VALUE)
            return
        if not _BODY_FAT_MIN_PERCENT <= percent <= _BODY_FAT_MAX_PERCENT:
            self._mapping.issue(ref, field, IssueReason.OUT_OF_RANGE)
            return
        self._emit(
            record,
            record_day,
            index,
            ref,
            field,
            MetricKind.BODY_FAT,
            round(percent, 2),
        )

    def _record_day(self, day: _Day, ref: str, *, report: bool) -> date | None:
        if isinstance(day, date):
            return day
        if report:
            reason = IssueReason.MISSING if day is None else IssueReason.INVALID_TYPE
            self._mapping.issue(ref, _DATE_FIELD, reason)
        return None

    def _emit(
        self,
        record: Mapping[str, object],
        day: date,
        index: int,
        ref: str,
        field: str,
        kind: MetricKind,
        number: float,
    ) -> None:
        prefix = _BODY_FAT_RECORD if kind is MetricKind.BODY_FAT else _WEIGHT
        entry = _entry(prefix, ref, day, str(index), observed_at=_observed_at(record))
        self._mapping.emit(entry, kind, number, field, _DEVICE)


class _HealthMapping:
    """Collects the observations and issues of one ``map_garmin_health`` call."""

    def __init__(self, zone: tzinfo, retrieved_at: datetime) -> None:
        self._retrieved_at = retrieved_at
        self._sync_day = local_date(retrieved_at, zone)
        self.observations: list[Observation] = []
        self.issues: list[MappingIssue] = []

    def map_sections(self, sections: object) -> None:
        if not isinstance(sections, Mapping):
            self.issue(None, "sections", IssueReason.INVALID_TYPE)
            return
        for name in _SECTION_ORDER:
            if name == _WEIGHT:
                self._map_weight(sections)
            elif name in sections:
                self._map_section(name, sections[name])

    def _map_section(self, name: str, payload: object) -> None:
        if payload is None:
            return
        if name in _UNSUPPORTED_SECTIONS:
            self.issue(None, name, IssueReason.UNSUPPORTED)
        elif name == _RUNNING_THRESHOLD:
            self._map_running_threshold(payload)
        elif name == _HEART_RATE_ZONES:
            self._map_heart_rate_zones(payload)
        else:
            self._map_grouped(name, payload, _GROUPED_SECTIONS[name])

    def _map_grouped(
        self, name: str, payload: object, groups: tuple[_Group, ...]
    ) -> None:
        for ref, record, index in self._records(name, payload):
            day = self._record_day(record, ref, fallback=None)
            if day is not None:
                for group in groups:
                    self._map_group(name, record, group, ref, day, index=index)

    def _map_weight(self, sections: Mapping[str, object]) -> None:
        payload = self._weight_records(weight_payload(sections))
        _WeightWalk(self, body_fat=False).run(payload)
        _WeightWalk(self, body_fat=True).run(payload)

    def _weight_records(self, payload: object) -> object:
        """Drop scalar weight entries with an issue; the walk reads the rest."""
        if isinstance(payload, list):
            kept: list[object] = []
            for index, item in enumerate(payload):
                if isinstance(item, Mapping | list):
                    kept.append(item)
                elif item:
                    self.issue(f"{_WEIGHT}[{index}]", _WEIGHT, IssueReason.INVALID_TYPE)
            return kept
        if payload and not isinstance(payload, Mapping):
            self.issue(None, _WEIGHT, IssueReason.INVALID_TYPE)
            return None
        return payload

    def _map_running_threshold(self, payload: object) -> None:
        for ref, record, index in self._records(_RUNNING_THRESHOLD, payload):
            day = self._record_day(record, ref, fallback=self._sync_day)
            if day is not None:
                self._map_group(
                    _RUNNING_THRESHOLD, record, _THRESHOLD_GROUP, ref, day, index=index
                )
                self._report_power(record, ref)

    def _report_power(self, record: Mapping[str, object], ref: str) -> None:
        power = record.get("power")
        if power is None:
            return
        if not isinstance(power, Mapping):
            self.issue(ref, "power", IssueReason.INVALID_TYPE)
        elif _first_value(power, ("functionalThresholdPower",)) is not None:
            self.issue(ref, "power.functionalThresholdPower", IssueReason.UNSUPPORTED)

    def _map_heart_rate_zones(self, payload: object) -> None:
        for ref, record, index in self._records(
            _HEART_RATE_ZONES, _top_level_items(payload)
        ):
            day = self._record_day(record, ref, fallback=self._sync_day)
            if day is None:
                continue
            for ordinal, node in enumerate(_heart_rate_nodes(record)):
                self._map_max_hr(node, ref, day, index=index, ordinal=ordinal)

    def _map_max_hr(
        self,
        node: Mapping[str, object],
        ref: str,
        day: date,
        *,
        index: int | None,
        ordinal: int,
    ) -> None:
        number = self._number(node, _MAX_HR_KEYS, ref)
        if number is None:
            return
        value = round(number, 2)
        if value < _MAX_HR_FLOOR:
            self.issue(ref, _MAX_HR_KEYS[0], IssueReason.OUT_OF_RANGE)
            return
        entry = _entry(_HEART_RATE_ZONES, ref, day, str(ordinal), index=index)
        sport = _heart_rate_sport(_first_value(node, _HEART_RATE_SPORT_KEYS))
        self.emit(
            entry,
            MetricKind.MAX_HR,
            value,
            _MAX_HR_KEYS[0],
            _PROVIDER,
            sport,
        )

    def _map_group(
        self,
        name: str,
        record: Mapping[str, object],
        group: _Group,
        ref: str,
        day: date,
        *,
        index: int | None = None,
    ) -> None:
        source: object = record if group.key is None else record.get(group.key)
        if source is None:
            return
        if not isinstance(source, Mapping):
            self.issue(ref, group.key or name, IssueReason.INVALID_TYPE)
            return
        entry = _entry(name, ref, day, group.key, index=index)
        for field in group.fields:
            number = self._group_number(name, group, record, source, field, ref)
            if number is not None:
                self.emit(
                    entry,
                    field.kind,
                    number,
                    field.names[0],
                    field.source_kind,
                    field.sport,
                )

    def _group_number(
        self,
        name: str,
        group: _Group,
        record: Mapping[str, object],
        source: Mapping[str, object],
        field: _Field,
        ref: str,
    ) -> float | None:
        number = self._number(source, field.names, ref)
        if number is not None or group.key is not None or name != "sleep":
            return number
        nested = record.get("dailySleepDTO")
        if not isinstance(nested, Mapping):
            return None
        number = self._number(nested, field.names, ref)
        if number is not None or field.kind != MetricKind.SLEEP_SCORE:
            return number
        scores = nested.get("sleepScores")
        overall = scores.get("overall") if isinstance(scores, Mapping) else None
        return (
            self._number(overall, ("value",), ref)
            if isinstance(overall, Mapping)
            else None
        )

    def _records(
        self, name: str, payload: object
    ) -> list[tuple[str, Mapping[str, object], int | None]]:
        items: object = [payload] if isinstance(payload, Mapping) else payload
        if not isinstance(items, list):
            self.issue(None, name, IssueReason.INVALID_TYPE)
            return []
        rows: list[tuple[str, Mapping[str, object], int | None]] = []
        for index, item in enumerate(items):
            ref = f"{name}[{index}]"
            if isinstance(item, Mapping):
                rows.append((ref, item, index if isinstance(payload, list) else None))
            else:
                self.issue(ref, name, IssueReason.INVALID_TYPE)
        return rows

    def _record_day(
        self, record: Mapping[str, object], ref: str, *, fallback: date | None
    ) -> date | None:
        raw = _first_value(record, (_DATE_FIELD,))
        nested_sleep = record.get("dailySleepDTO")
        if raw is None and isinstance(nested_sleep, Mapping):
            raw = _first_value(nested_sleep, (_DATE_FIELD,))
        if raw is None:
            if fallback is None:
                self.issue(ref, _DATE_FIELD, IssueReason.MISSING)
            return fallback
        day = _parse_day(raw)
        if day is None:
            self.issue(ref, _DATE_FIELD, IssueReason.INVALID_TYPE)
        return day

    def _number(
        self, record: Mapping[str, object], names: tuple[str, ...], ref: str
    ) -> float | None:
        raw = _first_value(record, names)
        if raw is None:
            return None
        number = coerce_number(raw)
        if number is None:
            self.issue(ref, names[0], IssueReason.INVALID_NUMBER)
        return number

    def emit(
        self,
        entry: _Entry,
        kind: MetricKind,
        number: float,
        field: str,
        source_kind: SourceKind,
        sport: Sport | None = None,
    ) -> None:
        if not _within_bounds(kind, number):
            self.issue(entry.ref, field, IssueReason.OUT_OF_RANGE)
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
                observed_at=entry.observed_at,
                provenance=provenance,
                sport=sport,
            )
        )

    def issue(self, record_ref: str | None, field: str, reason: IssueReason) -> None:
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
