"""Source precedence for canonical observations.

Pure, table-driven rules that decide which provider's observation is the current
or per-day value for a metric. The tables reproduce the precedence of the legacy
readers in ``backend.performance``:

* ``current_metrics`` (weight, body fat, thresholds, max HR, VO2max),
* ``recovery_context`` and ``recovery`` (sleep, resting HR, HRV, readiness),
* ``load_context`` (CTL and ATL),
* ``planning_recovery`` (the date-indexed planning view).

Selection, for ``select_current``: observations are filtered by kind, by the
optional sport and by the rule's per-provider bounds. Intervals wellness-derived
kinds are further limited to the newest wellness row, given by the caller as
``latest_wellness_day``, because legacy readers never look past that row. The
first provider in the rule's order that still has an observation wins.

Within a provider, ``select_current`` ranks as the legacy readers do:

* weight: newest ``observed_on``, then ``observed_at`` (missing is oldest), then
  the last input record;
* other dated kinds: newest ``observed_on``, then the last Garmin input record;
* sport-scoped kinds (FTP, thresholds, max HR, VO2max): dates are ignored, the
  last Garmin input record wins, and the first Intervals sport setting wins.
* Intervals athlete-level values (weight from the athlete record) carry the
  athlete id rather than a wellness day. They are exempt from the latest-row
  restriction and rank below any dated observation, so the latest wellness value
  wins and the athlete value is the fallback, as the ``current_metrics`` chain.

For ``select_daily``, each calendar day independently takes the first provider in
the rule's order that has an observation that day. Within a provider the first
input record wins and timestamps are ignored, matching the planning overwrite.
Daily rules apply the current rules' bounds.

Sleep, HRV and resting HR are one method family in both selections
(``family_providers``): Garmin's night values, with Intervals only when it relays
Garmin's values (``intervals_relays_garmin``), so a different method never fills
in silently. Weight and body fat are resolved by recency (``RECENCY_ORDERS``).

Wahoo is the lowest-priority provider for current FTP and weight: it follows
Garmin and Intervals, and it ranks after them in both rules. Its FTP is the newest
stored cycling zone set, and its weight is the newest stored profile weight. When
the caller passes ``as_of`` (the athlete-local day), a Wahoo value observed more
than ``WAHOO_CURRENT_MAX_AGE_DAYS`` days before it is not current. Such values stay
in the observations, so history keeps them.

Values that this module does not see, and must stay with the caller: profile and
manual values, per-sport settings from the wellness row, Intervals eFTP, the
generic top-level FTP and threshold-HR fallbacks, and activity-derived fallbacks
such as the maximum recorded heart rate.

The one mapper gap still open is pinned by a named test in
``tests/test_source_policy.py``: Garmin cycling FTP history is observed, but the
legacy current FTP reads only the cycling FTP section. Garmin sleep score 0 and
Garmin heart-rate-zone max HR, athlete-level weight, athlete-wide threshold HR and
max HR, and sport-setting VO2max are mapped and covered by parity tests.

Thresholds (FTP, threshold and maximum heart rate, threshold pace) are resolved
with ``resolve_candidates`` from each source's own current value: a locally
confirmed zone configuration first, then the providers in rule order
(``SPORT_ORDERS`` overrides it per sport), within each provider's bounds and age
limits. The result keeps the other sources as alternatives with a conflict flag,
so the Coach context, current metrics and plans read one value.

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
from backend.canonical.vocabulary import MetricKind, ProviderId, SourceKind, Sport

_GARMIN: Final = ProviderId.GARMIN
_INTERVALS: Final = ProviderId.INTERVALS
_WAHOO: Final = ProviderId.WAHOO
_EARLIEST: Final = datetime.min.replace(tzinfo=UTC)
_NO_DATE: Final = date.min
# A Wahoo FTP or weight observed longer ago than this is history, not the current value.
WAHOO_CURRENT_MAX_AGE_DAYS: Final = 90
# An Intervals threshold counts only from a sync at most this many days old.
INTERVALS_THRESHOLD_MAX_AGE_DAYS: Final = 30
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
    """Provider order, optional bounds and age limits, and Intervals latest-row only."""

    kind: MetricKind
    order: tuple[ProviderId, ...]
    bounds: tuple[ProviderBounds, ...] = ()
    latest_intervals_row: bool = False
    max_age: tuple[ProviderMaxAge, ...] = ()


_THRESHOLD_MAX_AGE: Final = (
    ProviderMaxAge(_INTERVALS, INTERVALS_THRESHOLD_MAX_AGE_DAYS),
    ProviderMaxAge(_GARMIN, GARMIN_THRESHOLD_MAX_AGE_DAYS),
)

# Rules for select_current. A provider absent from ``order`` never supplies the kind.
CURRENT_RULES: Final[Mapping[MetricKind, SourceRule]] = MappingProxyType(
    {
        rule.kind: rule
        for rule in (
            # current_metrics: Garmin's newest weight wins even when older than the
            # Intervals wellness row. Body fat ignores Garmin entirely. Wahoo, which
            # has no wellness row, is the last resort for weight.
            SourceRule(
                MetricKind.WEIGHT,
                (_GARMIN, _INTERVALS, _WAHOO),
                latest_intervals_row=True,
                max_age=(ProviderMaxAge(_WAHOO, WAHOO_CURRENT_MAX_AGE_DAYS),),
            ),
            SourceRule(
                MetricKind.BODY_FAT, (_GARMIN, _INTERVALS), latest_intervals_row=True
            ),
            # recovery_context: newest in-bounds Garmin value, else Intervals latest.
            SourceRule(
                MetricKind.RESTING_HR,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 30.0, 230.0),),
                latest_intervals_row=True,
            ),
            SourceRule(
                MetricKind.HRV_RMSSD,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 1.0, 300.0),),
                latest_intervals_row=True,
            ),
            # Garmin's weekly HRV average: only a labelled fallback for RMSSD.
            SourceRule(
                MetricKind.HRV_WEEKLY_AVERAGE,
                (_GARMIN,),
                (ProviderBounds(_GARMIN, 1.0, 300.0),),
            ),
            # Sleep duration and score: Garmin before Intervals. Readiness: the reverse.
            SourceRule(
                MetricKind.SLEEP_DURATION,
                (_GARMIN, _INTERVALS),
                latest_intervals_row=True,
            ),
            SourceRule(
                MetricKind.SLEEP_SCORE,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 0.0, 100.0),),
                latest_intervals_row=True,
            ),
            SourceRule(
                MetricKind.READINESS,
                (_INTERVALS, _GARMIN),
                latest_intervals_row=True,
            ),
            # Thresholds (athlete decision 2026-11-04): the athlete-maintained
            # Intervals FTP before Garmin's auto-detected FTP, Wahoo power zones last.
            # Garmin's auto-detected heart-rate and pace thresholds before the
            # manually kept Intervals values. A locally confirmed zone configuration
            # precedes every provider (``resolve_candidates``). Intervals values age
            # with their sync, Garmin and Wahoo values with their observed day.
            SourceRule(
                MetricKind.FTP,
                (_INTERVALS, _GARMIN, _WAHOO),
                (
                    ProviderBounds(_GARMIN, 50.0, 700.0),
                    ProviderBounds(_WAHOO, 50.0, 700.0),
                ),
                max_age=(
                    ProviderMaxAge(_INTERVALS, INTERVALS_THRESHOLD_MAX_AGE_DAYS),
                    ProviderMaxAge(_GARMIN, GARMIN_THRESHOLD_MAX_AGE_DAYS),
                    ProviderMaxAge(_WAHOO, WAHOO_CURRENT_MAX_AGE_DAYS),
                ),
            ),
            SourceRule(
                MetricKind.THRESHOLD_HR,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 80.0, 230.0),),
                max_age=_THRESHOLD_MAX_AGE,
            ),
            SourceRule(
                MetricKind.THRESHOLD_PACE,
                (_GARMIN, _INTERVALS),
                max_age=_THRESHOLD_MAX_AGE,
            ),
            SourceRule(
                MetricKind.MAX_HR,
                (_GARMIN, _INTERVALS),
                (
                    ProviderBounds(_GARMIN, 80.0, 260.0),
                    ProviderBounds(_INTERVALS, 80.0, 260.0),
                ),
                max_age=_THRESHOLD_MAX_AGE,
            ),
            SourceRule(
                MetricKind.VO2MAX,
                (_GARMIN, _INTERVALS),
                (ProviderBounds(_GARMIN, 20.0, 100.0),),
            ),
            # load_context: Intervals only, latest row.
            SourceRule(MetricKind.CTL, (_INTERVALS,), latest_intervals_row=True),
            SourceRule(MetricKind.ATL, (_INTERVALS,), latest_intervals_row=True),
            # Intervals' estimated FTP: a separate, labelled value, never the FTP.
            SourceRule(MetricKind.EFTP, (_INTERVALS,)),
        )
    }
)

# Rules for select_daily: the current rules' order and bounds. Sleep, HRV and
# resting HR keep their method family per day (``family_providers``). Readiness
# comes from Intervals, and Garmin only fills the days that Intervals leaves empty.
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

# HRV, resting HR and sleep (athlete decision 2026-11-04): one method family,
# Garmin's night values by default, never a silent fallback to another method.
# Intervals wellness rows do not say where a value came from, so Intervals counts
# as Garmin's family only as a relay: its value equals Garmin's (within the kind's
# rounding) on at least ``RELAY_SHARE`` of at least ``RELAY_MIN_OVERLAP_DAYS``
# days with both. Without any Garmin value, Intervals is the only family present.
METHOD_FAMILY_KINDS: Final[frozenset[MetricKind]] = frozenset(
    {
        MetricKind.SLEEP_DURATION,
        MetricKind.SLEEP_SCORE,
        MetricKind.RESTING_HR,
        MetricKind.HRV_RMSSD,
    }
)
RELAY_SHARE: Final = 0.9
# Days, ending on the latest day read, over which every reader decides the family.
FAMILY_LOOKBACK_DAYS: Final = 84
RELAY_MIN_OVERLAP_DAYS: Final = 5
_RELAY_TOLERANCE: Final[Mapping[MetricKind, float]] = MappingProxyType(
    {
        MetricKind.SLEEP_DURATION: 60.0,
        MetricKind.SLEEP_SCORE: 1.0,
        MetricKind.RESTING_HR: 1.0,
        MetricKind.HRV_RMSSD: 1.0,
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

type _Rank = tuple[date, datetime, int]


def _is_athlete_level(observation: Observation) -> bool:
    """Return True for Intervals values taken from the athlete record.

    Wellness observations use their ``YYYY-MM-DD`` row id, so an Intervals
    observation whose record id is not its own ISO day comes from the athlete
    record (or has no record id). Known limit: an athlete id that is itself an ISO
    date would be misread as a wellness value. Intervals athlete ids are not dates.
    """
    if observation.provenance.provider is not _INTERVALS:
        return False
    return (
        observation.provenance.source_record_id != observation.observed_on.isoformat()
    )


def _current_rank(index: int, observation: Observation, kind: MetricKind) -> _Rank:
    """Rank within one provider; a larger rank wins.

    The tie key is the input position: the last Garmin record wins, and the first
    Intervals record wins. Athlete-level values rank below any dated value.
    """
    undated = kind in _SPORT_SCOPED or _is_athlete_level(observation)
    day = _NO_DATE if undated else observation.observed_on
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


def _within_latest_row(
    observation: Observation, rule: SourceRule, latest_wellness_day: date | None
) -> bool:
    if not rule.latest_intervals_row or latest_wellness_day is None:
        return True
    if observation.provenance.provider is not _INTERVALS or _is_athlete_level(
        observation
    ):
        return True
    return observation.observed_on == latest_wellness_day


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
    latest_wellness_day: date | None,
    as_of: date | None,
) -> list[tuple[int, Observation]]:
    return [
        (index, observation)
        for index, observation in enumerate(observations)
        if observation.kind is kind
        and observation.provenance.provider in rule.order
        and (sport is None or observation.sport is sport)
        and _within_bounds(observation, rule)
        and _within_latest_row(observation, rule, latest_wellness_day)
        and _within_max_age(observation, rule, as_of)
    ]


def select_current(
    observations: Iterable[Observation],
    kind: MetricKind,
    *,
    sport: Sport | None = None,
    latest_wellness_day: date | None = None,
    as_of: date | None = None,
) -> Observation | None:
    """Return the current observation for ``kind`` under its source rule.

    ``sport`` restricts the candidates to observations for that sport. Sport-scoped
    kinds require a sport, because legacy readers always select per sport; passing
    None for them raises ValueError rather than mixing sports by input order.

    ``latest_wellness_day`` is the newest Intervals wellness row date, as the
    caller sees it. For wellness-derived kinds, Intervals observations count only
    on that day; a newest row that lacks the field yields no Intervals value. None
    applies no restriction and is correct when the snapshot has no wellness rows.

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
    providers = family_providers(observations, kind)
    candidates = _eligible(observations, kind, rule, sport, latest_wellness_day, as_of)
    bests: list[Observation] = []
    for provider in providers:
        best: tuple[_Rank, Observation] | None = None
        for index, observation in candidates:
            if observation.provenance.provider is not provider:
                continue
            rank = _current_rank(index, observation, kind)
            if best is None or rank > best[0]:
                best = (rank, observation)
        if best is not None:
            bests.append(best[1])
    if kind in METHOD_FAMILY_KINDS:
        # A relay is the same measurement: its newer day wins, a tie keeps Garmin.
        return max(bests, key=lambda item: item.observed_on, default=None)
    return bests[0] if bests else None


