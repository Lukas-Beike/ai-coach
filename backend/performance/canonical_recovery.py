"""Canonical current recovery values: sleep score, resting HR and readiness.

Each value is selected by ``select_current`` pinned to the snapshot's latest
wellness day, the same selection the consumer parity ledger checks for these
fields. The canonical value replaces the legacy value only when it has the same
provider as the legacy source, the same day where the legacy output carries one,
and the same number, compared exactly. The replacement keeps the legacy
Python type, so the serialized output stays byte-identical. Otherwise the legacy
value is kept.

Source labels stay the legacy strings. The label table has no recovery view, so
the legacy reader keeps naming the source. Sleep hours, sleep date, HRV, the
resting HR date and the sleep and HRV averages stay on the legacy path. The
resting HR and readiness 7-day averages come from
``backend.performance.canonical_recovery_averages``.

The reader window starts at the snapshot's earliest wellness day and has no upper
bound, because Garmin records may be newer than the latest wellness row. Garmin
records older than the window cannot match, so the legacy value is kept.

``read_daily_recovery`` serves the planning view: it reads each kind once over the
legacy planning day span and applies the daily source rule per day.

A snapshot without a usable wellness day never reaches this module, and the
caller keeps the legacy values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.source_policy import select_current, select_daily
from backend.runtime.ports import ObservationReader


@dataclass(frozen=True, slots=True)
class CanonicalDailyRecovery:
    """Per-day observations for the planning recovery view, keyed by ISO day.

    Each map holds at most one observation per day: the one ``select_daily`` picks
    under the daily source rule of its kind.
    """

    sleep_score: Mapping[str, Observation]
    resting_hr: Mapping[str, Observation]
    readiness: Mapping[str, Observation]

    def by_field(self) -> dict[str, Mapping[str, Observation]]:
        """Map each planning field name to its per-day observations."""
        return {
            "sleep_score": self.sleep_score,
            "resting_hr": self.resting_hr,
            "readiness": self.readiness,
        }


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
    if legacy != value:
        return legacy
    return type(legacy)(value)


def read_daily_recovery(
    reader: ObservationReader,
    db: Any,
    *,
    start: date,
    end: date,
) -> CanonicalDailyRecovery:
    """Select each recovery value per day within the inclusive window.

    ``reader`` must already be the source chosen for the unit of work. Days without
    an eligible observation are absent from the maps.
    """
    return CanonicalDailyRecovery(
        sleep_score=_daily(reader, db, MetricKind.SLEEP_SCORE, start, end),
        resting_hr=_daily(reader, db, MetricKind.RESTING_HR, start, end),
        readiness=_daily(reader, db, MetricKind.READINESS, start, end),
    )


def _daily(
    reader: ObservationReader,
    db: Any,
    kind: MetricKind,
    start: date,
    end: date,
) -> dict[str, Observation]:
    observations = reader.observations(db, kind, start=start, end=end)
    return {
        day.isoformat(): observation
        for day, observation in select_daily(observations, kind).items()
    }


def _selected(
    reader: ObservationReader,
    db: Any,
    kind: MetricKind,
    latest_wellness_day: date,
    start: date,
) -> Observation | None:
    observations = reader.observations(db, kind, start=start)
    return select_current(observations, kind, latest_wellness_day=latest_wellness_day)
