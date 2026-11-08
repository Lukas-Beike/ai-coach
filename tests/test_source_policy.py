"""Source precedence rules, checked against the legacy performance readers.

Intervals.icu is never a source (athlete decision 2026-11-07); the tests pin that
its observations are ignored by every rule. The parity classes feed the same raw
provider data to the legacy readers and to the canonical mappers plus
``source_policy``, then compare the chosen values. Named deviation tests pin where
the canonical path intentionally differs from the legacy output.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from canonical_recovery_support import recovery_inputs
from intervals_wellness_stub import (
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)
from performance_day_support import snapshot_metrics

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.garmin_canonical import garmin_body
from backend.performance.recovery_context import performance_recovery_context
from backend.performance.source_policy import (
    CURRENT_RULES,
    DAILY_RULES,
    Candidate,
    preferences_from_profile,
    resolve_candidates,
    select_current,
    select_daily,
    source_order,
)
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.sync.garmin_payload_metrics import garmin_payload_performance_metrics

GARMIN = ProviderId.GARMIN


def current_performance_metrics(snapshot, profile, garmin, **kwargs):
    return snapshot_metrics(snapshot, profile, garmin, **kwargs)


INTERVALS = ProviderId.INTERVALS
BERLIN = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 5, 4)
# The newest Intervals wellness row in WELLNESS_ROWS.
LATEST_DAY = date(2026, 5, 4)
RETRIEVED_AT = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
EARLY = datetime(2026, 5, 4, 6, 0, tzinfo=UTC)
LATE = datetime(2026, 5, 4, 7, 0, tzinfo=UTC)

CURRENT_KINDS = frozenset(
    {
        MetricKind.WEIGHT,
        MetricKind.BODY_FAT,
        MetricKind.RESTING_HR,
        MetricKind.HRV_RMSSD,
        MetricKind.HRV_WEEKLY_AVERAGE,
        MetricKind.SLEEP_DURATION,
        MetricKind.SLEEP_SCORE,
        MetricKind.READINESS,
        MetricKind.FTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.THRESHOLD_PACE,
        MetricKind.MAX_HR,
        MetricKind.VO2MAX,
    }
)
DAILY_KINDS = frozenset(
    {
        MetricKind.SLEEP_DURATION,
        MetricKind.SLEEP_SCORE,
        MetricKind.HRV_RMSSD,
        MetricKind.RESTING_HR,
        MetricKind.READINESS,
    }
)


def _obs(
    kind: MetricKind,
    value: float,
    day: date,
    provider: ProviderId | None = INTERVALS,
    *,
    sport: Sport | None = None,
    observed_at: datetime | None = None,
    record_id: str | None = None,
) -> Observation:
    """Build a valid observation for one provider, or a provider-less one.

    Intervals observations default to their ISO day as record id, as wellness rows
    do. An athlete-record value is modelled by passing an athlete record id.
    """
    if record_id is None and provider is INTERVALS:
        record_id = day.isoformat()
    source_kind = (
        SourceKind.PROVIDER_REPORTED if provider is not None else SourceKind.AI_ESTIMATE
    )
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=day,
        observed_at=observed_at,
        provenance=Provenance(
            provider=provider,
            source_kind=source_kind,
            source_record_id=record_id,
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=RETRIEVED_AT if provider is not None else None,
            label=None,
        ),
        sport=sport,
    )


def _values(observation: Observation | None) -> float | None:
    return None if observation is None else observation.value.value


def _day_values(result: Mapping[date, Observation]) -> dict[date, float]:
    return {day: observation.value.value for day, observation in result.items()}


def _wahoo_ftp(value: float, day: date = LATEST_DAY) -> Observation:
    return _obs(MetricKind.FTP, value, day, ProviderId.WAHOO, sport=Sport.RIDE)


class WahooLowestPriorityTests(unittest.TestCase):
    """Wahoo FTP and weight only ever fill in after Garmin."""

    def test_ftp_and_weight_orders_put_wahoo_last(self) -> None:
        self.assertEqual(
            (GARMIN, ProviderId.WAHOO), CURRENT_RULES[MetricKind.FTP].order
        )
        self.assertEqual(
            (GARMIN, ProviderId.WAHOO), CURRENT_RULES[MetricKind.WEIGHT].order
        )

    def test_no_rule_orders_intervals(self) -> None:
        for table in (CURRENT_RULES, DAILY_RULES):
            for rule in table.values():
                with self.subTest(kind=rule.kind):
                    self.assertNotIn(INTERVALS, rule.order)
                    self.assertFalse(
                        any(item.provider is INTERVALS for item in rule.bounds)
                    )
                    self.assertFalse(
                        any(item.provider is INTERVALS for item in rule.max_age)
                    )

    def test_garmin_ftp_wins_over_intervals_and_wahoo(self) -> None:
        wahoo = _wahoo_ftp(250)
        intervals = _obs(MetricKind.FTP, 240, LATEST_DAY, INTERVALS, sport=Sport.RIDE)
        garmin = _obs(MetricKind.FTP, 302, LATEST_DAY, GARMIN, sport=Sport.RIDE)
        self.assertEqual(
            302,
            _values(
                select_current(
                    [intervals, wahoo, garmin], MetricKind.FTP, sport=Sport.RIDE
                )
            ),
        )
        self.assertEqual(
            250,
            _values(
                select_current([intervals, wahoo], MetricKind.FTP, sport=Sport.RIDE)
            ),
        )
        self.assertIsNone(select_current([intervals], MetricKind.FTP, sport=Sport.RIDE))

    def test_wahoo_ftp_outside_the_bounds_is_not_selected(self) -> None:
        self.assertIsNone(
            select_current([_wahoo_ftp(800)], MetricKind.FTP, sport=Sport.RIDE)
        )

    def test_wahoo_weight_is_used_when_garmin_has_none(self) -> None:
        wahoo_weight = _obs(MetricKind.WEIGHT, 78.5, LATEST_DAY, ProviderId.WAHOO)
        intervals_weight = _obs(MetricKind.WEIGHT, 77.0, LATEST_DAY, INTERVALS)
        self.assertEqual(
            78.5,
            _values(
                select_current([intervals_weight, wahoo_weight], MetricKind.WEIGHT)
            ),
        )
        garmin_weight = _obs(MetricKind.WEIGHT, 80.0, LATEST_DAY, GARMIN)
        self.assertEqual(
            80.0,
            _values(
                select_current(
                    [wahoo_weight, intervals_weight, garmin_weight], MetricKind.WEIGHT
                )
            ),
        )


class WahooAgeLimitTests(unittest.TestCase):
    """A Wahoo FTP or weight older than 90 days is history, not the current value."""

    AS_OF = LATEST_DAY

    def _ftp_days_old(self, days: int, value: float = 250) -> Observation:
        return _wahoo_ftp(value, self.AS_OF - timedelta(days=days))

    def _weight_days_old(self, days: int, value: float = 78.5) -> Observation:
        return _obs(
            MetricKind.WEIGHT,
            value,
            self.AS_OF - timedelta(days=days),
            ProviderId.WAHOO,
        )

    def test_wahoo_ftp_at_89_and_90_days_is_current_but_91_days_is_not(self) -> None:
        for days, expected in ((89, 250), (90, 250), (91, None)):
            with self.subTest(days=days):
                self.assertEqual(
                    expected,
                    _values(
                        select_current(
                            [self._ftp_days_old(days)],
                            MetricKind.FTP,
                            sport=Sport.RIDE,
                            as_of=self.AS_OF,
                        )
                    ),
                )

    def test_wahoo_weight_at_89_days_is_current_but_91_days_is_not(self) -> None:
        self.assertEqual(
            78.5,
            _values(
                select_current(
                    [self._weight_days_old(89)],
                    MetricKind.WEIGHT,
                    as_of=self.AS_OF,
                )
            ),
        )
        self.assertIsNone(
            select_current(
                [self._weight_days_old(91)],
                MetricKind.WEIGHT,
                as_of=self.AS_OF,
            )
        )

    def test_stale_wahoo_value_stays_in_history_and_fresh_garmin_still_wins(
        self,
    ) -> None:
        stale = self._ftp_days_old(120, value=300)
        observations = [
            stale,
            _obs(MetricKind.FTP, 240, LATEST_DAY, GARMIN, sport=Sport.RIDE),
        ]
        self.assertEqual(
            240,
            _values(
                select_current(
                    observations, MetricKind.FTP, sport=Sport.RIDE, as_of=self.AS_OF
                )
            ),
        )
        self.assertIn(stale, observations)
        self.assertIsNone(
            select_current([stale], MetricKind.FTP, sport=Sport.RIDE, as_of=self.AS_OF)
        )

    def test_without_as_of_no_age_limit_applies(self) -> None:
        self.assertEqual(
            250,
            _values(
                select_current(
                    [self._ftp_days_old(400)],
                    MetricKind.FTP,
                    sport=Sport.RIDE,
                )
            ),
        )

    def test_garmin_weight_is_not_age_limited(self) -> None:
        old_garmin_weight = _obs(
            MetricKind.WEIGHT, 80.0, self.AS_OF - timedelta(days=400), GARMIN
        )
        self.assertIs(
            old_garmin_weight,
            select_current([old_garmin_weight], MetricKind.WEIGHT, as_of=self.AS_OF),
        )

    def test_age_limits_cover_wahoo_and_the_thresholds(self) -> None:
        limited = {
            kind: [(limit.provider, limit.days) for limit in rule.max_age]
            for kind, rule in CURRENT_RULES.items()
            if rule.max_age
        }
        self.assertEqual(
            limited,
            {
                MetricKind.FTP: [(GARMIN, 180), (ProviderId.WAHOO, 90)],
                MetricKind.WEIGHT: [(ProviderId.WAHOO, 90)],
                **{
                    kind: [(GARMIN, 180)]
                    for kind in (
                        MetricKind.THRESHOLD_HR,
                        MetricKind.THRESHOLD_PACE,
                        MetricKind.MAX_HR,
                    )
                },
            },
        )


class SourceRuleTableTests(unittest.TestCase):
    def test_current_table_covers_the_legacy_metric_set(self) -> None:
        self.assertEqual(set(CURRENT_RULES), CURRENT_KINDS)

    def test_daily_table_covers_only_the_planning_recovery_kinds(self) -> None:
        self.assertEqual(set(DAILY_RULES), DAILY_KINDS)

    def test_rule_orders_are_non_empty_and_free_of_duplicates(self) -> None:
        for table in (CURRENT_RULES, DAILY_RULES):
            for rule in table.values():
                with self.subTest(kind=rule.kind):
                    self.assertTrue(rule.order)
                    self.assertEqual(len(set(rule.order)), len(rule.order))

    def test_bounds_name_only_providers_in_the_rule_order(self) -> None:
        for rule in CURRENT_RULES.values():
            for bound in rule.bounds:
                with self.subTest(kind=rule.kind):
                    self.assertIn(bound.provider, rule.order)
                    self.assertLessEqual(bound.lower, bound.upper)

    def test_daily_rules_carry_the_current_bounds(self) -> None:
        for kind, rule in DAILY_RULES.items():
            with self.subTest(kind=kind):
                self.assertEqual(rule.bounds, CURRENT_RULES[kind].bounds)
                self.assertEqual(rule.order, CURRENT_RULES[kind].order)

    def test_unknown_or_unlisted_kinds_have_no_rule(self) -> None:
        for kind in (
            MetricKind.HRV_SDNN,
            MetricKind.BODY_BATTERY,
            MetricKind.TRAINING_LOAD,
        ):
            with self.subTest(kind=kind):
                self.assertNotIn(kind, CURRENT_RULES)
                self.assertNotIn(kind, DAILY_RULES)


class CurrentSelectionTests(unittest.TestCase):
    def test_weight_prefers_garmin_even_when_it_is_older(self) -> None:
        garmin_old = _obs(MetricKind.WEIGHT, 80.0, date(2026, 5, 1), GARMIN)
        intervals_new = _obs(MetricKind.WEIGHT, 81.0, TODAY)

        chosen = select_current([intervals_new, garmin_old], MetricKind.WEIGHT)

        self.assertIs(chosen, garmin_old)

    def test_weight_from_intervals_alone_is_none(self) -> None:
        older = _obs(MetricKind.WEIGHT, 80.0, date(2026, 5, 1))
        newer = _obs(MetricKind.WEIGHT, 81.0, TODAY)

        self.assertIsNone(select_current([older, newer], MetricKind.WEIGHT))

    def test_body_fat_reads_garmin_only(self) -> None:
        garmin = _obs(MetricKind.BODY_FAT, 12.0, TODAY, GARMIN)
        intervals = _obs(MetricKind.BODY_FAT, 14.0, date(2026, 5, 1))

        self.assertIs(select_current([garmin, intervals], MetricKind.BODY_FAT), garmin)
        self.assertIsNone(select_current([intervals], MetricKind.BODY_FAT))

    def test_resting_hr_takes_newest_in_bounds_garmin_value(self) -> None:
        older_valid = _obs(MetricKind.RESTING_HR, 50.0, date(2026, 5, 2), GARMIN)
        newest_implausible = _obs(MetricKind.RESTING_HR, 240.0, TODAY, GARMIN)

        chosen = select_current(
            [older_valid, newest_implausible], MetricKind.RESTING_HR
        )

        self.assertIs(chosen, older_valid)

    def test_resting_hr_bounds_are_inclusive_at_30_and_230(self) -> None:
        for value in (30.0, 230.0):
            with self.subTest(value=value):
                observation = _obs(MetricKind.RESTING_HR, value, TODAY, GARMIN)
                self.assertIs(
                    select_current([observation], MetricKind.RESTING_HR), observation
                )

        for value in (29.0, 231.0):
            with self.subTest(value=value):
                garmin = _obs(MetricKind.RESTING_HR, value, TODAY, GARMIN)
                intervals = _obs(MetricKind.RESTING_HR, 55.0, date(2026, 5, 1))
                self.assertIsNone(
                    select_current([garmin, intervals], MetricKind.RESTING_HR)
                )

    def test_hrv_bounds_are_inclusive_for_garmin(self) -> None:
        for value in (1.0, 300.0):
            with self.subTest(value=value):
                garmin = _obs(MetricKind.HRV_RMSSD, value, TODAY, GARMIN)
                self.assertIs(select_current([garmin], MetricKind.HRV_RMSSD), garmin)

        for value in (0.5, 300.5):
            with self.subTest(value=value):
                garmin = _obs(MetricKind.HRV_RMSSD, value, TODAY, GARMIN)
                self.assertIsNone(select_current([garmin], MetricKind.HRV_RMSSD))

    def test_sleep_duration_prefers_garmin_regardless_of_date(self) -> None:
        garmin_old = _obs(MetricKind.SLEEP_DURATION, 28_800.0, date(2026, 5, 1), GARMIN)
        intervals_new = _obs(MetricKind.SLEEP_DURATION, 25_200.0, TODAY)

        self.assertIs(
            select_current([intervals_new, garmin_old], MetricKind.SLEEP_DURATION),
            garmin_old,
        )

    def test_sleep_with_only_intervals_values_is_none(self) -> None:
        duration = _obs(MetricKind.SLEEP_DURATION, 25_200.0, TODAY)
        score = _obs(MetricKind.SLEEP_SCORE, 78.0, TODAY)

        self.assertIsNone(select_current([duration], MetricKind.SLEEP_DURATION))
        self.assertIsNone(select_current([score], MetricKind.SLEEP_SCORE))
        self.assertEqual(select_daily([duration], MetricKind.SLEEP_DURATION), {})

    def test_sleep_score_prefers_in_bounds_garmin(self) -> None:
        garmin = _obs(MetricKind.SLEEP_SCORE, 85.0, TODAY, GARMIN)
        intervals = _obs(MetricKind.SLEEP_SCORE, 78.0, TODAY)

        self.assertIs(
            select_current([intervals, garmin], MetricKind.SLEEP_SCORE), garmin
        )

    def test_readiness_comes_from_garmin_even_when_intervals_is_older(self) -> None:
        intervals_old = _obs(MetricKind.READINESS, 66.0, date(2026, 5, 1))
        garmin_new = _obs(MetricKind.READINESS, 75.0, TODAY, GARMIN)

        self.assertIs(
            select_current([garmin_new, intervals_old], MetricKind.READINESS),
            garmin_new,
        )
        self.assertIsNone(select_current([intervals_old], MetricKind.READINESS))

    def test_sport_specific_ftp_ignores_the_intervals_setting(self) -> None:
        garmin_ride = _obs(MetricKind.FTP, 302.0, TODAY, GARMIN, sport=Sport.RIDE)
        intervals_ride = _obs(MetricKind.FTP, 250.0, TODAY, sport=Sport.RIDE)
        intervals_run = _obs(MetricKind.FTP, 280.0, TODAY, sport=Sport.RUN)
        observations = [intervals_run, intervals_ride, garmin_ride]

        self.assertIs(
            select_current(observations, MetricKind.FTP, sport=Sport.RIDE),
            garmin_ride,
        )
        self.assertIsNone(select_current(observations, MetricKind.FTP, sport=Sport.RUN))

    def test_sport_filter_excludes_other_sports_and_unsported_values(self) -> None:
        run_only = _obs(MetricKind.THRESHOLD_HR, 170.0, TODAY, GARMIN, sport=Sport.RUN)

        self.assertIsNone(
            select_current([run_only], MetricKind.THRESHOLD_HR, sport=Sport.RIDE)
        )
        self.assertIs(
            select_current([run_only], MetricKind.THRESHOLD_HR, sport=Sport.RUN),
            run_only,
        )

    def test_sport_scoped_kinds_refuse_a_sportless_query(self) -> None:
        run_only = _obs(MetricKind.THRESHOLD_HR, 170.0, TODAY, GARMIN, sport=Sport.RUN)

        with self.assertRaises(ValueError):
            select_current([run_only], MetricKind.THRESHOLD_HR, sport=None)
        # Sport-agnostic kinds still accept no sport.
        weight = _obs(MetricKind.WEIGHT, 80.0, TODAY, GARMIN)
        self.assertIs(select_current([weight], MetricKind.WEIGHT), weight)

    def test_garmin_values_outside_legacy_bounds_are_not_selected(self) -> None:
        low_ftp = _obs(MetricKind.FTP, 49.0, TODAY, GARMIN, sport=Sport.RIDE)
        high_ftp = _obs(MetricKind.FTP, 701.0, TODAY, GARMIN, sport=Sport.RIDE)
        wahoo = _wahoo_ftp(250.0)
        high_threshold = _obs(
            MetricKind.THRESHOLD_HR, 231.0, TODAY, GARMIN, sport=Sport.RUN
        )
        high_vo2 = _obs(MetricKind.VO2MAX, 101.0, TODAY, GARMIN, sport=Sport.RUN)

        self.assertIs(
            select_current(
                [low_ftp, high_ftp, wahoo], MetricKind.FTP, sport=Sport.RIDE
            ),
            wahoo,
        )
        self.assertIsNone(
            select_current([high_threshold], MetricKind.THRESHOLD_HR, sport=Sport.RUN)
        )
        self.assertIsNone(
            select_current([high_vo2], MetricKind.VO2MAX, sport=Sport.RUN)
        )

    def test_threshold_pace_and_max_hr_are_garmin_only(self) -> None:
        intervals_pace = _obs(MetricKind.THRESHOLD_PACE, 4.0, TODAY, sport=Sport.RUN)
        garmin_pace = _obs(
            MetricKind.THRESHOLD_PACE, 4.2, TODAY, GARMIN, sport=Sport.RUN
        )
        intervals_max = _obs(MetricKind.MAX_HR, 185.0, TODAY, sport=Sport.RIDE)

        self.assertIs(
            select_current(
                [intervals_pace, garmin_pace],
                MetricKind.THRESHOLD_PACE,
                sport=Sport.RUN,
            ),
            garmin_pace,
        )
        self.assertIsNone(
            select_current([intervals_max], MetricKind.MAX_HR, sport=Sport.RIDE)
        )

    def test_vo2max_prefers_garmin_for_the_sport(self) -> None:
        garmin = _obs(MetricKind.VO2MAX, 58.0, TODAY, GARMIN, sport=Sport.RUN)
        intervals = _obs(MetricKind.VO2MAX, 55.0, TODAY, sport=Sport.RUN)

        self.assertIs(
            select_current([intervals, garmin], MetricKind.VO2MAX, sport=Sport.RUN),
            garmin,
        )
        self.assertIsNone(
            select_current([intervals], MetricKind.VO2MAX, sport=Sport.RUN)
        )

    def test_load_kinds_have_no_current_rule(self) -> None:
        for kind in (MetricKind.CTL, MetricKind.ATL):
            observation = _obs(kind, 60.0, TODAY)
            self.assertNotIn(kind, CURRENT_RULES)
            self.assertIsNone(select_current([observation], kind))

    def test_garmin_thresholds_tie_keeps_the_last_input(self) -> None:
        first = _obs(MetricKind.FTP, 250.0, TODAY, GARMIN, sport=Sport.RIDE)
        second = _obs(MetricKind.FTP, 240.0, TODAY, GARMIN, sport=Sport.RIDE)

        self.assertIs(
            select_current([first, second], MetricKind.FTP, sport=Sport.RIDE), second
        )
        self.assertIs(
            select_current([second, first], MetricKind.FTP, sport=Sport.RIDE), first
        )

    def test_wahoo_thresholds_tie_keeps_the_first_input(self) -> None:
        first = _wahoo_ftp(250.0)
        second = _wahoo_ftp(240.0)

        self.assertIs(
            select_current([first, second], MetricKind.FTP, sport=Sport.RIDE), first
        )
        self.assertIs(
            select_current([second, first], MetricKind.FTP, sport=Sport.RIDE), second
        )

    def test_weight_breaks_same_day_garmin_ties_by_timestamp_then_last_input(
        self,
    ) -> None:
        # Legacy current weight orders same-day Garmin records by timestamp first;
        # an untimed record ranks below any timed one.
        early = _obs(MetricKind.WEIGHT, 80.0, TODAY, GARMIN, observed_at=EARLY)
        late = _obs(MetricKind.WEIGHT, 81.0, TODAY, GARMIN, observed_at=LATE)
        untimed = _obs(MetricKind.WEIGHT, 82.0, TODAY, GARMIN)

        self.assertIs(select_current([early, late], MetricKind.WEIGHT), late)
        self.assertIs(select_current([late, early], MetricKind.WEIGHT), late)
        self.assertIs(select_current([untimed, early], MetricKind.WEIGHT), early)
        self.assertIs(select_current([early, untimed], MetricKind.WEIGHT), early)
        self.assertIs(select_current([untimed, untimed], MetricKind.WEIGHT), untimed)

    def test_resting_hr_same_day_garmin_ties_ignore_timestamps_keep_last_input(
        self,
    ) -> None:
        # Legacy recovery ignores timestamps and keeps the last same-day record.
        late_stamp = _obs(MetricKind.RESTING_HR, 50.0, TODAY, GARMIN, observed_at=LATE)
        early_stamp = _obs(
            MetricKind.RESTING_HR, 52.0, TODAY, GARMIN, observed_at=EARLY
        )

        self.assertIs(
            select_current([late_stamp, early_stamp], MetricKind.RESTING_HR),
            early_stamp,
        )
        self.assertIs(
            select_current([early_stamp, late_stamp], MetricKind.RESTING_HR),
            late_stamp,
        )

    def test_empty_input_and_unknown_kinds_return_none(self) -> None:
        self.assertIsNone(select_current([], MetricKind.WEIGHT))
        self.assertIsNone(select_current([], MetricKind.HRV_SDNN))
        observation = _obs(MetricKind.TRAINING_LOAD, 40.0, TODAY)
        self.assertIsNone(select_current([observation], MetricKind.TRAINING_LOAD))

    def test_observations_without_a_provider_are_never_selected(self) -> None:
        estimate = _obs(MetricKind.READINESS, 90.0, TODAY, provider=None)

        self.assertIsNone(select_current([estimate], MetricKind.READINESS))


def _of(
    observations: list[Observation], kind: MetricKind, provider: ProviderId
) -> tuple[Observation, ...]:
    return tuple(
        item
        for item in observations
        if item.kind is kind and item.provenance.provider is provider
    )


def _weight(
    source: ProviderId | None,
    value: float,
    day: date | None,
    source_kind: SourceKind = SourceKind.PROVIDER_REPORTED,
) -> Candidate:
    observation = None
    if source is not None:
        base = _obs(MetricKind.WEIGHT, value, day or TODAY, source)
        observation = replace(
            base, provenance=replace(base.provenance, source_kind=source_kind)
        )
    return Candidate(source, value, day, observation)


class RecencyResolutionTests(unittest.TestCase):
    def test_the_newest_measurement_wins_across_sources(self) -> None:
        garmin = _weight(GARMIN, 72.0, date(2026, 5, 1), SourceKind.DEVICE_MEASURED)
        profile = _weight(None, 71.0, TODAY)

        resolved = resolve_candidates(MetricKind.WEIGHT, (garmin, profile), as_of=TODAY)

        assert resolved is not None
        self.assertIs(resolved.winner, profile)
        self.assertEqual(resolved.alternatives, (garmin,))

    def test_an_intervals_candidate_is_never_current(self) -> None:
        garmin = _weight(GARMIN, 72.0, date(2026, 5, 1), SourceKind.DEVICE_MEASURED)
        intervals = _weight(INTERVALS, 71.0, TODAY)

        resolved = resolve_candidates(
            MetricKind.WEIGHT, (intervals, garmin), as_of=TODAY
        )

        assert resolved is not None
        self.assertIs(resolved.winner, garmin)
        self.assertEqual(resolved.alternatives, ())
        self.assertIsNone(
            resolve_candidates(MetricKind.WEIGHT, (intervals,), as_of=TODAY)
        )

    def test_a_device_measurement_wins_within_one_day(self) -> None:
        garmin = _weight(GARMIN, 72.0, date(2026, 5, 3), SourceKind.DEVICE_MEASURED)
        wahoo = _weight(ProviderId.WAHOO, 70.0, TODAY)

        resolved = resolve_candidates(MetricKind.WEIGHT, (wahoo, garmin), as_of=TODAY)

        assert resolved is not None
        self.assertIs(resolved.winner, garmin)
        self.assertTrue(resolved.conflict)

    def test_an_athlete_entry_yields_to_a_report_within_one_day(self) -> None:
        typed = _weight(None, 72.0, TODAY)
        wahoo = _weight(ProviderId.WAHOO, 71.5, date(2026, 5, 3))

        resolved = resolve_candidates(MetricKind.WEIGHT, (typed, wahoo), as_of=TODAY)

        assert resolved is not None
        self.assertIs(resolved.winner, wahoo)

    def test_undated_values_are_fallbacks_in_order(self) -> None:
        wahoo = _weight(ProviderId.WAHOO, 74.0, None)
        profile = _weight(None, 73.0, None)

        resolved = resolve_candidates(MetricKind.WEIGHT, (wahoo, profile), as_of=TODAY)

        assert resolved is not None
        self.assertIs(resolved.winner, profile)
        dated = _weight(ProviderId.WAHOO, 74.0, None)
        garmin = _weight(GARMIN, 75.0, date(2026, 1, 1), SourceKind.DEVICE_MEASURED)
        resolved = resolve_candidates(MetricKind.WEIGHT, (dated, garmin), as_of=TODAY)
        assert resolved is not None
        self.assertIs(resolved.winner, garmin)


class PreferredSourceTests(unittest.TestCase):
    """The athlete's preferred source per metric group (#1668)."""

    def test_only_known_groups_and_providers_are_read(self) -> None:
        preferences = preferences_from_profile(
            {
                "preferred_source_hrv": "intervals",
                "preferred_source_body": "wahoo",
                "preferred_source_resting_hr": "garmin",
                "preferred_source_sleep": "",
            }
        )

        self.assertEqual(dict(preferences), {"resting_hr": GARMIN})

    def test_a_stored_intervals_preference_is_ignored_everywhere(self) -> None:
        profile = {
            "preferred_source_thresholds": "intervals",
            "preferred_source_body": "intervals",
            "preferred_source_hrv": "intervals",
            "preferred_source_resting_hr": "intervals",
            "preferred_source_sleep": "intervals",
        }
        preferences = preferences_from_profile(profile)

        self.assertEqual(dict(preferences), {})
        self.assertEqual(profile["preferred_source_hrv"], "intervals")
        garmin = _obs(MetricKind.HRV_RMSSD, 60.0, TODAY, GARMIN)
        intervals = _obs(MetricKind.HRV_RMSSD, 45.0, TODAY)
        self.assertIs(
            select_current(
                [intervals, garmin], MetricKind.HRV_RMSSD, preferences=preferences
            ),
            garmin,
        )
        self.assertEqual(
            source_order(MetricKind.FTP, Sport.RIDE, preferences),
            (None, GARMIN, ProviderId.WAHOO),
        )
        self.assertEqual(
            source_order(MetricKind.WEIGHT, preferences=preferences),
            (GARMIN, None, ProviderId.WAHOO),
        )

    def test_preferring_garmin_never_falls_back_to_another_method(self) -> None:
        preferences = preferences_from_profile({"preferred_source_sleep": "garmin"})
        intervals = _obs(MetricKind.SLEEP_SCORE, 80.0, TODAY)

        self.assertIsNone(
            select_current([intervals], MetricKind.SLEEP_SCORE, preferences=preferences)
        )

    def test_a_garmin_body_preference_keeps_the_profile_value_behind_garmin(
        self,
    ) -> None:
        preferences = preferences_from_profile({"preferred_source_body": "garmin"})

        self.assertEqual(
            source_order(MetricKind.WEIGHT, preferences=preferences),
            (GARMIN, None, ProviderId.WAHOO),
        )
        garmin = _weight(GARMIN, 72.0, date(2026, 4, 28), SourceKind.DEVICE_MEASURED)
        profile = _weight(None, 73.0, TODAY)
        resolved = resolve_candidates(
            MetricKind.WEIGHT, (profile, garmin), as_of=TODAY, preferences=preferences
        )
        assert resolved is not None
        self.assertIs(resolved.winner, garmin)
        self.assertEqual(resolved.alternatives, (profile,))