def select_daily(
    observations: Iterable[Observation], kind: MetricKind
) -> Mapping[date, Observation]:
    """Return the per-day observation for ``kind`` under its daily rule.

    Within a day and provider, the first input record wins, as the planning
    overwrite does. Values outside the rule's bounds and providers outside the
    kind's method family (``family_providers``) are skipped. Days without any
    eligible observation are absent. Unknown kinds return an empty mapping.
    """
    rule = DAILY_RULES.get(kind)
    if rule is None:
        return {}
    observations = tuple(observations)
    providers = family_providers(observations, kind)
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
    # Visit days in order and, within a day, providers in rule order; the first
    # observation seen for a day is the one from the highest-priority provider.
    priority = {provider: position for position, provider in enumerate(rule.order)}
    result: dict[date, Observation] = {}
    for (day, provider), observation in sorted(
        first_by_day.items(), key=lambda item: (item[0][0], priority[item[0][1]])
    ):
        result.setdefault(day, observation)
    return result


def _first_daily_values(
    observations: Iterable[Observation], kind: MetricKind, provider: ProviderId
) -> dict[date, float]:
    days: dict[date, float] = {}
    for observation in observations:
        if (
            observation.kind is kind
            and observation.provenance.provider is provider
            and within_current_bounds(observation)
        ):
            days.setdefault(observation.observed_on, float(observation.value.value))
    return days


