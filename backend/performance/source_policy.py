"""Source precedence for canonical observations.

Pure, table-driven rules that decide which provider's observation is the current
or per-day value for a metric. Intervals.icu is output-only and never a source
(athlete decision 2026-11-07): the orders are Garmin, then Wahoo where it has the
kind (weight, FTP). A locally confirmed value precedes them where noted.

Selection, for ``select_current``: observations are filtered by kind, by the
optional sport and by the rule's per-provider bounds and age limits. The first
provider in the rule's order that still has an observation wins.

Within a provider, ``select_current`` ranks as follows:

* weight: newest ``observed_on``, then ``observed_at`` (missing is oldest), then
  the last input record;
* other dated kinds: newest ``observed_on``, then the last Garmin input record;
* sport-scoped kinds (FTP, thresholds, max HR, VO2max): dates are ignored and the
  last Garmin input record wins.

For ``select_daily``, each calendar day independently takes the first provider in
the rule's order that has an observation that day. Within a provider the first
input record wins and timestamps are ignored. Daily rules apply the current
rules' bounds.

Wahoo is the lowest-priority provider for current FTP and weight. Its FTP is the
newest stored cycling zone set, and its weight is the newest stored profile
weight. When the caller passes ``as_of`` (the athlete-local day), a Wahoo value
observed more than ``WAHOO_CURRENT_MAX_AGE_DAYS`` days before it is not current.
Such values stay in the observations, so history keeps them.

Values that this module does not see, and must stay with the caller: profile and
manual values, and activity-derived fallbacks such as the maximum recorded heart
rate.

Thresholds (FTP, threshold and maximum heart rate, threshold pace) are resolved
with ``resolve_candidates`` from each source's own current value: a locally
confirmed zone configuration first, then the providers in rule order, within each
provider's bounds and age limits. The result keeps the other sources as
alternatives with a conflict flag, so the Coach context, current metrics and plans
read one value.

This module is stdlib-only except for ``backend.canonical`` and must not import
``server.py``, providers or other domain packages.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, SourceKind, Sport

_GARMIN: Final = ProviderId.GARMIN
_WAHOO: Final = ProviderId.WAHOO
_EARLIEST: Final = datetime.min.replace(tzinfo=UTC)
_NO_DATE: Final = date.min
# A Wahoo FTP or weight observed longer ago than this is history, not the current value.
WAHOO_CURRENT_MAX_AGE_DAYS: Final = 90
# A Garmin threshold observed longer ago than this is history, not current.
GARMIN_THRESHOLD_MAX_AGE_DAYS: Final = 180


@dataclass(frozen=True, slots=True)
class ProviderBounds:
    """Inclusive plausibility bounds applied to one provider's observations."""

    provider: ProviderId
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class ProviderMaxAge:
    """Largest allowed age, in days before ``as_of``, of one provider's observations."""

    provider: ProviderId
    days: int


@dataclass(frozen=True, slots=True)
class SourceRule:
    """Provider order with optional bounds and age limits."""

    kind: MetricKind
    order: tuple[ProviderId, ...]
    bounds: tuple[ProviderBounds, ...] = ()
    max_age: tuple[ProviderMaxAge, ...] = ()


_THRESHOLD_MAX_AGE: Final = (ProviderMaxAge(_GARMIN, GARMIN_THRESHOLD_MAX_AGE_DAYS),)

