"""Canonical ATL for the season-preparation load basis, read from observations.

The explicit scenario model starts from yesterday's wellness row. Its ATL is read
as the Intervals.icu observation of that exact day, selected by ``select_current``
pinned to that day. The legacy value stays unless the observation is an Intervals.icu
record of the same day that carries the same number, so the scenario output stays
byte-identical. The basis label is derived from the matched observation through the
label table, and it is the legacy string.

CTL stays on the legacy path: the consumer parity ledger marks ``ctl`` as not
switchable, while ``atl`` is switchable.

A snapshot read and this read share one unit of work, so a concurrent sync cannot
mix revisions. Without a canonical source the legacy call shape is kept.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.canonical_inputs import (
    CanonicalPerformanceSource,
    resolve_reader,
)
from backend.performance.source_policy import select_current
from backend.providers.source_labels import (
    SourceView,
    observation_source_label,
    provider_label,
)
from backend.runtime.ports import ObservationReader


@dataclass(frozen=True, slots=True)
class CanonicalSeasonLoad:
    """The ATL observation of ``basis_day``, or None when canonical has none."""

    basis_day: date
    atl: Observation | None


def season_load_options(
    canonical: CanonicalSeasonLoad | None,
) -> dict[str, CanonicalSeasonLoad]:
    """Keyword arguments for ``load_scenarios``, empty when there is no canonical read."""
    return {} if canonical is None else {"canonical": canonical}


def read_season_load(
    reader: ObservationReader, db: Any, *, basis_day: date
) -> CanonicalSeasonLoad:
    """Select the ATL observed on ``basis_day``.

    ``reader`` must already be the source chosen for the unit of work.
    """
    observations = reader.observations(
        db, MetricKind.ATL, start=basis_day, end=basis_day
    )
    return CanonicalSeasonLoad(
        basis_day=basis_day,
        atl=select_current(observations, MetricKind.ATL, latest_wellness_day=basis_day),
    )


def snapshot_with_season_load(
    source: CanonicalPerformanceSource | None,
    read_snapshot: Callable[[], Any],
    basis_day: date,
) -> tuple[Any, CanonicalSeasonLoad | None]:
    """Read a snapshot and the basis-day ATL in one unit of work.

    Without a canonical source the snapshot is read exactly as before.
    """
    if source is None:
        return read_snapshot(), None
    with source.database_manager().unit_of_work() as db:
        snapshot = read_snapshot()
        reader = resolve_reader(source.observation_reader(), db)
        return snapshot, read_season_load(reader, db, basis_day=basis_day)


def matched_atl(
    canonical: CanonicalSeasonLoad | None, legacy: float | None
) -> Observation | None:
    """Return the ATL observation when it is the record the legacy scenario reads.

    It must be an Intervals.icu observation of the basis day, and its number must
    equal the legacy number. A missing legacy value never matches.
    """
    if canonical is None or canonical.atl is None or legacy is None:
        return None
    observation = canonical.atl
    if observation.provenance.provider is not ProviderId.INTERVALS:
        return None
    if observation.observed_on != canonical.basis_day:
        return None
    return observation if float(legacy) == observation.value.value else None


def served_atl(
    canonical: CanonicalSeasonLoad | None, legacy: float | None
) -> tuple[float | None, str]:
    """Return the ATL to report and the basis label; canonical only when it matches."""
    served = matched_atl(canonical, legacy)
    if served is None:
        return legacy, provider_label(
            ProviderId.INTERVALS, SourceView.SEASON_PREPARATION
        )
    return float(served.value.value), observation_source_label(
        served, SourceView.SEASON_PREPARATION
    )
