"""Activity and wellness inputs of the performance readers, read through the selector.

The performance readers used to read the Intervals.icu snapshot sections
``recent_activities``, ``raw_provider_data.activities``, ``recent_wellness`` and
``raw_provider_data.wellness``. This module rebuilds the same shapes from the
canonical read ports, so the serving source (legacy projection or tables) decides
where the values come from:

* Activities are the raw rows of ``ActivityRowReader.activity_rows``. The compact
  shape that ``recent_activities`` had is derived from those rows with the planning
  compaction (``ACTIVITY_FIELDS``).
* Wellness rows are rebuilt from the Intervals.icu wellness-day observations
  (``ObservationReader``): one row per day, holding the first alias of each
  canonical field (``restingHR``, ``hrv``, ``sleepSecs``, ``ctl`` ...).

The athlete's Intervals.icu ratings ``fatigue``/``soreness``/``stress``/``mood``
are rebuilt from their SUBJECTIVE_* observations. Wellness fields without a
canonical observation (``tsb``, ``rampRate`` and the ``sportInfo`` eFTP) are not
rebuilt. They still come from the snapshot's wellness rows when the
snapshot holds them, and are absent when it does not. The snapshot rows act only as
the carrier of these fields: a canonical observation always wins over a snapshot
value of the same field, and a snapshot without wellness rows yields rows from
observations alone.

The day window is anchored on observation data, never on a snapshot section: the
latest wellness day is the latest day of any wellness row or observation, and
observation-only days are added for the 90 days ending on it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.providers.intervals_activity_fields import ACTIVITY_FIELDS, selected
from backend.runtime.ports import ObservationReader

WELLNESS_WINDOW_DAYS: Final = 90

# First provider alias of each canonical wellness field (see the Intervals wellness
# mapper). Readers try this alias first, so it carries the canonical value.
WELLNESS_ROW_KEYS: Final[Mapping[MetricKind, str]] = {
    MetricKind.WEIGHT: "weight",
    MetricKind.BODY_FAT: "bodyFat",
    MetricKind.RESTING_HR: "restingHR",
    MetricKind.HRV_RMSSD: "hrv",
    MetricKind.HRV_SDNN: "hrvSDNN",
    MetricKind.SLEEP_DURATION: "sleepSecs",
    MetricKind.SLEEP_SCORE: "sleepScore",
    MetricKind.READINESS: "readiness",
    MetricKind.VO2MAX: "vo2max",
    MetricKind.CTL: "ctl",
    MetricKind.ATL: "atl",
    MetricKind.SUBJECTIVE_FATIGUE: "fatigue",
    MetricKind.SUBJECTIVE_SORENESS: "soreness",
    MetricKind.SUBJECTIVE_STRESS: "stress",
    MetricKind.SUBJECTIVE_MOOD: "mood",
}

type WellnessObservations = Mapping[MetricKind, Sequence[Observation]]


def compact_activity_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the compact ``recent_activities`` shape of raw activity rows."""
    return [selected(row, ACTIVITY_FIELDS) for row in rows]


def read_wellness_observations(
    reader: ObservationReader, db: Any
) -> dict[MetricKind, tuple[Observation, ...]]:
    """Read the Intervals.icu wellness-day observations of every wellness field.

    Athlete-record and sport-scoped observations (thresholds, athlete weight) are
    not wellness days and are left out: a wellness-day observation has no sport and
    carries its own ISO day as record id.
    """
    return {
        kind: tuple(
            observation
            for observation in reader.observations(db, kind)
            if _is_wellness_day(observation)
        )
        for kind in WELLNESS_ROW_KEYS
    }


def wellness_rows(
    carrier: Iterable[Mapping[str, Any]],
    observed: WellnessObservations,
) -> list[dict[str, Any]]:
    """Return wellness rows: carrier rows overlaid with, and extended by, observations.

    Carrier rows keep their order and every field the observations do not cover.
    Observation days that no carrier row has, inside the window ending on the latest
    day, are added as new rows and the result is then ordered by row id.
    """
    values = _values_by_day(observed)
    rows: list[dict[str, Any]] = []
    seen: set[date] = set()
    for source in carrier:
        row = dict(source)
        day = row_day(row)
        if day is not None:
            seen.add(day)
            row.update(values.get(day, {}))
        rows.append(row)
    latest = max([*seen, *values], default=None)
    if latest is None:
        return rows
    start = latest - timedelta(days=WELLNESS_WINDOW_DAYS - 1)
    added = [
        {"id": day.isoformat(), **values[day]}
        for day in sorted(values)
        if day not in seen and start <= day <= latest
    ]
    if not added:
        return rows
    return sorted([*rows, *added], key=lambda row: str(row.get("id") or ""))


def row_day(row: Mapping[str, Any]) -> date | None:
    """Return the row's day only for a strict ``YYYY-MM-DD`` id."""
    text = row.get("id")
    if not isinstance(text, str):
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    return day if day.isoformat() == text else None


def _is_wellness_day(observation: Observation) -> bool:
    provenance = observation.provenance
    return (
        provenance.provider is ProviderId.INTERVALS
        and observation.sport is None
        and provenance.source_record_id == observation.observed_on.isoformat()
    )


def _values_by_day(observed: WellnessObservations) -> dict[date, dict[str, Any]]:
    values: dict[date, dict[str, Any]] = {}
    for kind, key in WELLNESS_ROW_KEYS.items():
        for observation in observed.get(kind, ()):
            values.setdefault(observation.observed_on, {})[key] = _row_number(
                observation.value.value
            )
    return values


def _row_number(value: float) -> float | int:
    number = float(value)
    return int(number) if number.is_integer() else number
