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
Daily rules have no bounds.

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
_WAHOO: Final = ProviderId.WAHOO
_EARLIEST: Final = datetime.min.replace(tzinfo=UTC)
_NO_DATE: Final = date.min
# A Wahoo FTP or weight observed longer ago than this is history, not the current value.
WAHOO_CURRENT_MAX_AGE_DAYS: Final = 90


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
            SourceRule(MetricKind.BODY_FAT, (_INTERVALS,), latest_intervals_row=True),
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
            # current_metrics: Garmin before Intervals sportSettings, per sport. Wahoo
            # power zones are the last resort, with the same plausibility band.
            SourceRule(
                MetricKind.FTP,
                (_GARMIN, _INTERVALS, _WAHOO),
                (
                    ProviderBounds(_GARMIN, 50.0, 700.0),
                    ProviderBounds(_WAHOO, 50.0, 700.0),
                ),
                max_age=(ProviderMaxAge(_WAHOO, WAHOO_CURRENT_MAX_AGE_DAYS),),
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
            SourceRule(MetricKind.CTL, (_INTERVALS,), latest_intervals_row=True),
            SourceRule(MetricKind.ATL, (_INTERVALS,), latest_intervals_row=True),
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
    candidates = _eligible(observations, kind, rule, sport, latest_wellness_day, as_of)
    for provider in rule.order:
        best: tuple[_Rank, Observation] | None = None
        for index, observation in candidates:
            if observation.provenance.provider is not provider:
                continue
            rank = _current_rank(index, observation, kind)
            if best is None or rank > best[0]:
                best = (rank, observation)
        if best is not None:
            return best[1]
    return None


def select_daily(
    observations: Iterable[Observation], kind: MetricKind
) -> Mapping[date, Observation]:
    """Return the per-day observation for ``kind`` under its daily rule.

    Within a day and provider, the first input record wins, as the planning
    overwrite does. Days without any eligible observation are absent. Unknown
    kinds return an empty mapping.
    """
    rule = DAILY_RULES.get(kind)
    if rule is None:
        return {}
    first_by_day: dict[tuple[date, ProviderId], Observation] = {}
    for observation in observations:
        provider = observation.provenance.provider
        if (
            observation.kind is not kind
            or provider is None
            or provider not in rule.order
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