# Rules for select_current. A provider absent from ``order`` never supplies the kind.
CURRENT_RULES: Final[Mapping[MetricKind, SourceRule]] = MappingProxyType(
    {
        rule.kind: rule
        for rule in (
            SourceRule(
                MetricKind.WEIGHT,
                (_GARMIN, _WAHOO),
                max_age=(ProviderMaxAge(_WAHOO, WAHOO_CURRENT_MAX_AGE_DAYS),),
            ),
            SourceRule(MetricKind.BODY_FAT, (_GARMIN,)),
            SourceRule(
                MetricKind.RESTING_HR,
                (_GARMIN,),
                (ProviderBounds(_GARMIN, 30.0, 230.0),),
            ),
            SourceRule(
                MetricKind.HRV_RMSSD,
                (_GARMIN,),
                (ProviderBounds(_GARMIN, 1.0, 300.0),),
            ),
            # Garmin's weekly HRV average: only a labelled fallback for RMSSD.
            SourceRule(
                MetricKind.HRV_WEEKLY_AVERAGE,
                (_GARMIN,),
                (ProviderBounds(_GARMIN, 1.0, 300.0),),
            ),
            SourceRule(MetricKind.SLEEP_DURATION, (_GARMIN,)),
            SourceRule(
                MetricKind.SLEEP_SCORE,
                (_GARMIN,),
                (ProviderBounds(_GARMIN, 0.0, 100.0),),
            ),
            SourceRule(MetricKind.READINESS, (_GARMIN,)),
            # Thresholds (athlete decision 2026-11-07): Garmin's auto-detected
            # values, Wahoo power zones last for FTP. A locally confirmed zone
            # configuration precedes every provider (``resolve_candidates``).
            # Values age with their observed day.
            SourceRule(
                MetricKind.FTP,
                (_GARMIN, _WAHOO),
                (
                    ProviderBounds(_GARMIN, 50.0, 700.0),
                    ProviderBounds(_WAHOO, 50.0, 700.0),
                ),
                max_age=(
                    ProviderMaxAge(_GARMIN, GARMIN_THRESHOLD_MAX_AGE_DAYS),
                    ProviderMaxAge(_WAHOO, WAHOO_CURRENT_MAX_AGE_DAYS),
                ),
            ),
            SourceRule(
                MetricKind.THRESHOLD_HR,
                (_GARMIN,),
                (ProviderBounds(_GARMIN, 80.0, 230.0),),
                max_age=_THRESHOLD_MAX_AGE,
            ),
            SourceRule(
                MetricKind.THRESHOLD_PACE, (_GARMIN,), max_age=_THRESHOLD_MAX_AGE
            ),
            SourceRule(
                MetricKind.MAX_HR,
                (_GARMIN,),
                (ProviderBounds(_GARMIN, 80.0, 260.0),),
                max_age=_THRESHOLD_MAX_AGE,
            ),
            SourceRule(
                MetricKind.VO2MAX, (_GARMIN,), (ProviderBounds(_GARMIN, 20.0, 100.0),)
            ),
        )
    }
)

# Rules for select_daily: the current rules' order and bounds.
DAILY_RULES: Final[Mapping[MetricKind, SourceRule]] = MappingProxyType(
    {
        kind: SourceRule(kind, CURRENT_RULES[kind].order, CURRENT_RULES[kind].bounds)
        for kind in (
            MetricKind.SLEEP_DURATION,
            MetricKind.SLEEP_SCORE,
            MetricKind.HRV_RMSSD,
            MetricKind.RESTING_HR,
            MetricKind.READINESS,
        )
    }
)

# The athlete's preferred source per metric group (#1668), a local profile setting.
# Each group lists its kinds and the providers the athlete may prefer for it; a
# stored value of another provider (such as "intervals") is ignored. Only groups
# where a preference changes the result have one (athlete decision 2026-11-11,
# #2084): Garmin already leads thresholds, HRV, resting HR and sleep, so their
# stored profile values are kept but read nowhere. "body" makes Garmin win over
# a newer local or Wahoo measurement.
PREFERENCE_GROUPS: Final[
    Mapping[str, tuple[frozenset[MetricKind], tuple[ProviderId, ...]]]
] = MappingProxyType(
    {
        "body": (
            frozenset({MetricKind.WEIGHT, MetricKind.BODY_FAT}),
            (_GARMIN,),
        ),
    }
)
# Profile field of each group's preference; an empty value keeps the default order.
PREFERENCE_PROFILE_FIELDS: Final[Mapping[str, str]] = MappingProxyType(
    {group: f"preferred_source_{group}" for group in PREFERENCE_GROUPS}
)
type SourcePreferences = Mapping[str, ProviderId]
NO_PREFERENCES: Final[SourcePreferences] = MappingProxyType({})


def preferences_from_profile(profile: Mapping[str, Any]) -> SourcePreferences:
    """Return the valid preferred sources of a profile; others are ignored."""
    result: dict[str, ProviderId] = {}
    for group, field_name in PREFERENCE_PROFILE_FIELDS.items():
        raw = profile.get(field_name)
        allowed = {provider.value: provider for provider in PREFERENCE_GROUPS[group][1]}
        if isinstance(raw, str) and raw in allowed:
            result[group] = allowed[raw]
    return MappingProxyType(result)


def preferred_source(
    kind: MetricKind, preferences: SourcePreferences
) -> ProviderId | None:
    """Return the athlete's preferred provider for ``kind``'s group, if any."""
    for group, (kinds, _) in PREFERENCE_GROUPS.items():
        if kind in kinds:
            return preferences.get(group)
    return None


