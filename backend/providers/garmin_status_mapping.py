"""Map Garmin status codes to canonical categorical observations.

Codes are kept as Garmin reports them and never turned into numbers:

* ``hrv``: HRV_STATUS from ``hrvStatus``, such as ``BALANCED``.
* ``readiness`` and ``training_readiness_history``: READINESS_LEVEL from ``level``.
* ``daily_training_status``: TRAINING_STATUS from ``trainingStatus`` of the primary
  (or unambiguous latest) device record, when Garmin sends a text code. A numeric
  status has no verified meaning and is not mapped.

Each code is dated by its record's ``calendarDate``; an undated record or a value
that is not a short code yields nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Final

from backend.canonical.domain_records import CategoricalObservation
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    CategoricalDomain,
    ProviderId,
    RecordingOrigin,
    SourceKind,
)
from backend.providers.garmin_device_records import primary_device_record
from backend.providers.garmin_training_mapping import (
    DAILY_TRAINING_STATUS,
    TRAINING_READINESS_HISTORY,
    history_rows,
)

GARMIN_LABEL: Final = "Garmin Connect"
HRV_SECTION: Final = "hrv"
READINESS_SECTION: Final = "readiness"
STATUS_SECTIONS: Final = frozenset(
    {HRV_SECTION, READINESS_SECTION, TRAINING_READINESS_HISTORY, DAILY_TRAINING_STATUS}
)
_CODE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
_DAY_TEXT_LENGTH: Final = 10
_ROW_LIMIT: Final = 1000
_DAILY_COMPARABLE: Final = ("calendarDate", "trainingStatus")


def _day(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < _DAY_TEXT_LENGTH:
        return None
    try:
        return date.fromisoformat(value[:_DAY_TEXT_LENGTH])
    except ValueError:
        return None


def _day_text(value: object) -> str | None:
    day = _day(value)
    return None if day is None else day.isoformat()


def _rows(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [row for row in value[:_ROW_LIMIT] if isinstance(row, Mapping)]
    return []


def map_garmin_status_codes(
    section: str,
    element: object,
    *,
    source_record_id: str,
    retrieved_at: datetime,
) -> tuple[CategoricalObservation, ...]:
    """Return the status codes of one stored element of a Garmin section."""
    if section == HRV_SECTION:
        domain, field = CategoricalDomain.HRV_STATUS, "hrvStatus"
        rows = _rows(element)
    elif section == READINESS_SECTION:
        domain, field = CategoricalDomain.READINESS_LEVEL, "level"
        rows = _rows(element)
    elif section == TRAINING_READINESS_HISTORY:
        domain, field = CategoricalDomain.READINESS_LEVEL, "level"
        rows = history_rows(element)
    elif section == DAILY_TRAINING_STATUS:
        domain, field = CategoricalDomain.TRAINING_STATUS, "trainingStatus"
        record = primary_device_record(
            element,
            "mostRecentTrainingStatus",
            "latestTrainingStatusData",
            _DAILY_COMPARABLE,
            day=_day_text,
        )
        rows = [] if record is None else [record]
    else:
        return ()
    provenance = Provenance(
        provider=ProviderId.GARMIN,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.GARMIN,
        retrieved_at=retrieved_at,
        label=GARMIN_LABEL,
    )
    codes: dict[date, CategoricalObservation] = {}
    for row in rows:
        code = row.get(field)
        day = _day(row.get("calendarDate"))
        if day is None or not isinstance(code, str) or not _CODE.fullmatch(code):
            continue
        codes.setdefault(
            day,
            CategoricalObservation(
                domain=domain,
                code=code,
                observed_on=day,
                observed_at=None,
                provenance=provenance,
            ),
        )
    return tuple(codes.values())