class DailySelectionTests(unittest.TestCase):
    def test_intervals_values_never_fill_garmin_gaps(self) -> None:
        intervals_same = _obs(MetricKind.SLEEP_DURATION, 25_200.0, TODAY)
        intervals_other = _obs(MetricKind.SLEEP_DURATION, 23_400.0, date(2026, 5, 3))
        garmin_same = _obs(MetricKind.SLEEP_DURATION, 28_800.0, TODAY, GARMIN)

        result = select_daily(
            [intervals_same, intervals_other, garmin_same], MetricKind.SLEEP_DURATION
        )

        self.assertEqual(result, {TODAY: garmin_same})

    def test_intervals_alone_yields_no_days(self) -> None:
        intervals = _obs(MetricKind.HRV_RMSSD, 58.0, TODAY)

        self.assertEqual(select_daily([intervals], MetricKind.HRV_RMSSD), {})

    def test_daily_rules_apply_the_current_bounds(self) -> None:
        implausible = _obs(MetricKind.RESTING_HR, 240.0, TODAY, GARMIN)

        self.assertEqual(select_daily([implausible], MetricKind.RESTING_HR), {})

    def test_readiness_is_garmin_only(self) -> None:
        intervals = _obs(MetricKind.READINESS, 71.0, TODAY)
        garmin_same = _obs(MetricKind.READINESS, 75.0, TODAY, GARMIN)
        garmin_gap = _obs(MetricKind.READINESS, 68.0, date(2026, 5, 3), GARMIN)

        result = select_daily(
            [garmin_same, garmin_gap, intervals], MetricKind.READINESS
        )

        self.assertEqual(_day_values(result), {TODAY: 75.0, date(2026, 5, 3): 68.0})

    def test_same_day_garmin_daily_duplicates_keep_the_first_input(self) -> None:
        # The planning overwrite keeps the first same-day record and ignores
        # timestamps, so the timestamp of the later record does not matter.
        early = _obs(MetricKind.HRV_RMSSD, 60.0, TODAY, GARMIN, observed_at=EARLY)
        late = _obs(MetricKind.HRV_RMSSD, 70.0, TODAY, GARMIN, observed_at=LATE)
        untimed_first = _obs(MetricKind.HRV_RMSSD, 65.0, TODAY, GARMIN)
        untimed_second = _obs(MetricKind.HRV_RMSSD, 66.0, TODAY, GARMIN)

        self.assertIs(select_daily([early, late], MetricKind.HRV_RMSSD)[TODAY], early)
        self.assertIs(select_daily([late, early], MetricKind.HRV_RMSSD)[TODAY], late)
        self.assertIs(
            select_daily([untimed_first, untimed_second], MetricKind.HRV_RMSSD)[TODAY],
            untimed_first,
        )

    def test_kinds_without_a_daily_rule_and_empty_input_return_nothing(self) -> None:
        self.assertEqual(select_daily([], MetricKind.SLEEP_DURATION), {})
        weight = _obs(MetricKind.WEIGHT, 80.0, TODAY)
        self.assertEqual(select_daily([weight], MetricKind.WEIGHT), {})
        self.assertEqual(select_daily([weight], MetricKind.HRV_SDNN), {})

    def test_provider_less_observations_are_never_daily_values(self) -> None:
        estimate = _obs(MetricKind.READINESS, 90.0, TODAY, provider=None)

        self.assertEqual(select_daily([estimate], MetricKind.READINESS), {})