def _preferred_first(
    order: tuple[Source, ...], kind: MetricKind, preferences: SourcePreferences
) -> tuple[Source, ...]:
    """Move the preferred provider to the front, behind a leading local value.

    A local value elsewhere in the order (the undated profile weight) keeps its
    place among the rest.
    """
    preferred = preferred_source(kind, preferences)
    if preferred is None or preferred not in order:
        return order
    lead: tuple[Source, ...] = (None,) if order and order[0] is None else ()
    rest = tuple(item for item in order[len(lead) :] if item is not preferred)
    return (*lead, preferred, *rest)


def _preferred_providers(
    order: tuple[ProviderId, ...], kind: MetricKind, preferences: SourcePreferences
) -> tuple[ProviderId, ...]:
    return tuple(
        item for item in _preferred_first(order, kind, preferences) if item is not None
    )


# Days, ending on the latest day read, of recovery history every reader uses.
FAMILY_LOOKBACK_DAYS: Final = 84

_SPORT_SCOPED: Final[frozenset[MetricKind]] = frozenset(
    {
        MetricKind.FTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.THRESHOLD_PACE,
        MetricKind.MAX_HR,
        MetricKind.VO2MAX,
    }
)

type _Rank = tuple[date, datetime, int]


def _current_rank(index: int, observation: Observation, kind: MetricKind) -> _Rank:
    """Rank within one provider; a larger rank wins.

    The tie key is the input position: the last Garmin record wins, and the first
    record of any other provider wins.
    """
    day = _NO_DATE if kind in _SPORT_SCOPED else observation.observed_on
    moment = (
        (observation.observed_at or _EARLIEST)
        if kind is MetricKind.WEIGHT
        else _EARLIEST
    )
    tie = index if observation.provenance.provider is _GARMIN else -index
    return (day, moment, tie)


def within_current_bounds(observation: Observation) -> bool:
    """Return True when the observation passes its kind's current-rule bounds.

    Averages of the current values use this so they skip the same implausible
    days the current selection skips. Kinds without a rule have no bounds.
    """
    rule = CURRENT_RULES.get(observation.kind)
    return rule is None or _within_bounds(observation, rule)


def _within_bounds(observation: Observation, rule: SourceRule) -> bool:
    provider = observation.provenance.provider
    value = observation.value.value
    return all(
        bound.lower <= value <= bound.upper
        for bound in rule.bounds
        if bound.provider is provider
    )


def _within_max_age(
    observation: Observation, rule: SourceRule, as_of: date | None
) -> bool:
    """Return False for a value older than its provider's limit before ``as_of``."""
    if as_of is None:
        return True
    provider = observation.provenance.provider
    age_days = (as_of - observation.observed_on).days
    return all(
        age_days <= limit.days for limit in rule.max_age if limit.provider is provider
    )


def _eligible(
    observations: Iterable[Observation],
    kind: MetricKind,
    rule: SourceRule,
    sport: Sport | None,
    as_of: date | None,
) -> list[tuple[int, Observation]]:
    return [
        (index, observation)
        for index, observation in enumerate(observations)
        if observation.kind is kind
        and observation.provenance.provider in rule.order
        and (sport is None or observation.sport is sport)
        and _within_bounds(observation, rule)
        and _within_max_age(observation, rule, as_of)
    ]


def _provider_best(
    candidates: Iterable[tuple[int, Observation]],
    provider: ProviderId,
    kind: MetricKind,
) -> Observation | None:
    """Return ``provider``'s highest-ranked candidate, or None."""
    ranked = [
        (_current_rank(index, observation, kind), observation)
        for index, observation in candidates
        if observation.provenance.provider is provider
    ]
    return max(ranked, key=lambda item: item[0], default=(None, None))[1]


