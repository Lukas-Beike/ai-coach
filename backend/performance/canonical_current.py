"""Canonical current metrics: Wahoo fallbacks, local and Garmin thresholds.

Intervals.icu is output-only and never a source of current values (athlete
decision 2026-11-07). The current inputs hold the stored Wahoo cycling FTP and
weight, the locally confirmed thresholds in effect on the athlete-local ``as_of``
day, and the plan-zone thresholds the source policy resolves from them and from
Garmin's.

Wahoo cycling FTP and Wahoo weight are read without a sync instant, because each
Wahoo row keeps its own fetch time. A Wahoo value older than its age limit on
``as_of`` is not current. Its row stays stored and readable, so history keeps it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Final

from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance.current_thresholds import (
    ThresholdKey,
    ZoneConfigurationSource,
    local_thresholds,
    provider_zone_thresholds,
    resolve_current_thresholds,
)
from backend.performance.garmin_canonical import (
    ActivityMaxHr,
    provider_activity_max_hr,
    read_garmin_thresholds,
)
from backend.performance.source_policy import (
    NO_PREFERENCES,
    SourcePreferences,
    select_current,
)
from backend.runtime.ports import ObservationReader

_EARLIEST: Final = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CanonicalCurrentInputs:
    """The stored Wahoo fallbacks and the resolved thresholds of one read.

    ``wahoo_ftp`` is the newest cycling FTP and ``wahoo_weight`` the newest weight
    stored from Wahoo, or None. ``zone_thresholds`` are the source-policy provider
    winners per sport (FTP, threshold and maximum heart rate, threshold pace): the
    thresholds of the plan zones and of planned-unit load.
    ``threshold_candidates`` are the Wahoo threshold candidates of the current
    metrics and ``local_thresholds`` the thresholds of the local zone
    configurations in effect on ``as_of``. Current metrics resolve them with the
    Garmin thresholds of the same read.
    """

    wahoo_ftp: Observation | None = None
    wahoo_weight: Observation | None = None
    zone_thresholds: tuple[Observation, ...] = ()
    threshold_candidates: tuple[Observation, ...] = ()
    local_thresholds: tuple[Observation, ...] = ()
    # The highest stored Wahoo activity max heart rate per category (cycling,
    # running), over the whole history: the activity fallback beside Garmin's.
    wahoo_activity_max_hr: Mapping[str, ActivityMaxHr] = field(default_factory=dict)
    # The athlete's preferred sources, applied to the thresholds and body values.
    preferences: SourcePreferences = NO_PREFERENCES


NO_CURRENT_INPUTS: Final = CanonicalCurrentInputs()


def read_current_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    as_of: date,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> CanonicalCurrentInputs:
    """Read the Wahoo fallbacks and the thresholds current on ``as_of``.

    ``as_of`` is the athlete-local day the Wahoo values must be current on.
    Without anything stored every field is empty.
    """
    wahoo_ftp, wahoo_weight = _wahoo_current(reader, db, as_of=as_of)
    candidates = (wahoo_ftp,) if wahoo_ftp is not None else ()
    providers = _provider_thresholds(reader, db, wahoo_ftp)
    local = (
        local_thresholds(reader.zone_configurations(db), as_of)
        if isinstance(reader, ZoneConfigurationSource)
        else ()
    )
    return CanonicalCurrentInputs(
        wahoo_ftp=wahoo_ftp,
        wahoo_weight=wahoo_weight,
        zone_thresholds=provider_zone_thresholds(
            providers, as_of=as_of, preferences=preferences
        ),
        threshold_candidates=candidates,
        local_thresholds=local,
        preferences=preferences,
        wahoo_activity_max_hr=provider_activity_max_hr(reader, db, ProviderId.WAHOO),
    )


def read_zone_thresholds(
    reader: ObservationReader,
    db: Any,
    *,
    as_of: date,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> tuple[Observation, ...]:
    """Return the plan-zone thresholds (``zone_thresholds``) current on ``as_of``.

    A reader that already holds ``CanonicalCurrentInputs`` takes them from there.
    """
    return provider_zone_thresholds(
        _provider_thresholds(reader, db, _wahoo_ftp(reader, db, as_of=as_of)),
        as_of=as_of,
        preferences=preferences,
    )


def _provider_thresholds(
    reader: ObservationReader, db: Any, wahoo_ftp: Observation | None
) -> tuple[Observation, ...]:
    """The provider threshold candidates: the current Wahoo FTP, then Garmin's."""
    return (
        *((wahoo_ftp,) if wahoo_ftp is not None else ()),
        *read_garmin_thresholds(reader, db),
    )


def read_export_thresholds(
    reader: ObservationReader,
    db: Any,
    *,
    as_of: date,
    preferences: SourcePreferences = NO_PREFERENCES,
    configurations: Iterable[ZoneConfiguration] | None = None,
) -> dict[ThresholdKey, Observation]:
    """Return the thresholds an outbound export sends, current on ``as_of``.

    ``configurations`` are the stored zone configurations; without them the
    reader's are used (none when it serves no configurations).

    The local zone configuration in effect wins, then Garmin, then Wahoo, under
    the source policy and the athlete's preferences. Intervals.icu values are never
    a source, so a value Intervals reported is never sent back to it (#1729).
    """
    providers = _provider_thresholds(reader, db, _wahoo_ftp(reader, db, as_of=as_of))
    if configurations is None and isinstance(reader, ZoneConfigurationSource):
        configurations = reader.zone_configurations(db)
    local = local_thresholds(configurations or (), as_of)
    return {
        key: winner
        for key, result in resolve_current_thresholds(
            providers, local, as_of=as_of, preferences=preferences
        ).items()
        if (winner := result.winner.observation) is not None
    }


def _wahoo_current(
    reader: ObservationReader, db: Any, *, as_of: date
) -> tuple[Observation | None, Observation | None]:
    """Return the current Wahoo cycling FTP and the current Wahoo weight, or None each.

    Sport-scoped ranking ignores days, so the cycling FTP is reduced first to the
    newest stored zone set, by observed day and then fetch time. The weight is
    ranked by ``select_current`` over every stored Wahoo weight. Both must be within
    their age limit on ``as_of``.
    """
    ftp = _wahoo_ftp(reader, db, as_of=as_of)
    weights = [
        observation
        for observation in reader.observations(db, MetricKind.WEIGHT)
        if observation.provenance.provider is ProviderId.WAHOO
    ]
    return ftp, select_current(weights, MetricKind.WEIGHT, as_of=as_of)


def _wahoo_ftp(
    reader: ObservationReader, db: Any, *, as_of: date
) -> Observation | None:
    """The newest stored Wahoo cycling FTP when it is current on ``as_of``."""
    newest = newest_wahoo_ftp(reader, db)
    if newest is None:
        return None
    return select_current([newest], MetricKind.FTP, sport=Sport.RIDE, as_of=as_of)


def newest_wahoo_ftp(reader: ObservationReader, db: Any) -> Observation | None:
    """The newest stored Wahoo cycling FTP, whatever its age."""
    ftps = [
        observation
        for observation in reader.observations(db, MetricKind.FTP)
        if observation.provenance.provider is ProviderId.WAHOO
        and observation.sport is Sport.RIDE
    ]
    return max(ftps, key=_newest_first, default=None)


def _newest_first(observation: Observation) -> tuple[date, datetime]:
    """Order observations by observed day, then fetch time; a missing fetch time is oldest."""
    return observation.observed_on, observation.provenance.retrieved_at or _EARLIEST
