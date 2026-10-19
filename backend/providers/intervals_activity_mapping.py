"""Map Intervals.icu activity rows to canonical activity records.

The mapper is pure: it performs no I/O, logs nothing and never raises on
malformed provider input. A row without a usable id or start time is dropped
with an issue. Any other malformed field becomes None with an issue, so one bad
field never drops a record. Issues name the record id and the field only; they
never carry the provider value, and unknown fields are never copied.

Alias precedence. The first usable value wins. A malformed earlier alias still
produces an issue, and the next alias is tried:

* start: ``start_date`` before ``start_date_local``. ``start_date`` is used only
  when it carries its own offset, because it then names an exact instant. A
  naive ``start_date`` is reported and skipped, so it is never read as athlete
  wall time. ``start_date_local`` is athlete wall time, localised by
  ``parse_provider_datetime``. Other readers prefer ``start_date_local``; this
  mapper prefers the exact instant when one is sent.
* duration: ``moving_time`` before ``elapsed_time``, as activity_validation does.
  A zero duration is out of range (the legacy minimum is one second), so
  ``elapsed_time`` is then consulted. ``elapsed_time`` is also kept on its own as
  ``elapsed_duration_s``, so session bundling can compare it with a Garmin
  elapsed time when Garmin sends no moving time. A malformed ``elapsed_time`` is
  reported once.
* average heart rate: ``average_heartrate`` before ``averageHR``.
* maximum heart rate: ``max_heartrate`` before ``maxHR``, as activity_validation
  reads it.
* average power: ``average_watts`` before ``average_power``, as
  activity_validation does. ``icu_average_watts`` is not read because no reader
  or fixture carries it.
* load: ``icu_training_load`` only. Its model is INTERVALS_TRAINING_LOAD, and
  UNKNOWN when there is no load.
* distance: ``distance`` in metres.
* maximum speed and power: ``max_speed`` (m/s) -> ``max_speed_mps``, and
  ``max_watts`` -> ``max_power_w``. No other extreme is mapped.
* recording device type: whole-word terms in ``device_name`` (see
  ``_DEVICE_TYPE_TERMS``). Bike computer terms win over watch terms. Absent or
  unmatched text is None. A non-text ``device_name`` is reported once, as the
  other provenance text is.

Sport and environment come from ``INTERVALS_ACTIVITY_TYPES`` for known Intervals
type names. Any other type name falls back to the legacy text rules applied to
the space-joined identity text (type, sport, sport_type, activityType,
activityName, name), the fields the legacy activity_kind reads. Text environment
terms fill in only an UNKNOWN environment from the type table. OUTDOOR is set
only where the type name itself denotes an outdoor setting. No reader or fixture
carries a trainer flag, so none is read.

Recording origin comes from the source, device_name and external_id text. A
source of exactly "manual", ignoring case and surrounding whitespace, is MANUAL
before any brand term is checked. Other brand terms are checked in the order
wahoo, garmin, zwift, strava, manual, upload. The recording device therefore
wins over a sync source such as Strava. The word "file" counts only as a whole
word, so "profile" does not match.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, tzinfo
from typing import Final

from backend.canonical.local_time import parse_provider_datetime
from backend.canonical.mapping import (
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_number,
)
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.sports import classify_environment_text, classify_sport_text
from backend.canonical.validation import (
    HEART_RATE_BOUNDS,
    MAX_ACTIVITY_DISTANCE_M,
    MAX_ACTIVITY_DURATION_S,
    MAX_ACTIVITY_LOAD,
    MAX_ACTIVITY_POWER_W,
    MAX_ACTIVITY_SPEED_MPS,
)
from backend.canonical.vocabulary import (
    DeviceType,
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)

# Version 5: maps the maximum speed, maximum power and recording device type.
# Version 4: a source of exactly "manual" is recorded as MANUAL origin.
# Version 3: maps the activity's maximum heart rate.
MAPPER_VERSION: Final = 5
INTERVALS_LABEL: Final = "Intervals.icu"
MAX_ACTIVITY_ID_LENGTH: Final = 200
MAX_NAME_LENGTH: Final = 200

_START_KEYS: Final = ("start_date", "start_date_local")
_MOVING_TIME_KEYS: Final = ("moving_time",)
_ELAPSED_TIME_KEYS: Final = ("elapsed_time",)
_DISTANCE_KEYS: Final = ("distance",)
_LOAD_KEYS: Final = ("icu_training_load",)
_AVERAGE_HR_KEYS: Final = ("average_heartrate", "averageHR")
_MAX_HR_KEYS: Final = ("max_heartrate", "maxHR")
_MAX_SPEED_KEYS: Final = ("max_speed",)
_MAX_POWER_KEYS: Final = ("max_watts",)
_AVERAGE_POWER_KEYS: Final = ("average_watts", "average_power")
_IDENTITY_KEYS: Final = (
    "type",
    "sport",
    "sport_type",
    "activityType",
    "activityName",
    "name",
)
_PROVENANCE_KEYS: Final = ("source", "device_name", "external_id")
_WORD_BREAK: Final = re.compile(r"[^a-z0-9]+")
# Same minimum as activity_validation: a zero duration is not a usable value.
_MIN_DURATION_S: Final = 1.0
# 800 bits render to at most 241 decimal digits, far below Python's int-to-str
# digit limit, so wider integers are rejected before str() is called.
_MAX_ID_INT_BITS: Final = 4 * MAX_ACTIVITY_ID_LENGTH
# Offset of the time part in "YYYY-MM-DDTHH:MM..." text.
_TIME_PART_START: Final = 11


def _entries(
    sport: Sport, environment: Environment, names: tuple[str, ...]
) -> dict[str, tuple[Sport, Environment]]:
    return {name: (sport, environment) for name in names}


_UNKNOWN: Final = Environment.UNKNOWN
_VIRTUAL: Final = Environment.VIRTUAL
_OUTDOOR: Final = Environment.OUTDOOR

# Exact Intervals.icu type names whose sport is definite. "Workout" and "Other"
# are generic, so they are left out and classified from their text instead.
# OUTDOOR is used only where the name denotes an outdoor setting (trail, open
# water, hiking, backcountry). Indoor is never named by a type, so it comes
# from text only.
INTERVALS_ACTIVITY_TYPES: Final[Mapping[str, tuple[Sport, Environment]]] = {
    **_entries(
        Sport.RIDE,
        _UNKNOWN,
        (
            "Ride",
            "EBikeRide",
            "EMountainBikeRide",
            "GravelRide",
            "Handcycle",
            "MountainBikeRide",
            "Velomobile",
        ),
    ),
    **_entries(Sport.RIDE, _VIRTUAL, ("VirtualRide",)),
    **_entries(Sport.RUN, _UNKNOWN, ("Run",)),
    **_entries(Sport.RUN, _VIRTUAL, ("VirtualRun",)),
    **_entries(Sport.RUN, _OUTDOOR, ("TrailRun",)),
    **_entries(Sport.SWIM, _UNKNOWN, ("Swim",)),
    **_entries(Sport.SWIM, _OUTDOOR, ("OpenWaterSwim",)),
    **_entries(Sport.WALK, _UNKNOWN, ("Walk",)),
    **_entries(Sport.HIKE, _OUTDOOR, ("Hike",)),
    **_entries(Sport.STRENGTH, _UNKNOWN, ("WeightTraining",)),
    **_entries(Sport.ROW, _UNKNOWN, ("Rowing",)),
    **_entries(Sport.ROW, _VIRTUAL, ("VirtualRow",)),
    **_entries(Sport.NORDIC_SKI, _UNKNOWN, ("NordicSki", "RollerSki")),
    **_entries(Sport.ALPINE_SKI, _UNKNOWN, ("AlpineSki",)),
    **_entries(Sport.ALPINE_SKI, _OUTDOOR, ("BackcountrySki",)),
    **_entries(Sport.YOGA, _UNKNOWN, ("Yoga",)),
    **_entries(
        Sport.OTHER,
        _UNKNOWN,
        (
            "Badminton",
            "Canoeing",
            "Crossfit",
            "Elliptical",
            "Golf",
            "HighIntensityIntervalTraining",
            "IceSkate",
            "InlineSkate",
            "Kayaking",
            "Kitesurf",
            "Padel",
            "Pilates",
            "Pickleball",
            "Racquetball",
            "Rugby",
            "RockClimbing",
            "Sail",
            "Skateboard",
            "Snowboard",
            "Snowshoe",
            "Soccer",
            "Squash",
            "StairStepper",
            "StandUpPaddling",
            "Surfing",
            "TableTennis",
            "Tennis",
            "Transition",
            "WaterSport",
            "Wheelchair",
            "Windsurf",
        ),
    ),
}

_RECORDING_ORIGIN_TERMS: Final[tuple[tuple[tuple[str, ...], RecordingOrigin], ...]] = (
    (("wahoo", "elemnt"), RecordingOrigin.WAHOO),
    (("garmin",), RecordingOrigin.GARMIN),
    (("zwift",), RecordingOrigin.ZWIFT),
    (("strava",), RecordingOrigin.STRAVA),
    (("manual",), RecordingOrigin.MANUAL),
    (("upload",), RecordingOrigin.UPLOAD),
)
# Whole-word terms matched against the casefolded device_name. Bike computer terms
# are checked first, so a name that names both kinds is a bike computer. Terms are
# product lines, never bare brands: COROS, Polar and Suunto also sell bike
# computers or sensors, so a brand-only name stays unclassified.
_DEVICE_TYPE_TERMS: Final[tuple[tuple[tuple[str, ...], DeviceType], ...]] = (
    (
        (
            "edge",
            "elemnt",
            "bolt",
            "roam",
            "karoo",
            "dura",
            "v650",
            "m450",
            "m460",
            "bryton rider",
        ),
        DeviceType.BIKE_COMPUTER,
    ),
    (
        (
            "forerunner",
            "fenix",
            "fēnix",
            "epix",
            "venu",
            "enduro",
            "instinct",
            "vivoactive",
            "apple watch",
            "pace",
            "apex",
            "vertix",
            "vantage",
            "grit",
            "pacer",
            "ignite",
            "suunto 5",
            "suunto 9",
            "suunto race",
            "suunto vertical",
        ),
        DeviceType.WATCH,
    ),
)
_WORD: Final = re.compile(r"\w+")


class _ActivityRow:
    """Reads the known fields of one activity row and records an issue per fault."""

    def __init__(self, row: Mapping[str, object], issues: list[MappingIssue]) -> None:
        self._row = row
        self._issues = issues
        self.record_ref: str | None = None

    def _fail(self, field: str, reason: IssueReason) -> None:
        self._issues.append(MappingIssue(self.record_ref, field, reason))

    def _present(self, key: str) -> object:
        """Return the raw value, or None when the key is absent, null or blank."""
        value = self._row.get(key)
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def activity_id(self) -> str | None:
        value = self._present("id")
        if value is None:
            self._fail("id", IssueReason.MISSING)
            return None
        if isinstance(value, bool) or not isinstance(value, str | int):
            self._fail("id", IssueReason.INVALID_TYPE)
            return None
        if isinstance(value, int) and value.bit_length() > _MAX_ID_INT_BITS:
            self._fail("id", IssueReason.OUT_OF_RANGE)
            return None
        text = str(value).strip()
        if len(text) > MAX_ACTIVITY_ID_LENGTH:
            self._fail("id", IssueReason.OUT_OF_RANGE)
            return None
        self.record_ref = text
        return text

    def started_at(self, zone: tzinfo) -> datetime | None:
        seen = False
        for key in _START_KEYS:
            value = self._present(key)
            if value is None:
                continue
            seen = True
            parsed = parse_provider_datetime(value, zone)
            # A naive start_date would be localised to the athlete zone, which is
            # the wrong reading for a field that names an exact instant.
            if parsed is not None and (key == "start_date_local" or _has_offset(value)):
                return parsed
            # Text that is not an ISO datetime, any other type, or a naive
            # start_date is INVALID_TYPE.
            self._fail(key, IssueReason.INVALID_TYPE)
        if not seen:
            self._fail("start_date", IssueReason.MISSING)
        return None

    def number(self, keys: tuple[str, ...], lower: float, upper: float) -> float | None:
        for key in keys:
            value = self._present(key)
            if value is None:
                continue
            number = coerce_number(value)
            if number is None:
                self._fail(key, IssueReason.INVALID_NUMBER)
            elif lower <= number <= upper:
                return number
            else:
                self._fail(key, IssueReason.OUT_OF_RANGE)
        return None

    def text(self, key: str) -> str | None:
        value = self._present(key)
        if value is None:
            return None
        if not isinstance(value, str):
            self._fail(key, IssueReason.INVALID_TYPE)
            return None
        return value.strip()

    def name(self) -> str | None:
        value = self.text("name")
        return None if value is None else value[:MAX_NAME_LENGTH]


def _has_offset(value: object) -> bool:
    """Return True when ISO text carries its own offset (``Z``, ``+hh:mm``, ``-hh:mm``).

    Called only on text that ``parse_provider_datetime`` already accepted, so the
    time part starts at a fixed position. Any other value returns False.
    """
    text = value.strip() if isinstance(value, str) else ""
    time_part = text[_TIME_PART_START:]
    return time_part.endswith(("Z", "z")) or "+" in time_part or "-" in time_part


def _identity_text(row: Mapping[str, object]) -> str:
    """Space-join the classification fields, as the legacy activity_kind does.

    Only text values take part. Non-text values are not classification text.
    """
    values = (row.get(key) for key in _IDENTITY_KEYS)
    return " ".join(value for value in values if isinstance(value, str))


def _classify(type_name: str | None, identity: str) -> tuple[Sport, Environment]:
    entry = INTERVALS_ACTIVITY_TYPES.get(type_name or "")
    if entry is None:
        sport = classify_sport_text(identity)
        environment = Environment.UNKNOWN
    else:
        sport, environment = entry
    if environment is Environment.UNKNOWN:
        environment = classify_environment_text(identity)
    return sport, environment


def _recording_origin(source: str | None, provenance_text: str) -> RecordingOrigin:
    # _ActivityRow.text already strips the source value.
    if source is not None and source.casefold() == "manual":
        return RecordingOrigin.MANUAL
    folded = provenance_text.casefold()
    for terms, origin in _RECORDING_ORIGIN_TERMS:
        if any(term in folded for term in terms):
            return origin
    if "file" in _WORD_BREAK.split(folded):
        return RecordingOrigin.UPLOAD
    return RecordingOrigin.UNKNOWN


def _device_type(device_name: str | None) -> DeviceType | None:
    if device_name is None:
        return None
    # Padded words, so a term matches only as a whole word ("edge", not "hedgehog").
    words = f" {' '.join(_WORD.findall(device_name.casefold()))} "
    for terms, device_type in _DEVICE_TYPE_TERMS:
        if any(f" {term} " in words for term in terms):
            return device_type
    return None


def _map_row(
    row: object,
    *,
    zone: tzinfo,
    retrieved_at: datetime,
    issues: list[MappingIssue],
) -> ActivityRecord | None:
    if not isinstance(row, dict):
        issues.append(MappingIssue(None, "row", IssueReason.INVALID_TYPE))
        return None
    reader = _ActivityRow(row, issues)
    activity_id = reader.activity_id()
    started_at = reader.started_at(zone)
    if activity_id is None or started_at is None:
        return None
    sport, environment = _classify(reader.text("type"), _identity_text(row))
    provenance = {key: reader.text(key) for key in _PROVENANCE_KEYS}
    provenance_text = " ".join(
        value for value in provenance.values() if value is not None
    )
    load = reader.number(_LOAD_KEYS, 0.0, MAX_ACTIVITY_LOAD)
    moving_time = reader.number(
        _MOVING_TIME_KEYS, _MIN_DURATION_S, MAX_ACTIVITY_DURATION_S
    )
    elapsed_time = reader.number(
        _ELAPSED_TIME_KEYS, _MIN_DURATION_S, MAX_ACTIVITY_DURATION_S
    )
    return ActivityRecord(
        activity_id=activity_id,
        provenance=Provenance(
            provider=ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=activity_id,
            recorded_by=_recording_origin(provenance["source"], provenance_text),
            retrieved_at=retrieved_at,
            label=INTERVALS_LABEL,
        ),
        sport=sport,
        environment=environment,
        started_at=started_at,
        duration_s=moving_time if moving_time is not None else elapsed_time,
        distance_m=reader.number(_DISTANCE_KEYS, 0.0, MAX_ACTIVITY_DISTANCE_M),
        load=load,
        load_model=(
            LoadModel.INTERVALS_TRAINING_LOAD if load is not None else LoadModel.UNKNOWN
        ),
        avg_hr=reader.number(_AVERAGE_HR_KEYS, *HEART_RATE_BOUNDS),
        avg_power=reader.number(_AVERAGE_POWER_KEYS, 0.0, MAX_ACTIVITY_POWER_W),
        name=reader.name(),
        elapsed_duration_s=elapsed_time,
        max_hr=reader.number(_MAX_HR_KEYS, *HEART_RATE_BOUNDS),
        max_speed_mps=reader.number(_MAX_SPEED_KEYS, 0.0, MAX_ACTIVITY_SPEED_MPS),
        max_power_w=reader.number(_MAX_POWER_KEYS, 0.0, MAX_ACTIVITY_POWER_W),
        device_type=_device_type(provenance["device_name"]),
    )


def map_intervals_activities(
    rows: object, *, zone: tzinfo, retrieved_at: datetime
) -> MappingResult[ActivityRecord]:
    """Map Intervals.icu activity rows; never raises on malformed row data.

    ``zone`` localises naive ``start_date_local`` wall times. ``retrieved_at``
    must be timezone-aware, because it is the provenance timestamp and a naive
    value is a programming error.
    """
    if retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    if not isinstance(rows, list):
        issue = MappingIssue(None, "rows", IssueReason.INVALID_TYPE)
        return MappingResult(issues=(issue,))
    records: list[ActivityRecord] = []
    issues: list[MappingIssue] = []
    for row in rows:
        record = _map_row(row, zone=zone, retrieved_at=retrieved_at, issues=issues)
        if record is not None:
            records.append(record)
    return MappingResult(records=tuple(records), issues=tuple(issues))