def intervals_relays_garmin(
    observations: Iterable[Observation], kind: MetricKind
) -> bool:
    """Return True when the Intervals values of ``kind`` relay Garmin's values.

    Each provider's first in-bounds value per day is compared on the days both
    have; at least ``RELAY_MIN_OVERLAP_DAYS`` such days are needed, and at least
    ``RELAY_SHARE`` of them must agree within the kind's rounding tolerance.
    """
    tolerance = _RELAY_TOLERANCE.get(kind)
    if tolerance is None:
        return False
    observations = tuple(observations)
    garmin = _first_daily_values(observations, kind, _GARMIN)
    intervals = _first_daily_values(observations, kind, _INTERVALS)
    days = garmin.keys() & intervals.keys()
    if len(days) < RELAY_MIN_OVERLAP_DAYS:
        return False
    agreeing = sum(abs(garmin[day] - intervals[day]) <= tolerance for day in days)
    return agreeing >= RELAY_SHARE * len(days)


def family_providers(
    observations: Iterable[Observation], kind: MetricKind
) -> tuple[ProviderId, ...]:
    """Return the providers that may supply ``kind``, in precedence order.

    Kinds outside ``METHOD_FAMILY_KINDS`` use their current rule's order. Method
    family kinds use Garmin's values when there is any in-bounds Garmin value,
    together with Intervals only when Intervals relays Garmin; otherwise the
    Intervals values are the only family present.
    """
    rule = CURRENT_RULES.get(kind)
    if rule is None:
        return ()
    if kind not in METHOD_FAMILY_KINDS:
        return rule.order
    observations = tuple(observations)
    if not _first_daily_values(observations, kind, _GARMIN):
        return (_INTERVALS,)
    if intervals_relays_garmin(observations, kind):
        return (_GARMIN, _INTERVALS)
    return (_GARMIN,)


