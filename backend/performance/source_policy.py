"""Source precedence for canonical observations.

Pure, table-driven rules that decide which provider's observation is the current
or per-day value for a metric. The tables reproduce the precedence of the legacy
readers in ``backend.performance``:

* ``current_metrics`` (weight, body fat, thresholds, max HR, VO2max),
* ``recovery_context`` and ``recovery`` (sleep, resting HR, HRV, readiness),
* ``load_context`` (CTL and ATL),
* ``planning_recovery`` (the date-indexed planning view).

Selection, for ``select_current``: observations are filtered by kind, by the
optional sport and by the rule's per-provider bounds. The first provider in the
rule's order that still has an observation wins, and its newest observation is
returned. For ``select_daily``, each calendar day independently takes the first
provider in the rule's order that has an observation that day; daily rules have
no bounds.

Ties are deterministic. "Newest" compares ``observed_on``, then ``observed_at``
(an observation without a timestamp is older than any timestamped one). Full ties
keep the observation that appears first in the input, which for the Intervals
mapper is the order of ``sportSettings`` and the row order of the wellness list.
Legacy current views keep the last same-day Garmin duplicate instead; that is a
named deviation, not a rule of this module.

Known gaps, pinned by named tests: Intervals fallbacks take the newest row that
has the field, while legacy reads only the newest row; the Garmin mapper does not
emit heart-rate-zone max HR; and athlete-level weight is not observed.

Values that this module does not see, and must stay with the caller: profile and
manual values, per-sport settings from the wellness row, Intervals eFTP, the
generic top-level FTP and threshold-HR fallbacks, and activity-derived fallbacks
such as the maximum recorded heart rate. The Intervals mapper already applies the
top-level FTP fallback when no Ride FTP was mapped from the athlete's sport settings.

Intentional deviations from the legacy readers are pinned by named tests in
``tests/test_source_policy.py``.

This module is stdlib-only except for ``backend.canonical`` and must not import
``server.py``, providers or other domain packages.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport

_GARMIN: Final = ProviderId.GARMIN
_INTERVALS: Final = ProviderId.INTERVALS
_EARLIEST: Final = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ProviderBounds:
    """Inclusive plausibility bounds applied to one provider's observations."""

    provider: ProviderId
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class SourceRule:
    """Provider order and optional bounds for one metric kind."""

    kind: MetricKind
    order: tuple[ProviderId, ...]
    bounds: tuple[ProviderBounds, ...] = ()


# Rules for select_current. A provider absent from ``order`` never supplies the kind.
CURRENT_RULES: Final[Mapping[MetricKind, SourceRule]] = MappingProxyType(
    {
        rule.kind: rule
        for rule in (
            # current_metrics: Garmin's newest weight wins even when older than the
            # Intervals wellness row. Body fat ignores Garmin entirely.
            SourceRule(MetricKind.WEIGHT, (_GARMIN, _INTERVALS)),
            SourceRule(MetricKind.BODY_FAT, (_INTERVALS,)),
            # recovery_context: newest in-bounds Garmin value, else Intervals latest.
            SourceRule(
                MetricKind.RESTING_HR,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 30.0, 230.0),),
            ),
            SourceRule(
                MetricKind.HRV_RMSSD,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 1.0, 300.0),),
            ),
            # Sleep duration and score: Garmin before Intervals. Readiness: the reverse.
            SourceRule(MetricKind.SLEEP_DURATION, (_GARMIN, _INTERVALS)),
            SourceRule(
                MetricKind.SLEEP_SCORE,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 0.0, 100.0),),
            ),
            SourceRule(MetricKind.READINESS, (_INTERVALS, _GARMIN)),
            # current_metrics: Garmin before Intervals sportSettings, per sport.
            SourceRule(
                MetricKind.FTP,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 50.0, 700.0),),
            ),
            SourceRule(
                MetricKind.THRESHOLD_HR,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 80.0, 230.0),),
            ),
            SourceRule(MetricKind.THRESHOLD_PACE, (_GARMIN, _INTERVALS)),
            SourceRule(MetricKind.MAX_HR, (_GARMIN, _INTERVALS)),
            SourceRule(
                MetricKind.VO2MAX,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 20.0, 100.0),),
            ),
            # load_context: Intervals only, latest row.
            SourceRule(MetricKind.CTL, (_INTERVALS,)),
            SourceRule(MetricKind.ATL, (_INTERVALS,)),
        )
    }
)

