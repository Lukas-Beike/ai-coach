"""Canonical current recovery values: sleep score, resting HR and readiness.

Each value is selected by ``select_current`` pinned to the snapshot's latest
wellness day, the same selection the consumer parity ledger checks for these
fields. The canonical value replaces the legacy value only when it is the same
record the legacy reader picked: the same provider, the same day where the
legacy output carries one, and the same number. The replacement keeps the legacy
Python type, so the serialized output stays byte-identical. Otherwise the legacy
value is kept.

Source labels stay the legacy strings. The label table has no recovery view, so
the legacy reader keeps naming the source. Sleep hours, sleep date, HRV, the
resting HR date and all averages stay on the legacy path.

The reader window starts at the snapshot's earliest wellness day and has no upper
bound, because Garmin records may be newer than the latest wellness row. Garmin
records older than the window cannot match, so the legacy value is kept.

A snapshot without a usable wellness day never reaches this module, and the
caller keeps the legacy values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.source_policy import select_current
from backend.runtime.ports import ObservationReader


@dataclass(frozen=True, slots=True)
class CanonicalRecoveryInputs:
    """The observations selected for the current sleep score, resting HR and readiness.

    A field is None when the canonical selection has no observation for it.
    """

    sleep_score: Observation | None
    resting_hr: Observation | None
    readiness: Observation | None


def read_recovery_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    latest_wellness_day: date,
    start: date,
) -> CanonicalRecoveryInputs:
    """Select each recovery value once, for the snapshot's latest wellness day.

    ``reader`` must already be the source chosen for the unit of work.
    """
    return CanonicalRecoveryInputs(
        sleep_score=_selected(
            reader, db, MetricKind.SLEEP_SCORE, latest_wellness_day, start
        ),
        resting_hr=_selected(
            reader, db, MetricKind.RESTING_HR, latest_wellness_day, start
        ),
        readiness=_selected(
            reader, db, MetricKind.READINESS, latest_wellness_day, start
        ),
    )


def prefer_canonical(
    observation: Observation | None,
    legacy: Any,
    provider: ProviderId,
    day: Any = None,
) -> Any:
    """Return the canonical value when it is the legacy-selected record, else legacy.

    The canonical observation must come from ``provider``, the provider the legacy
    reader picked, and, when ``day`` is given, be observed on that day. Its number
    must equal the legacy number. A legacy value that is not a plain int or float
    (a string, a bool, None) is always kept.
    """
    if observation is None or type(legacy) not in (int, float):
        return legacy
    if observation.provenance.provider is not provider:
        return legacy
    if day is not None and observation.observed_on.isoformat() != day:
        return legacy
    value = observation.value.value
    if float(legacy) != value:
        return legacy
    return type(legacy)(value)


def _selected(
    reader: ObservationReader,
    db: Any,
    kind: MetricKind,
    latest_wellness_day: date,
    start: date,
) -> Observation | None:
    observations = reader.observations(db, kind, start=start)
    return select_current(observations, kind, latest_wellness_day=latest_wellness_day)