def _wellness(day: str, **fields: Any) -> dict[str, Any]:
    return {"id": day, **fields}


def _garmin_record(day: str, **fields: Any) -> dict[str, Any]:
    return {"calendarDate": day, **fields}


WELLNESS_ROWS: list[dict[str, Any]] = [
    _wellness(
        "2026-05-03",
        weight=80.0,
        bodyFat=13.0,
        restingHR=47,
        hrv=58,
        sleepSecs=25_200,
        sleepScore=74,
        readiness=66,
        ctl=58.0,
        atl=54.0,
    ),
    _wellness(
        "2026-05-04",
        weight=81.0,
        bodyFat=14.0,
        restingHR=48,
        hrv=60,
        sleepSecs=27_000,
        sleepScore=78,
        readiness=71,
        ctl=60.0,
        atl=55.0,
    ),
]
ATHLETE: dict[str, Any] = {
    "id": "a1",
    "sportSettings": [
        {"types": ["Ride"], "ftp": 250, "lthr": 165, "max_hr": 185},
        {"types": ["Run"], "threshold_pace": 4.0, "lthr": 170},
    ],
}
# The legacy readers take the normalised snapshot key; the mappers take raw sportSettings.
LEGACY_ATHLETE: dict[str, Any] = {"sport_settings": ATHLETE["sportSettings"]}
GARMIN_SECTIONS: dict[str, Any] = {
    "weight": {
        "dailyWeightSummaries": [
            {
                "summaryDate": "2026-05-04",
                "latestWeight": {"weight": 80_500, "bodyFat": 12.0},
            }
        ]
    },
    "sleep": [_garmin_record("2026-05-04", sleepTimeSeconds=28_800, sleepScore=85)],
    "hrv": [_garmin_record("2026-05-04", hrvLastNight=70)],
    "resting_hr": [_garmin_record("2026-05-04", restingHeartRate=44)],
    "readiness": [_garmin_record("2026-05-04", score=75)],
    "cycling_ftp": _garmin_record("2026-05-04", functionalThresholdPower=302),
}