# Rules for select_daily. Garmin overwrites Intervals per day for sleep, HRV and
# resting HR without a bounds check. Readiness comes from Intervals, and Garmin
# only fills the days that Intervals leaves empty.
DAILY_RULES: Final[Mapping[MetricKind, SourceRule]] = MappingProxyType(
    {
        rule.kind: rule
        for rule in (
            SourceRule(MetricKind.SLEEP_DURATION, (_GARMIN, _INTERVALS)),
            SourceRule(MetricKind.SLEEP_SCORE, (_GARMIN, _INTERVALS)),
            SourceRule(MetricKind.HRV_RMSSD, (_GARMIN, _INTERVALS)),
            SourceRule(MetricKind.RESTING_HR, (_GARMIN, _INTERVALS)),
            SourceRule(MetricKind.READINESS, (_INTERVALS, _GARMIN)),
        )
    }
)

_SPORT_SCOPED: Final[frozenset[MetricKind]] = frozenset(
    {
        MetricKind.FTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.THRESHOLD_PACE,
        MetricKind.MAX_HR,
        MetricKind.VO2MAX,
    }
)

type _Recency = tuple[datetime, int]


def _recency(index: int, observation: Observation) -> _Recency:
    """Timestamp, then earliest input position, so that full ties keep input order."""
    return (observation.observed_at or _EARLIEST, -index)


def _within_bounds(observation: Observation, rule: SourceRule) -> bool:
    provider = observation.provenance.provider
    value = observation.value.value
    return all(
        bound.lower <= value <= bound.upper
        for bound in rule.bounds
        if bound.provider is provider
    )


def _eligible(
    observations: Iterable[Observation],
    kind: MetricKind,
    rule: SourceRule,
    sport: Sport | None,
) -> list[tuple[int, Observation]]:
    return [
        (index, observation)
        for index, observation in enumerate(observations)
        if observation.kind is kind
        and observation.provenance.provider in rule.order
        and (sport is None or observation.sport is sport)
        and _within_bounds(observation, rule)
    ]


def select_current(
    observations: Iterable[Observation],
    kind: MetricKind,
    *,
    sport: Sport | None = None,
) -> Observation | None:
    """Return the current observation for ``kind`` under its source rule.

    ``sport`` restricts the candidates to observations for that sport. Sport-scoped
    kinds require a sport, because legacy readers always select per sport; passing
    None for them raises ValueError rather than mixing sports by input order.
    Unknown kinds return None.
    """
    rule = CURRENT_RULES.get(kind)
    if rule is None:
        return None
    if sport is None and kind in _SPORT_SCOPED:
        raise ValueError(f"{kind.value} is sport-scoped and needs a sport")
    candidates = _eligible(observations, kind, rule, sport)
    for provider in rule.order:
        best: tuple[tuple[date, _Recency], Observation] | None = None
        for index, observation in candidates:
            if observation.provenance.provider is not provider:
                continue
            rank = (observation.observed_on, _recency(index, observation))
            if best is None or rank > best[0]:
                best = (rank, observation)
        if best is not None:
            return best[1]
    return None


def select_daily(
    observations: Iterable[Observation], kind: MetricKind
) -> Mapping[date, Observation]:
    """Return the per-day observation for ``kind`` under its daily rule.

    Days without any eligible observation are absent. Unknown kinds return an
    empty mapping.
    """
    rule = DAILY_RULES.get(kind)
    if rule is None:
        return {}
    best_by_day: dict[tuple[date, ProviderId], tuple[_Recency, Observation]] = {}
    for index, observation in enumerate(observations):
        provider = observation.provenance.provider
        if (
            observation.kind is not kind
            or provider is None
            or provider not in rule.order
        ):
            continue
        key = (observation.observed_on, provider)
        recency = _recency(index, observation)
        current = best_by_day.get(key)
        if current is None or recency > current[0]:
            best_by_day[key] = (recency, observation)
    # Visit days in order and, within a day, providers in rule order; the first
    # observation seen for a day is the one from the highest-priority provider.
    priority = {provider: position for position, provider in enumerate(rule.order)}
    result: dict[date, Observation] = {}
    for (day, provider), (_, observation) in sorted(
        best_by_day.items(), key=lambda item: (item[0][0], priority[item[0][1]])
    ):
        result.setdefault(day, observation)
    return result
