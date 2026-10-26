"""Read Garmin's training-load, tolerance and readiness-history sections.

Pure readers for the health mapper (``garmin_health_mapping``), which validates
and emits the values. Each value is a provider calculation, never rebuilt
locally. The fields are the ones today's readers show:

* ``daily_training_status``: ACUTE_LOAD, CHRONIC_LOAD and ACUTE_CHRONIC_RATIO of
  the primary (or unambiguous latest) device record.
* ``training_load_balance``: the nine LOAD_BALANCE kinds of that device record.
* ``training_status`` and ``weekly_training_status``: ACUTE_LOAD per dated row,
  from ``acuteTrainingLoad`` or ``dailyTrainingLoadAcute`` at any depth; a row
  with two different values is ambiguous and yields none. These and the daily
  status describe one quantity, so a day reported by two sections is one row.
* ``running_tolerance``: RUNNING_TOLERANCE for running from ``toleranceScore``.
* ``training_readiness_history``: READINESS from the readiness score aliases.
* ``endurance_score``: ENDURANCE_SCORE_GROUP_AVERAGE and _MAX of each dated
  ``groupMap`` entry.

A device-keyed section whose devices disagree yields no value; the health mapper
reports it as UNKNOWN_VALUE, so coverage shows the gap. History rows are dated by ``date``, ``calendarDate``, ``summaryDate`` or
``from``; a row whose readable dates disagree is skipped.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.canonical.mapping import coerce_number
from backend.canonical.vocabulary import MetricKind, Sport
from backend.providers.garmin_device_records import primary_device_record
from backend.providers.garmin_performance_fields import (
    METRIC_DATE_KEYS,
    PLANNING_READINESS_ALIASES,
)

DAILY_TRAINING_STATUS: Final = "daily_training_status"
TRAINING_LOAD_BALANCE: Final = "training_load_balance"
TRAINING_STATUS: Final = "training_status"
WEEKLY_TRAINING_STATUS: Final = "weekly_training_status"
RUNNING_TOLERANCE: Final = "running_tolerance"
TRAINING_READINESS_HISTORY: Final = "training_readiness_history"
TRAINING_SECTIONS: Final = (
    DAILY_TRAINING_STATUS,
    TRAINING_LOAD_BALANCE,
    TRAINING_STATUS,
    WEEKLY_TRAINING_STATUS,
    RUNNING_TOLERANCE,
    TRAINING_READINESS_HISTORY,
)

_ACUTE_DTO: Final = "acuteTrainingLoadDTO"
_DAILY_FIELDS: Final = (
    ("dailyTrainingLoadAcute", MetricKind.ACUTE_LOAD),
    ("dailyTrainingLoadChronic", MetricKind.CHRONIC_LOAD),
    ("dailyAcuteChronicWorkloadRatio", MetricKind.ACUTE_CHRONIC_RATIO),
)
_BALANCE_FIELDS: Final = (
    ("monthlyLoadAerobicLow", MetricKind.LOAD_BALANCE_AEROBIC_LOW),
    ("monthlyLoadAerobicLowTargetMin", MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MIN),
    ("monthlyLoadAerobicLowTargetMax", MetricKind.LOAD_BALANCE_AEROBIC_LOW_TARGET_MAX),
    ("monthlyLoadAerobicHigh", MetricKind.LOAD_BALANCE_AEROBIC_HIGH),
    (
        "monthlyLoadAerobicHighTargetMin",
        MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MIN,
    ),
    (
        "monthlyLoadAerobicHighTargetMax",
        MetricKind.LOAD_BALANCE_AEROBIC_HIGH_TARGET_MAX,
    ),
    ("monthlyLoadAnaerobic", MetricKind.LOAD_BALANCE_ANAEROBIC),
    ("monthlyLoadAnaerobicTargetMin", MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MIN),
    ("monthlyLoadAnaerobicTargetMax", MetricKind.LOAD_BALANCE_ANAEROBIC_TARGET_MAX),
)
_DAILY_COMPARABLE: Final = (
    "calendarDate",
    *(f"{_ACUTE_DTO}.{field}" for field, _ in _DAILY_FIELDS),
)
_BALANCE_COMPARABLE: Final = ("calendarDate", *(field for field, _ in _BALANCE_FIELDS))
_ACUTE_FIELDS: Final = ("acuteTrainingLoad", "dailyTrainingLoadAcute")
_HISTORY_WRAPPERS: Final = (
    "data",
    "weeklyTrainingStatusDTO",
    "weeklyTrainingStatusDTOList",
    "weeklyTrainingStatus",
    "trainingStatusDTOList",
)
_GROUP_FIELDS: Final = (
    ("groupAverage", MetricKind.ENDURANCE_SCORE_GROUP_AVERAGE),
    ("groupMax", MetricKind.ENDURANCE_SCORE_GROUP_MAX),
)
_DEVICE_SECTIONS: Final[dict[str, tuple[str, str, tuple[str, ...]]]] = {
    DAILY_TRAINING_STATUS: (
        "mostRecentTrainingStatus",
        "latestTrainingStatusData",
        _DAILY_COMPARABLE,
    ),
    TRAINING_LOAD_BALANCE: (
        "mostRecentTrainingLoadBalance",
        "metricsTrainingLoadBalanceDTOMap",
        _BALANCE_COMPARABLE,
    ),
}
_TOLERANCE_FIELD: Final = "toleranceScore"
# The legacy readers' walk limits.
_VISIT_LIMIT: Final = 2000
_LIST_LIMIT: Final = 500
_ROW_LIMIT: Final = 1000
_DAY_TEXT_LENGTH: Final = 10


@dataclass(frozen=True, slots=True)
class TrainingValue:
    """One provider value and where it came from; ``key`` names it in the record id."""

    day: date
    kind: MetricKind
    raw: object
    field: str
    key: str
    sport: Sport | None = None


def _iso_day(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < _DAY_TEXT_LENGTH:
        return None
    try:
        return date.fromisoformat(value[:_DAY_TEXT_LENGTH])
    except ValueError:
        return None


def _iso_text(value: object) -> str | None:
    day = _iso_day(value)
    return None if day is None else day.isoformat()


def _row_day(record: Mapping[str, Any]) -> date | None:
    days = {_iso_day(record.get(key)) for key in METRIC_DATE_KEYS}
    days.discard(None)
    return next(iter(days)) if len(days) == 1 else None


def history_rows(value: object) -> list[Mapping[str, Any]]:
    """Unwrap the history containers the legacy history reader unwraps."""
    for _ in range(8):
        if not isinstance(value, Mapping):
            break
        nested = next(
            (
                value[key]
                for key in _HISTORY_WRAPPERS
                if isinstance(value.get(key), Mapping | list)
            ),
            None,
        )
        if nested is None:
            return [value]
        value = nested
    if isinstance(value, list):
        return [row for row in value[:_ROW_LIMIT] if isinstance(row, Mapping)]
    return [value] if isinstance(value, Mapping) else []


def _acute_load(record: Mapping[str, Any]) -> tuple[object, str] | None:
    """Return the one acute load of a row at any depth, or None when absent or ambiguous."""
    values: dict[float, tuple[object, str]] = {}
    pending: list[Any] = [record]
    visited = 0
    while pending and visited < _VISIT_LIMIT:
        item = pending.pop()
        visited += 1
        if isinstance(item, Mapping):
            for field in _ACUTE_FIELDS:
                number = coerce_number(item.get(field))
                if number is not None and 0 <= number <= 100_000:
                    values.setdefault(number, (item[field], field))
            pending.extend(
                child for child in item.values() if isinstance(child, Mapping | list)
            )
        elif isinstance(item, list):
            pending.extend(item[:_LIST_LIMIT])
    return next(iter(values.values())) if len(values) == 1 else None


def _device_values(
    payload: object,
    section_key: str,
    devices_key: str,
    comparable: tuple[str, ...],
    fields: tuple[tuple[str, MetricKind], ...],
    nested: str | None,
) -> Iterator[TrainingValue]:
    record = primary_device_record(
        payload, section_key, devices_key, comparable, day=_iso_text
    )
    day = None if record is None else _iso_day(record.get("calendarDate"))
    if record is None or day is None:
        return
    source = record.get(nested) if nested is not None else record
    if not isinstance(source, Mapping):
        return
    for field, kind in fields:
        if source.get(field) is not None:
            yield TrainingValue(day, kind, source[field], field, kind.value)


def unresolved_device_record(section: str, payload: object) -> bool:
    """Return whether a device-keyed section lists devices but no record can be chosen."""
    keys = _DEVICE_SECTIONS.get(section)
    if keys is None or not isinstance(payload, Mapping):
        return False
    devices = payload.get(keys[1])
    nested = payload.get(keys[0])
    if not isinstance(devices, Mapping) and isinstance(nested, Mapping):
        devices = nested.get(keys[1])
    if not isinstance(devices, Mapping) or not devices:
        return False
    return (
        primary_device_record(payload, keys[0], keys[1], keys[2], day=_iso_text) is None
    )


def training_values(section: str, payload: object) -> list[TrainingValue]:
    """Return the values one training section reports; unreadable rows yield none."""
    if section == DAILY_TRAINING_STATUS:
        return list(
            _device_values(
                payload,
                "mostRecentTrainingStatus",
                "latestTrainingStatusData",
                _DAILY_COMPARABLE,
                _DAILY_FIELDS,
                _ACUTE_DTO,
            )
        )
    if section == TRAINING_LOAD_BALANCE:
        return list(
            _device_values(
                payload,
                "mostRecentTrainingLoadBalance",
                "metricsTrainingLoadBalanceDTOMap",
                _BALANCE_COMPARABLE,
                _BALANCE_FIELDS,
                None,
            )
        )
    values: list[TrainingValue] = []
    for row in history_rows(payload):
        day = _row_day(row)
        if day is None:
            continue
        if section in (TRAINING_STATUS, WEEKLY_TRAINING_STATUS):
            found = _acute_load(row)
            if found is not None:
                raw, field = found
                values.append(
                    TrainingValue(day, MetricKind.ACUTE_LOAD, raw, field, "acute_load")
                )
        elif section == RUNNING_TOLERANCE:
            if row.get(_TOLERANCE_FIELD) is not None:
                values.append(
                    TrainingValue(
                        day,
                        MetricKind.RUNNING_TOLERANCE,
                        row[_TOLERANCE_FIELD],
                        _TOLERANCE_FIELD,
                        "running_tolerance",
                        Sport.RUN,
                    )
                )
        elif section == TRAINING_READINESS_HISTORY:
            alias = next(
                (key for key in PLANNING_READINESS_ALIASES if row.get(key) is not None),
                None,
            )
            if alias is not None:
                values.append(
                    TrainingValue(
                        day, MetricKind.READINESS, row[alias], alias, "readiness"
                    )
                )
    return values


def endurance_group_values(payload: object) -> list[TrainingValue]:
    """Return the group average and maximum of each dated ``groupMap`` entry."""
    groups = payload.get("groupMap") if isinstance(payload, Mapping) else None
    if not isinstance(groups, Mapping):
        return []
    values: list[TrainingValue] = []
    for key, group in list(groups.items())[:_ROW_LIMIT]:
        day = _iso_day(key) if len(str(key)) == _DAY_TEXT_LENGTH else None
        if day is None or not isinstance(group, Mapping):
            continue
        for field, kind in _GROUP_FIELDS:
            if group.get(field) is not None:
                values.append(TrainingValue(day, kind, group[field], field, kind.value))
    return values