def _mapped(
    rows: list[dict[str, Any]],
    athlete: dict[str, Any] | None,
    garmin: dict[str, Any],
) -> list[Observation]:
    observations: list[Observation] = []
    observations += map_intervals_wellness(rows, retrieved_at=RETRIEVED_AT).records
    if athlete is not None:
        observations += map_intervals_athlete_thresholds(
            athlete, observed_on=TODAY, retrieved_at=RETRIEVED_AT
        ).records
    observations += map_garmin_health(
        garmin, zone=BERLIN, retrieved_at=RETRIEVED_AT
    ).records
    return observations


def _recovery_context(observations: list[Observation]) -> dict[str, Any]:
    """The recovery context over the same observations the policy ranks (#1411)."""
    return performance_recovery_context(recovery_inputs(observations), TODAY)


class GarminSelectionTests(unittest.TestCase):
    """Canonical selection over mapped data equals the readers' output.

    The fixture carries Intervals.icu wellness rows and an athlete record next to
    Garmin's sections; the Intervals values never reach a selected value.
    """

    def setUp(self) -> None:
        self.observations = _mapped(WELLNESS_ROWS, ATHLETE, GARMIN_SECTIONS)
        self.garmin_metrics = garmin_payload_performance_metrics(GARMIN_SECTIONS, TODAY)
        self.snapshot: dict[str, Any] = {
            "athlete": LEGACY_ATHLETE,
            "recent_wellness": WELLNESS_ROWS,
            "recent_activities": [],
        }
        self.current = current_performance_metrics(
            self.snapshot, {}, self.garmin_metrics
        )

    def pick(self, kind: MetricKind, sport: Sport | None = None) -> float | None:
        return _values(select_current(self.observations, kind, sport=sport))

    def test_zero_garmin_sleep_score_is_kept(self) -> None:
        garmin = {
            "sleep": [
                _garmin_record("2026-05-04", sleepTimeSeconds=28_800, sleepScore=0)
            ]
        }
        observations = _mapped(WELLNESS_ROWS, None, garmin)

        self.assertEqual(_recovery_context(observations)["sleep_score"], 0)
        self.assertEqual(
            _values(select_current(observations, MetricKind.SLEEP_SCORE)), 0.0
        )

    def test_garmin_heart_rate_zone_max_hr_is_the_current_value(self) -> None:
        garmin = {
            "heart_rate_zones": [
                _garmin_record("2026-05-04", sport="CYCLING", maxHeartRateUsed=188)
            ]
        }
        observations = _mapped(WELLNESS_ROWS, ATHLETE, garmin)

        current = current_performance_metrics(
            self.snapshot, {}, garmin_payload_performance_metrics(garmin, TODAY)
        )
        self.assertEqual(current["cycling_max_hr_bpm"]["value"], 188)
        self.assertEqual(
            _values(select_current(observations, MetricKind.MAX_HR, sport=Sport.RIDE)),
            188.0,
        )

    def test_weight_is_garmin_newest_over_the_wellness_rows(self) -> None:
        self.assertEqual(self.current["weight_kg"]["value"], 80.5)
        self.assertEqual(self.current["weight_kg"]["source"], "Garmin Connect")
        self.assertNotIn("alternatives", self.current["weight_kg"])
        self.assertEqual(
            self.pick(MetricKind.WEIGHT), self.current["weight_kg"]["value"]
        )

    def test_body_fat_takes_the_garmin_measurement_only(self) -> None:
        current = current_performance_metrics(
            self.snapshot,
            {},
            self.garmin_metrics,
            garmin_body=garmin_body(
                {
                    MetricKind.BODY_FAT: _of(
                        self.observations, MetricKind.BODY_FAT, GARMIN
                    )
                }
            ),
        )

        self.assertEqual(current["body_fat_pct"]["value"], 12)
        self.assertNotIn("alternatives", current["body_fat_pct"])
        self.assertEqual(
            self.pick(MetricKind.BODY_FAT), current["body_fat_pct"]["value"]
        )

    def test_cycling_ftp_with_intervals_and_garmin_present_is_garmins(self) -> None:
        self.assertEqual(self.current["cycling_ftp_watts"]["value"], 302)
        self.assertEqual(self.current["cycling_ftp_watts"]["source"], "Garmin Connect")
        self.assertNotIn("alternatives", self.current["cycling_ftp_watts"])
        self.assertEqual(self.pick(MetricKind.FTP, Sport.RIDE), 302)

    def test_cycling_ftp_with_only_intervals_is_none(self) -> None:
        without_garmin = _mapped(WELLNESS_ROWS, ATHLETE, {})
        current = current_performance_metrics(
            self.snapshot, {}, garmin_payload_performance_metrics({}, TODAY)
        )
        self.assertIsNone(current["cycling_ftp_watts"]["value"])
        self.assertIsNone(
            select_current(without_garmin, MetricKind.FTP, sport=Sport.RIDE)
        )

    def test_cycling_ftp_is_date_blind_and_keeps_the_last_garmin_record(self) -> None:
        # Current FTP reads the last numeric input record and ignores dates, so the
        # older-dated 300 wins because it comes last.
        garmin = {
            "cycling_ftp": [
                _garmin_record("2026-05-04", functionalThresholdPower=302),
                _garmin_record("2026-05-03", functionalThresholdPower=300),
            ]
        }
        metrics = garmin_payload_performance_metrics(garmin, TODAY)
        self.assertEqual(metrics["cycling_ftp_watts"]["value"], 300)
        self.assertEqual(
            _values(
                select_current(
                    _mapped([], None, garmin), MetricKind.FTP, sport=Sport.RIDE
                )
            ),
            300,
        )

    def test_same_day_garmin_ftp_duplicates_keep_the_last_record(self) -> None:
        garmin = {
            "cycling_ftp": [
                _garmin_record("2026-05-04", functionalThresholdPower=250),
                _garmin_record("2026-05-04", functionalThresholdPower=260),
            ]
        }

        metrics = garmin_payload_performance_metrics(garmin, TODAY)
        self.assertEqual(metrics["cycling_ftp_watts"]["value"], 260)
        self.assertEqual(
            _values(
                select_current(
                    _mapped([], None, garmin), MetricKind.FTP, sport=Sport.RIDE
                )
            ),
            260,
        )

    def test_same_day_garmin_resting_hr_duplicates_keep_the_last_record(self) -> None:
        garmin = {
            "resting_hr": [
                _garmin_record("2026-05-04", restingHeartRate=44),
                _garmin_record("2026-05-04", restingHeartRate=46),
            ]
        }
        observations = _mapped(WELLNESS_ROWS, None, garmin)

        self.assertEqual(_recovery_context(observations)["resting_hr"], 46)
        self.assertEqual(
            _values(select_current(observations, MetricKind.RESTING_HR)), 46
        )

    def test_wellness_rows_alone_give_no_current_value(self) -> None:
        observations = _mapped(WELLNESS_ROWS, None, {})
        context = _recovery_context(observations)

        for kind in (
            MetricKind.RESTING_HR,
            MetricKind.HRV_RMSSD,
            MetricKind.SLEEP_DURATION,
            MetricKind.SLEEP_SCORE,
            MetricKind.READINESS,
            MetricKind.WEIGHT,
            MetricKind.BODY_FAT,
        ):
            with self.subTest(kind=kind):
                self.assertIsNone(select_current(observations, kind))
        self.assertIsNone(context["sleep_hours"])
        self.assertIsNone(context["resting_hr"])
        self.assertIsNone(context["hrv"])
        self.assertIsNone(context["readiness"])
        current = current_performance_metrics(
            self.snapshot, {}, garmin_payload_performance_metrics({}, TODAY)
        )
        self.assertIsNone(current["weight_kg"]["value"])
        self.assertIsNone(current["body_fat_pct"]["value"])

    def test_intervals_sport_settings_are_not_thresholds(self) -> None:
        for key in (
            "bike_threshold_hr_bpm",
            "run_threshold_hr_bpm",
            "run_threshold_pace_seconds_per_km",
            "cycling_max_hr_bpm",
        ):
            with self.subTest(key=key):
                self.assertIsNone(self.current[key]["value"])
        self.assertIsNone(self.pick(MetricKind.THRESHOLD_HR, Sport.RIDE))
        self.assertIsNone(self.pick(MetricKind.THRESHOLD_HR, Sport.RUN))
        self.assertIsNone(self.pick(MetricKind.THRESHOLD_PACE, Sport.RUN))
        self.assertIsNone(self.pick(MetricKind.MAX_HR, Sport.RIDE))

    def test_recovery_context_matches_the_policy_for_each_metric(self) -> None:
        recovery = _recovery_context(self.observations)

        self.assertEqual(recovery["sleep_hours"], 8.0)
        sleep_seconds = self.pick(MetricKind.SLEEP_DURATION)
        assert sleep_seconds is not None
        self.assertEqual(round(sleep_seconds / 3600, 1), recovery["sleep_hours"])
        self.assertEqual(recovery["sleep_score"], 85)
        self.assertEqual(self.pick(MetricKind.SLEEP_SCORE), recovery["sleep_score"])
        self.assertEqual(recovery["resting_hr"], 44)
        self.assertEqual(self.pick(MetricKind.RESTING_HR), recovery["resting_hr"])
        self.assertEqual(recovery["hrv"], 70)
        self.assertEqual(self.pick(MetricKind.HRV_RMSSD), recovery["hrv"])
        # Readiness is Garmin's 75; the Intervals row says 71.
        self.assertEqual(recovery["readiness"], 75)
        self.assertEqual(self.pick(MetricKind.READINESS), recovery["readiness"])

    def test_daily_policy_keeps_only_garmin_hrv_days(self) -> None:
        self.assertEqual(
            _day_values(select_daily(self.observations, MetricKind.HRV_RMSSD)),
            {date(2026, 5, 4): 70},
        )

    def test_same_day_hrv_duplicates_keep_the_first_record(self) -> None:
        garmin = {
            "hrv": [
                _garmin_record("2026-05-04", hrvLastNight=60),
                _garmin_record("2026-05-04", hrvLastNight=70),
            ]
        }

        self.assertEqual(
            _day_values(select_daily(_mapped([], None, garmin), MetricKind.HRV_RMSSD)),
            {TODAY: 60},
        )