# Kinds whose locally confirmed value (a zone configuration) precedes every provider.
LOCAL_FIRST_KINDS: Final[frozenset[MetricKind]] = frozenset(
    {
        MetricKind.FTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.THRESHOLD_PACE,
        MetricKind.MAX_HR,
    }
)
# Sport-specific provider orders. The Intervals-first FTP order is the ride FTP;
# run threshold power is auto-detected by Garmin like the other run thresholds.
SPORT_ORDERS: Final[Mapping[tuple[MetricKind, Sport], tuple[ProviderId, ...]]] = (
    MappingProxyType({(MetricKind.FTP, Sport.RUN): (_GARMIN, _INTERVALS)})
)
# Weight and body fat (athlete decision 2026-11-04): the most recent measurement
# across sources wins; within ``RECENCY_TIE_DAYS`` of the newest one, a device
# measurement precedes a provider report, which precedes an athlete entry. Undated
# values (Intervals athlete record, the local profile, Wahoo's profile weight) are
# only fallbacks, in this order. None stands for the local profile value.
RECENCY_ORDERS: Final[Mapping[MetricKind, tuple[ProviderId | None, ...]]] = (
    MappingProxyType(
        {
            MetricKind.WEIGHT: (_GARMIN, _INTERVALS, None, _WAHOO),
            MetricKind.BODY_FAT: (_GARMIN, _INTERVALS, None),
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


def source_order(kind: MetricKind, sport: Sport | None = None) -> tuple[Source, ...]:
    """Return the sources of ``kind`` in precedence order; empty without a rule."""
    rule = CURRENT_RULES.get(kind)
    if rule is None:
        return ()
    if kind in RECENCY_ORDERS:
        return RECENCY_ORDERS[kind]
    order = SPORT_ORDERS.get((kind, sport), rule.order) if sport else rule.order
    return (None, *order) if kind in LOCAL_FIRST_KINDS else order


def preferred_provider(kind: MetricKind) -> ProviderId | None:
    """Return the first provider of ``kind``'s rule, the one displays prefer."""
    rule = CURRENT_RULES.get(kind)
    return None if rule is None else rule.order[0]


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
) -> Resolved | None:
    """Resolve one metric from each source's own current value under its rule.

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
    order = source_order(kind, sport)
    first: dict[Source, Candidate] = {}
    for candidate in candidates:
        if candidate.source in order and _candidate_current(candidate, rule, as_of):
            first.setdefault(candidate.source, candidate)
    ranked = [first[source] for source in order if source in first]
    if kind in RECENCY_ORDERS:
        ranked = _by_recency(ranked)
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
