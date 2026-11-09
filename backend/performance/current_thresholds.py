"""Current sport thresholds under the source policy, shared by Coach and plan.

The current FTP, threshold heart rate, threshold pace and maximum heart rate of
each sport are resolved once for a day, with one precedence:

1. the athlete's locally confirmed zone configuration in effect on the day;
2. the Garmin watch zone set in effect on the day, for the lactate threshold
   heart rate (``lactateThresholdHeartRateUsed``, the watch-first rule of
   ``zone_settings.configured_threshold``);
3. the source-policy observations (``source_policy.resolve_candidates``): the
   latest Garmin value (``garmin_canonical.garmin_thresholds``) and the current
   Wahoo cycling FTP.

Layers 1 and 2 are ``configured_thresholds``; every consumer reads them through
it or through ``ZoneSettings``, which applies the same ``configured_threshold``:
zones, the local session load (M6), current metrics and the Coach run heart-rate
caps, planned-unit load, the export header and the staleness hint. Each value
keeps its source (local or Garmin). Intervals.icu values are never a source
(athlete decision 2026-11-07).

The Coach context and the current metrics read the resolved values with their
alternatives and conflict flags. Plans read ``provider_zone_thresholds``, the
provider winners only: ``ZoneSettings`` applies the configured layers per
planned day ahead of these values, so both use the same threshold on a day.

This module must not import ``server.py`` or providers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Final, Protocol, runtime_checkable

from backend.activities.zone_settings import configured_threshold
from backend.canonical.domain_records import ZoneConfiguration
from backend.canonical.records import MetricValue, Observation
from backend.canonical.vocabulary import (
    MetricKind,
    Sport,
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


def configured_thresholds(
    configurations: Iterable[ZoneConfiguration], day: date
) -> tuple[Observation, ...]:
    """Return the stored thresholds that lead the source-policy values on ``day``.

    These are the first two layers of the dated precedence, decided by
    ``configured_threshold``: the athlete-confirmed configuration in effect (no
    provider) and, for the lactate threshold heart rate, the dated Garmin watch
    zone set in effect. Each keeps its own provenance, so the source label stays
    local or Garmin. Values outside the canonical bounds are skipped.
    """
    result: list[Observation] = []
    for kind, sport in THRESHOLD_KEYS:
        found = configured_threshold(configurations, kind, sport, day)
        if found is None:
            continue
        value, chosen = found
        try:
            result.append(
                Observation(
                    kind=kind,
                    value=MetricValue(value, kind.unit),
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
    configured: Iterable[Observation] = (),
    *,
    as_of: date | None,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> Mapping[ThresholdKey, Resolved]:
    """Resolve each threshold key; keys without a current value are absent.

    Besides ``THRESHOLD_KEYS``, any other sport a provider gives a threshold for
    is resolved under the same rule.
    """
    observations = tuple(provider_observations)
    local_values = tuple(configured)
    other_sports = (
        (item.kind, sport)
        for item in (*observations, *local_values)
        if item.kind in LOCAL_FIRST_KINDS and (sport := item.sport) is not None
    )
    keys: list[ThresholdKey] = list(dict.fromkeys((*THRESHOLD_KEYS, *other_sports)))
    resolved: dict[ThresholdKey, Resolved] = {}
    for kind, sport in keys:
        # Configured values come first: a source's first candidate counts, so a
        # Garmin watch zone set leads Garmin's stored observation.
        candidates = [
            Candidate(
                item.provenance.provider,
                float(item.value.value),
                item.observed_on,
                item,
            )
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