class IntentionalDeviationTests(unittest.TestCase):
    """Named cases where the canonical policy differs from a legacy reader."""

    def test_sleep_score_is_chosen_independently_of_sleep_duration(self) -> None:
        # Resolved by #1411: the legacy reader dropped the whole Garmin sleep block
        # when the Garmin record had no duration. The recovery context follows the
        # policy and keeps Garmin's score.
        garmin = {"sleep": [_garmin_record("2026-05-04", sleepScore=85)]}
        observations = _mapped(WELLNESS_ROWS, None, garmin)

        self.assertEqual(_recovery_context(observations)["sleep_score"], 85)
        self.assertEqual(
            _values(select_current(observations, MetricKind.SLEEP_SCORE)), 85.0
        )

    def test_planning_ignores_the_weekly_hrv_average(self) -> None:
        # Deviation: the deleted legacy planning view (#1416) fell back to
        # hrvWeeklyAvg. The Garmin mapper only uses the last-night average,
        # because the weekly average covers a different window.
        garmin = {"hrv": [_garmin_record("2026-05-04", hrvWeeklyAvg=65)]}
        observations = _mapped([], None, garmin)

        self.assertEqual(select_daily(observations, MetricKind.HRV_RMSSD), {})

    def test_planning_drops_garmin_values_that_the_mapper_rejects(self) -> None:
        # Deviation: the deleted legacy planning view (#1416) overwrote without a
        # plausibility check. The canonical mapper rejects a 15 bpm resting HR, and
        # the Intervals value does not fill the day.
        garmin = {"resting_hr": [_garmin_record("2026-05-04", restingHeartRate=15)]}
        observations = _mapped(WELLNESS_ROWS, None, garmin)

        self.assertNotIn(TODAY, select_daily(observations, MetricKind.RESTING_HR))

    def test_garmin_generic_vo2max_is_not_applied_to_a_sport_query(self) -> None:
        # Deviation: the legacy reader applies a generic Garmin VO2max to running.
        # The canonical observation has no sport, so a sport-specific query skips
        # it. The caller decides whether a generic value should apply.
        garmin = {"max_metrics": {"generic": {"vo2MaxPreciseValue": 55.0}}}
        observations = _mapped([], None, garmin)

        current = current_performance_metrics(
            {"athlete": {}, "recent_wellness": [], "recent_activities": []},
            {},
            garmin_payload_performance_metrics(garmin, TODAY),
        )
        self.assertEqual(current["running_vo2max_ml_kg_min"]["value"], 55)
        self.assertIsNone(
            select_current(observations, MetricKind.VO2MAX, sport=Sport.RUN)
        )

    def test_garmin_ftp_history_is_observed_but_the_section_reader_ignores_it(
        self,
    ) -> None:
        # Gap: the mapper observes cycling_ftp_history, but the current FTP reads
        # only the cycling_ftp section. Because FTP ranking is date-blind and keeps
        # the last Garmin input, the history record wins here by input position, not
        # by its later date. Pinned until the history mapping is reconciled.
        garmin = {
            "cycling_ftp": _garmin_record("2026-05-04", functionalThresholdPower=302),
            "cycling_ftp_history": [
                _garmin_record("2026-05-05", functionalThresholdPower=290)
            ],
        }
        observations = _mapped([], None, garmin)

        metrics = garmin_payload_performance_metrics(garmin, TODAY)
        self.assertEqual(metrics["cycling_ftp_watts"]["value"], 302)
        self.assertEqual(
            _values(select_current(observations, MetricKind.FTP, sport=Sport.RIDE)),
            290,
        )

    def test_intervals_weight_and_sport_vo2max_give_no_current_value(self) -> None:
        athlete = {"weight": 80.0, "sportSettings": [{"types": ["Ride"], "vo2max": 58}]}
        observations = _mapped(
            [_wellness(LATEST_DAY.isoformat(), weight=81.0)], athlete, {}
        )

        self.assertIsNone(select_current(observations, MetricKind.WEIGHT))
        self.assertIsNone(
            select_current(observations, MetricKind.VO2MAX, sport=Sport.RIDE)
        )
        self.assertIsNone(
            select_current(observations, MetricKind.VO2MAX, sport=Sport.RUN)
        )


if __name__ == "__main__":
    unittest.main()
