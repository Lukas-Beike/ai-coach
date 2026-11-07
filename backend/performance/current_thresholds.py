"""Current sport thresholds under the source policy, shared by Coach and plan.

The current FTP, threshold heart rate, threshold pace and maximum heart rate of
each sport are resolved once, by ``source_policy.resolve_candidates``, from:

* the athlete's locally confirmed zone configuration in effect on the day,
* the latest Garmin value (``garmin_canonical.garmin_thresholds``),
* the current Wahoo cycling FTP.

Intervals.icu values are never a source (athlete decision 2026-11-07).

The Coach context and the current metrics read the resolved values with their
alternatives and conflict flags. Plans read ``provider_zone_thresholds``, the
provider winners only: they apply local configurations per planned day
themselves, ahead of these values, so both use the same threshold on a day.

This module must not import ``server.py`` or providers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Final, Protocol, runtime_checkable

from backend.activities.zone_settings import effective_zone_configuration
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import MetricValue, Observation
from backend.canonical.vocabulary import (
    MetricKind,
    Sport,
    ZoneConfigurationMetric,
)
from backend.performance.source_policy import (
    LOCAL_FIRST_KINDS,
    NO_PREFERENCES,
    Candidate,
    Resolved,
    SourcePreferences,
    resolve_candidates,
)

type ThresholdKey = tuple[MetricKind, Sport]

THRESHOLD_KEYS: Final[tuple[ThresholdKey, ...]] = (
    (MetricKind.FTP, Sport.RIDE),
    (MetricKind.FTP, Sport.RUN),
    (MetricKind.THRESHOLD_HR, Sport.RIDE),
    (MetricKind.THRESHOLD_HR, Sport.RUN),
    (MetricKind.THRESHOLD_PACE, Sport.RUN),
    (MetricKind.MAX_HR, Sport.RIDE),
    (MetricKind.MAX_HR, Sport.RUN),
)


@runtime_checkable
class ZoneConfigurationSource(Protocol):
    """A canonical source that also serves the stored zone configurations."""

    def zone_configurations(self, db: Any) -> tuple[ZoneConfiguration, ...]: ...


def local_thresholds(
    configurations: Iterable[ZoneConfiguration], day: date
) -> tuple[Observation, ...]:
    """Return the thresholds of the local configurations in effect on ``day``.

    Only athlete-confirmed configurations (no provider) count. Values outside the
    canonical bounds are skipped.
    """
    local = [item for item in configurations if item.provenance.provider is None]
    result: list[Observation] = []
    for kind, sport in THRESHOLD_KEYS:
        metric = {
            MetricKind.FTP: ZoneConfigurationMetric.POWER,
            MetricKind.THRESHOLD_PACE: ZoneConfigurationMetric.PACE,
        }.get(kind, ZoneConfigurationMetric.HEART_RATE)
        chosen = effective_zone_configuration(local, metric, sport, day=day)
        if chosen is None:
            continue
        value = chosen.maximum if kind is MetricKind.MAX_HR else chosen.threshold
        if not value:
            continue
        try:
            result.append(
                Observation(
                    kind=kind,
                    value=MetricValue(float(value), kind.unit),
                    observed_on=day,
                    observed_at=None,
                    provenance=chosen.provenance,
                    sport=sport,
                )
            )
        except ValueError:
            continue
    return tuple(result)


def _provider_candidates(
    observations: Sequence[Observation], kind: MetricKind, sport: Sport
) -> list[Candidate]:
    """Each provider's observations of ``kind`` for ``sport``, best first.

    The caller gives one current observation per provider and sport.
    """
    return [
        Candidate(
            item.provenance.provider,
            float(item.value.value),
            item.observed_on,
            item,
        )
        for item in observations
        if item.kind is kind and item.sport is sport
    ]


def resolve_current_thresholds(
    provider_observations: Iterable[Observation],
    local: Iterable[Observation] = (),
    *,
    as_of: date | None,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> Mapping[ThresholdKey, Resolved]:
    """Resolve each threshold key; keys without a current value are absent.

    Besides ``THRESHOLD_KEYS``, any other sport a provider gives a threshold for
    is resolved under the same rule.
    """
    observations = tuple(provider_observations)
    local_values = tuple(local)
    other_sports = (
        (item.kind, sport)
        for item in (*observations, *local_values)
        if item.kind in LOCAL_FIRST_KINDS and (sport := item.sport) is not None
    )
    keys: list[ThresholdKey] = list(dict.fromkeys((*THRESHOLD_KEYS, *other_sports)))
    resolved: dict[ThresholdKey, Resolved] = {}
    for kind, sport in keys:
        candidates = [
            Candidate(None, float(item.value.value), item.observed_on, item)
            for item in local_values
            if item.kind is kind and item.sport is sport
        ]
        candidates += _provider_candidates(observations, kind, sport)
        result = resolve_candidates(
            kind, candidates, as_of=as_of, sport=sport, preferences=preferences
        )
        if result is not None:
            resolved[(kind, sport)] = result
    return resolved


def provider_zone_thresholds(
    provider_observations: Iterable[Observation],
    *,
    as_of: date | None,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> tuple[Observation, ...]:
    """Return the provider winners per threshold key.

    Plans put their local configurations ahead of these.
    """
    return tuple(
        winner
        for result in resolve_current_thresholds(
            tuple(provider_observations), as_of=as_of, preferences=preferences
        ).values()
        if (winner := result.winner.observation) is not None
    )