def select_current(
    observations: Iterable[Observation],
    kind: MetricKind,
    *,
    sport: Sport | None = None,
    as_of: date | None = None,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> Observation | None:
    """Return the current observation for ``kind`` under its source rule.

    ``preferences`` is the athlete's preferred source per metric group.

    ``sport`` restricts the candidates to observations for that sport. Sport-scoped
    kinds require a sport, because legacy readers always select per sport; passing
    None for them raises ValueError rather than mixing sports by input order.

    ``as_of`` is the athlete-local day the value must be current on. Age limits of
    the rule (Wahoo FTP and weight) apply only when it is given, so a caller that
    has the day must pass it. None applies no age limit.

    Unknown kinds return None.
    """
    rule = CURRENT_RULES.get(kind)
    if rule is None:
        return None
    if sport is None and kind in _SPORT_SCOPED:
        raise ValueError(f"{kind.value} is sport-scoped and needs a sport")
    observations = tuple(observations)
    providers = _preferred_providers(rule.order, kind, preferences)
    candidates = _eligible(observations, kind, rule, sport, as_of)
    bests = [
        best
        for provider in providers
        if (best := _provider_best(candidates, provider, kind)) is not None
    ]
    return bests[0] if bests else None


def select_daily(
    observations: Iterable[Observation],
    kind: MetricKind,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> Mapping[date, Observation]:
    """Return the per-day observation for ``kind`` under its daily rule.

    Within a day and provider, the first input record wins, as the planning
    overwrite does. Values outside the rule's bounds and providers outside the
    rule's order are skipped. Days without any
    eligible observation are absent. Unknown kinds return an empty mapping.
    """
    rule = DAILY_RULES.get(kind)
    if rule is None:
        return {}
    observations = tuple(observations)
    providers = _preferred_providers(rule.order, kind, preferences)
    first_by_day: dict[tuple[date, ProviderId], Observation] = {}
    for observation in observations:
        provider = observation.provenance.provider
        if (
            observation.kind is not kind
            or provider is None
            or provider not in providers
            or not _within_bounds(observation, rule)
        ):
            continue
        first_by_day.setdefault((observation.observed_on, provider), observation)
    # Visit days in order and, within a day, providers in precedence order; the
    # first observation seen for a day is the one from the highest-priority one.
    priority = {provider: position for position, provider in enumerate(providers)}
    result: dict[date, Observation] = {}
    for (day, provider), observation in sorted(
        first_by_day.items(), key=lambda item: (item[0][0], priority[item[0][1]])
    ):
        result.setdefault(day, observation)
    return result


# Kinds whose locally confirmed value (a zone configuration) precedes every provider.
LOCAL_FIRST_KINDS: Final[frozenset[MetricKind]] = frozenset(
    {
        MetricKind.FTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.THRESHOLD_PACE,
        MetricKind.MAX_HR,
    }
)
# Sport-specific provider orders. Run threshold power is auto-detected by Garmin
# like the other run thresholds; Wahoo has only cycling power zones.
SPORT_ORDERS: Final[Mapping[tuple[MetricKind, Sport], tuple[ProviderId, ...]]] = (
    MappingProxyType({(MetricKind.FTP, Sport.RUN): (_GARMIN,)})
)
# Weight and body fat (athlete decision 2026-11-04): the most recent measurement
# across sources wins; within ``RECENCY_TIE_DAYS`` of the newest one, a device
# measurement precedes a provider report, which precedes an athlete entry. Undated
# values (the local profile, Wahoo's profile weight) are only fallbacks, in this
# order. None stands for the local profile value.
RECENCY_ORDERS: Final[Mapping[MetricKind, tuple[ProviderId | None, ...]]] = (
    MappingProxyType(
        {
            MetricKind.WEIGHT: (_GARMIN, None, _WAHOO),
            MetricKind.BODY_FAT: (_GARMIN, None),
        }
    )
)
RECENCY_TIE_DAYS: Final = 1
_MEASUREMENT_RANK: Final[Mapping[SourceKind, int]] = MappingProxyType(
    {SourceKind.DEVICE_MEASURED: 0, SourceKind.PROVIDER_REPORTED: 1}
)
# Relative difference above which two sources' current values are a conflict.
CONFLICT_TOLERANCE: Final[Mapping[MetricKind, float]] = MappingProxyType(
    dict.fromkeys(LOCAL_FIRST_KINDS, 0.03)
)
# Absolute difference above which two current values are a conflict.
ABSOLUTE_CONFLICT_TOLERANCE: Final[Mapping[MetricKind, float]] = MappingProxyType(
    {MetricKind.WEIGHT: 1.5, MetricKind.BODY_FAT: 2.0}
)

# None stands for the athlete's own, locally confirmed value.
type Source = ProviderId | None


@dataclass(frozen=True, slots=True)
class Candidate:
    """One source's current value of a metric, as the caller has selected it.

    ``observed_on`` is the day the value was observed or synced; None skips the
    age limit. ``observation`` is the canonical record behind it, if any.
    """

    source: Source
    value: float
    observed_on: date | None = None
    observation: Observation | None = None


@dataclass(frozen=True, slots=True)
class Resolved:
    """The winning value, the other sources' current values and a conflict flag."""

    winner: Candidate
    alternatives: tuple[Candidate, ...]
    conflict: bool


def source_order(
    kind: MetricKind,
    sport: Sport | None = None,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> tuple[Source, ...]:
    """Return the sources of ``kind`` in precedence order; empty without a rule.

    The athlete's preferred provider of the kind's group comes first, behind a
    locally confirmed value.
    """
    rule = CURRENT_RULES.get(kind)
    if rule is None:
        return ()
    if kind in RECENCY_ORDERS:
        return _preferred_first(RECENCY_ORDERS[kind], kind, preferences)
    order = SPORT_ORDERS.get((kind, sport), rule.order) if sport else rule.order
    full = (None, *order) if kind in LOCAL_FIRST_KINDS else order
    return _preferred_first(full, kind, preferences)


def preferred_provider(
    kind: MetricKind, preferences: SourcePreferences = NO_PREFERENCES
) -> ProviderId | None:
    """Return the provider displays prefer: the athlete's, else the rule's first."""
    rule = CURRENT_RULES.get(kind)
    if rule is None:
        return None
    return preferred_source(kind, preferences) or rule.order[0]


def _candidate_current(
    candidate: Candidate, rule: SourceRule, as_of: date | None
) -> bool:
    provider = candidate.source
    if provider is None:
        return True
    within = all(
        bound.lower <= candidate.value <= bound.upper
        for bound in rule.bounds
        if bound.provider is provider
    )
    if not within or as_of is None or candidate.observed_on is None:
        return within
    age_days = (as_of - candidate.observed_on).days
    return all(
        age_days <= limit.days for limit in rule.max_age if limit.provider is provider
    )


def resolve_candidates(
    kind: MetricKind,
    candidates: Iterable[Candidate],
    *,
    as_of: date | None,
    sport: Sport | None = None,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> Resolved | None:
    """Resolve one metric from each source's own current value under its rule.

    ``preferences`` puts the athlete's preferred provider first (``source_order``);
    for ``RECENCY_ORDERS`` kinds its value wins over a newer one of another source.

    The first candidate of each source counts. Candidates outside their source's
    bounds or age limit (on ``as_of``; None applies none) are dropped. The first
    remaining source in ``source_order`` wins; the others stay as alternatives in
    that order. ``RECENCY_ORDERS`` kinds rank by recency instead (``_by_recency``).
    A conflict is an alternative that differs from the winner by more than the
    kind's ``CONFLICT_TOLERANCE`` or ``ABSOLUTE_CONFLICT_TOLERANCE``. ``sport``
    selects a ``SPORT_ORDERS`` entry. None without any current candidate.
    """
    rule = CURRENT_RULES.get(kind)
    if rule is None:
        return None
    order = source_order(kind, sport, preferences)
    first: dict[Source, Candidate] = {}
    for candidate in candidates:
        if candidate.source in order and _candidate_current(candidate, rule, as_of):
            first.setdefault(candidate.source, candidate)
    ranked = [first[source] for source in order if source in first]
    if kind in RECENCY_ORDERS:
        preferred = preferred_source(kind, preferences)
        ranked = _by_recency(ranked)
        ranked.sort(key=lambda item: item.source is not preferred or preferred is None)
    if not ranked:
        return None
    winner, *alternatives = ranked
    return Resolved(winner, tuple(alternatives), _conflict(kind, winner, alternatives))


def _conflict(
    kind: MetricKind, winner: Candidate, alternatives: Iterable[Candidate]
) -> bool:
    relative = CONFLICT_TOLERANCE.get(kind)
    absolute = ABSOLUTE_CONFLICT_TOLERANCE.get(kind)
    if relative is not None:
        allowed = relative * abs(winner.value)
    elif absolute is not None:
        allowed = absolute
    else:
        return False
    return any(abs(item.value - winner.value) > allowed for item in alternatives)


def _measurement_rank(candidate: Candidate) -> int:
    """Device measurement 0, provider report 1, athlete entry or local value 2."""
    if candidate.source is None or candidate.observation is None:
        return 2
    return _MEASUREMENT_RANK.get(candidate.observation.provenance.source_kind, 2)


def _by_recency(ranked: list[Candidate]) -> list[Candidate]:
    """Order dated candidates by recency and measurement kind, undated ones last.

    ``ranked`` is in source order, which breaks the remaining ties.
    """
    days = [item.observed_on for item in ranked if item.observed_on is not None]
    if not days:
        return ranked
    newest = max(days)

    def key(position: int) -> tuple[int, int, int, int]:
        item = ranked[position]
        if item.observed_on is None:
            return (2, 0, 0, position)
        recent = (newest - item.observed_on).days <= RECENCY_TIE_DAYS
        rank = _measurement_rank(item) if recent else 0
        return (0 if recent else 1, rank, -item.observed_on.toordinal(), position)

    return [ranked[position] for position in sorted(range(len(ranked)), key=key)]
