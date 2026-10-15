"""Source precedence rules, checked against the legacy performance readers.

The parity classes feed the same raw provider data to the legacy readers and to
the canonical mappers plus ``source_policy``, then compare the chosen values.
Named deviation tests pin where the canonical path intentionally differs from
the legacy output; each comment states why. Mapper gaps are pinned the same way
and name the field the mapper does not observe yet.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.current_metrics import current_performance_metrics
from backend.performance.garmin_metrics import garmin_performance_metrics
from backend.performance.load_context import performance_load_context
from backend.performance.planning_recovery import planning_recovery_by_date
from backend.performance.recovery_context import performance_recovery_context
from backend.performance.source_policy import (
    CURRENT_RULES,
    DAILY_RULES,
    select_current,
    select_daily,
)
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.providers.intervals_wellness_mapping import (
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)

GARMIN = ProviderId.GARMIN
INTERVALS = ProviderId.INTERVALS
BERLIN = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 5, 4)
# The newest Intervals wellness row in WELLNESS_ROWS; callers pass it as
# latest_wellness_day for wellness-derived kinds.
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
        MetricKind.SLEEP_DURATION,
        MetricKind.SLEEP_SCORE,
        MetricKind.READINESS,
        MetricKind.FTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.THRESHOLD_PACE,
        MetricKind.MAX_HR,
        MetricKind.VO2MAX,
        MetricKind.CTL,
        MetricKind.ATL,
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
    """Wahoo FTP and weight only ever fill in after Garmin and Intervals."""

    def test_ftp_and_weight_orders_put_wahoo_last(self) -> None:
        expected = (GARMIN, INTERVALS, ProviderId.WAHOO)
        self.assertEqual(expected, CURRENT_RULES[MetricKind.FTP].order)
        self.assertEqual(expected, CURRENT_RULES[MetricKind.WEIGHT].order)

    def test_wahoo_ftp_is_used_only_when_intervals_has_none(self) -> None:
        only_wahoo = [_wahoo_ftp(250)]
        self.assertEqual(
            250,
            _values(
                select_current(
                    only_wahoo,
                    MetricKind.FTP,
                    sport=Sport.RIDE,
                    latest_wellness_day=LATEST_DAY,
                )
            ),
        )
        with_intervals = [
            *only_wahoo,
            _obs(MetricKind.FTP, 240, LATEST_DAY, INTERVALS, sport=Sport.RIDE),
        ]
        self.assertEqual(
            240,
            _values(
                select_current(
                    with_intervals,
                    MetricKind.FTP,
                    sport=Sport.RIDE,
                    latest_wellness_day=LATEST_DAY,
                )
            ),
        )

    def test_wahoo_ftp_outside_the_bounds_is_not_selected(self) -> None:
        self.assertIsNone(
            select_current(
                [_wahoo_ftp(800)],
                MetricKind.FTP,
                sport=Sport.RIDE,
                latest_wellness_day=LATEST_DAY,
            )
        )

    def test_wahoo_weight_is_used_only_when_intervals_has_none(self) -> None:
        wahoo_weight = _obs(MetricKind.WEIGHT, 78.5, LATEST_DAY, ProviderId.WAHOO)
        self.assertEqual(
            78.5,
            _values(
                select_current(
                    [wahoo_weight],
                    MetricKind.WEIGHT,
                    latest_wellness_day=LATEST_DAY,
                )
            ),
        )
        intervals_weight = _obs(MetricKind.WEIGHT, 77.0, LATEST_DAY, INTERVALS)
        self.assertEqual(
            77.0,
            _values(
                select_current(
                    [wahoo_weight, intervals_weight],
                    MetricKind.WEIGHT,
                    latest_wellness_day=LATEST_DAY,
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
                            latest_wellness_day=LATEST_DAY,
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
                    latest_wellness_day=LATEST_DAY,
                    as_of=self.AS_OF,
                )
            ),
        )
        self.assertIsNone(
            select_current(
                [self._weight_days_old(91)],
                MetricKind.WEIGHT,
                latest_wellness_day=LATEST_DAY,
                as_of=self.AS_OF,
            )
        )

    def test_stale_wahoo_value_stays_in_history_and_fresh_intervals_still_win(
        self,
    ) -> None:
        stale = self._ftp_days_old(120, value=300)
        observations = [
            stale,
            _obs(MetricKind.FTP, 240, LATEST_DAY, INTERVALS, sport=Sport.RIDE),
        ]
        self.assertEqual(
            240,
            _values(
                select_current(
                    observations,
                    MetricKind.FTP,
                    sport=Sport.RIDE,
                    latest_wellness_day=LATEST_DAY,
                    as_of=self.AS_OF,
                )
            ),
        )
        self.assertIn(stale, observations)
        self.assertIsNone(
            select_current(
                [stale],
                MetricKind.FTP,
                sport=Sport.RIDE,
                latest_wellness_day=LATEST_DAY,
                as_of=self.AS_OF,
            )
        )

    def test_without_as_of_no_age_limit_applies(self) -> None:
        self.assertEqual(
            250,
            _values(
                select_current(
                    [self._ftp_days_old(400)],
                    MetricKind.FTP,
                    sport=Sport.RIDE,
                    latest_wellness_day=LATEST_DAY,
                )
            ),
        )

    def test_garmin_and_intervals_values_are_not_age_limited(self) -> None:
        old_garmin_weight = _obs(
            MetricKind.WEIGHT, 80.0, self.AS_OF - timedelta(days=400), GARMIN
        )
        self.assertIs(
            old_garmin_weight,
            select_current([old_garmin_weight], MetricKind.WEIGHT, as_of=self.AS_OF),
        )

    def test_only_the_wahoo_rules_carry_an_age_limit(self) -> None:
        limited = {
            kind: [(limit.provider, limit.days) for limit in rule.max_age]
            for kind, rule in CURRENT_RULES.items()
            if rule.max_age
        }
        self.assertEqual(
            limited,
            {
                MetricKind.FTP: [(ProviderId.WAHOO, 90)],
                MetricKind.WEIGHT: [(ProviderId.WAHOO, 90)],
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

    def test_daily_rules_carry_no_bounds(self) -> None:
        self.assertTrue(all(not rule.bounds for rule in DAILY_RULES.values()))

    def test_only_wellness_derived_kinds_are_latest_row_limited(self) -> None:
        latest_row_kinds = {
            kind for kind, rule in CURRENT_RULES.items() if rule.latest_intervals_row
        }
        self.assertEqual(
            latest_row_kinds,
            {
                MetricKind.WEIGHT,
                MetricKind.BODY_FAT,
                MetricKind.RESTING_HR,
                MetricKind.HRV_RMSSD,
                MetricKind.SLEEP_DURATION,
                MetricKind.SLEEP_SCORE,
                MetricKind.READINESS,
                MetricKind.CTL,
                MetricKind.ATL,
            },
        )

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
        # The latest-row limit applies to Intervals only, never to Garmin.
        self.assertIs(
            select_current(
                [intervals_new, garmin_old],
                MetricKind.WEIGHT,
                latest_wellness_day=LATEST_DAY,
            ),
            garmin_old,
        )

    def test_weight_uses_latest_intervals_row_without_garmin(self) -> None:
        older = _obs(MetricKind.WEIGHT, 80.0, date(2026, 5, 1))
        newer = _obs(MetricKind.WEIGHT, 81.0, TODAY)

        chosen = select_current([older, newer], MetricKind.WEIGHT)

        self.assertIs(chosen, newer)

    def test_latest_wellness_day_excludes_older_intervals_for_wellness_kinds(
        self,
    ) -> None:
        older = _obs(MetricKind.RESTING_HR, 55.0, date(2026, 5, 1))

        self.assertIs(select_current([older], MetricKind.RESTING_HR), older)
        self.assertIsNone(
            select_current(
                [older], MetricKind.RESTING_HR, latest_wellness_day=LATEST_DAY
            )
        )

    def test_latest_wellness_day_does_not_limit_intervals_thresholds(self) -> None:
        older_ftp = _obs(MetricKind.FTP, 250.0, date(2026, 5, 1), sport=Sport.RIDE)

        self.assertIs(
            select_current(
                [older_ftp],
                MetricKind.FTP,
                sport=Sport.RIDE,
                latest_wellness_day=LATEST_DAY,
            ),
            older_ftp,
        )

    def test_body_fat_ignores_garmin(self) -> None:
        garmin = _obs(MetricKind.BODY_FAT, 12.0, TODAY, GARMIN)

        self.assertIsNone(select_current([garmin], MetricKind.BODY_FAT))

        intervals = _obs(MetricKind.BODY_FAT, 14.0, date(2026, 5, 1))
        self.assertIs(
            select_current([garmin, intervals], MetricKind.BODY_FAT), intervals
        )

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
                self.assertIs(
                    select_current([garmin, intervals], MetricKind.RESTING_HR),
                    intervals,
                )

    def test_resting_hr_intervals_fallback_without_a_latest_day_is_unrestricted(
        self,
    ) -> None:
        old = _obs(MetricKind.RESTING_HR, 22.0, date(2025, 1, 1))

        self.assertIs(select_current([old], MetricKind.RESTING_HR), old)

    def test_hrv_bounds_are_inclusive_for_garmin_only(self) -> None:
        for value in (1.0, 300.0):
            with self.subTest(value=value):
                garmin = _obs(MetricKind.HRV_RMSSD, value, TODAY, GARMIN)
                intervals = _obs(MetricKind.HRV_RMSSD, 60.0, date(2026, 5, 1))
                self.assertIs(
                    select_current([garmin, intervals], MetricKind.HRV_RMSSD), garmin
                )

        for value in (0.5, 300.5):
            with self.subTest(value=value):
                garmin = _obs(MetricKind.HRV_RMSSD, value, TODAY, GARMIN)
                intervals = _obs(MetricKind.HRV_RMSSD, 60.0, date(2026, 5, 1))
                self.assertIs(
                    select_current([garmin, intervals], MetricKind.HRV_RMSSD),
                    intervals,
                )

        unbounded = _obs(MetricKind.HRV_RMSSD, 400.0, TODAY)
        self.assertIs(select_current([unbounded], MetricKind.HRV_RMSSD), unbounded)

    def test_sleep_duration_prefers_garmin_regardless_of_date(self) -> None:
        garmin_old = _obs(MetricKind.SLEEP_DURATION, 28_800.0, date(2026, 5, 1), GARMIN)
        intervals_new = _obs(MetricKind.SLEEP_DURATION, 25_200.0, TODAY)

        self.assertIs(
            select_current([intervals_new, garmin_old], MetricKind.SLEEP_DURATION),
            garmin_old,
        )

    def test_sleep_score_prefers_in_bounds_garmin(self) -> None:
        garmin = _obs(MetricKind.SLEEP_SCORE, 85.0, TODAY, GARMIN)
        intervals = _obs(MetricKind.SLEEP_SCORE, 78.0, TODAY)

        self.assertIs(
            select_current([intervals, garmin], MetricKind.SLEEP_SCORE), garmin
        )
        # The 0-100 bound is also enforced by Observation validation, so a
        # Garmin score outside it cannot reach the policy; no separate case.

    def test_readiness_prefers_intervals_even_when_garmin_is_newer(self) -> None:
        intervals_old = _obs(MetricKind.READINESS, 66.0, date(2026, 5, 1))
        garmin_new = _obs(MetricKind.READINESS, 75.0, TODAY, GARMIN)

        self.assertIs(
            select_current([garmin_new, intervals_old], MetricKind.READINESS),
            intervals_old,
        )
        self.assertIs(select_current([garmin_new], MetricKind.READINESS), garmin_new)

    def test_sport_specific_thresholds_prefer_garmin_per_sport(self) -> None:
        garmin_ride = _obs(MetricKind.FTP, 302.0, TODAY, GARMIN, sport=Sport.RIDE)
        intervals_ride = _obs(MetricKind.FTP, 250.0, TODAY, sport=Sport.RIDE)
        intervals_run = _obs(MetricKind.FTP, 280.0, TODAY, sport=Sport.RUN)
        observations = [intervals_run, intervals_ride, garmin_ride]

        self.assertIs(
            select_current(observations, MetricKind.FTP, sport=Sport.RIDE),
            garmin_ride,
        )
        self.assertIs(
            select_current(observations, MetricKind.FTP, sport=Sport.RUN),
            intervals_run,
        )

    def test_sport_filter_excludes_other_sports_and_unsported_values(self) -> None:
        run_only = _obs(MetricKind.THRESHOLD_HR, 170.0, TODAY, sport=Sport.RUN)

        self.assertIsNone(
            select_current([run_only], MetricKind.THRESHOLD_HR, sport=Sport.RIDE)
        )
        self.assertIs(
            select_current([run_only], MetricKind.THRESHOLD_HR, sport=Sport.RUN),
            run_only,
        )

    def test_sport_scoped_kinds_refuse_a_sportless_query(self) -> None:
        run_only = _obs(MetricKind.THRESHOLD_HR, 170.0, TODAY, sport=Sport.RUN)

        with self.assertRaises(ValueError):
            select_current([run_only], MetricKind.THRESHOLD_HR, sport=None)
        # Sport-agnostic kinds still accept no sport.
        weight = _obs(MetricKind.WEIGHT, 80.0, TODAY)
        self.assertIs(select_current([weight], MetricKind.WEIGHT), weight)

    def test_garmin_values_outside_legacy_bounds_are_not_selected(self) -> None:
        low_ftp = _obs(MetricKind.FTP, 49.0, TODAY, GARMIN, sport=Sport.RIDE)
        high_ftp = _obs(MetricKind.FTP, 701.0, TODAY, GARMIN, sport=Sport.RIDE)
        intervals = _obs(MetricKind.FTP, 250.0, date(2026, 5, 1), sport=Sport.RIDE)
        high_threshold = _obs(
            MetricKind.THRESHOLD_HR, 231.0, TODAY, GARMIN, sport=Sport.RUN
        )
        high_vo2 = _obs(MetricKind.VO2MAX, 101.0, TODAY, GARMIN, sport=Sport.RUN)

        self.assertIs(
            select_current(
                [low_ftp, high_ftp, intervals], MetricKind.FTP, sport=Sport.RIDE
            ),
            intervals,
        )
        self.assertIsNone(
            select_current([high_threshold], MetricKind.THRESHOLD_HR, sport=Sport.RUN)
        )
        self.assertIsNone(
            select_current([high_vo2], MetricKind.VO2MAX, sport=Sport.RUN)
        )

    def test_threshold_pace_and_max_hr_follow_garmin_then_intervals(self) -> None:
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
        self.assertIs(
            select_current([intervals_max], MetricKind.MAX_HR, sport=Sport.RIDE),
            intervals_max,
        )

    def test_vo2max_prefers_garmin_for_the_sport(self) -> None:
        garmin = _obs(MetricKind.VO2MAX, 58.0, TODAY, GARMIN, sport=Sport.RUN)
        intervals = _obs(MetricKind.VO2MAX, 55.0, TODAY, sport=Sport.RUN)

        self.assertIs(
            select_current([intervals, garmin], MetricKind.VO2MAX, sport=Sport.RUN),
            garmin,
        )

    def test_load_is_intervals_only_and_latest(self) -> None:
        garmin = _obs(MetricKind.CTL, 90.0, TODAY, GARMIN)
        older = _obs(MetricKind.CTL, 58.0, date(2026, 5, 2))
        latest = _obs(MetricKind.CTL, 60.0, TODAY)

        self.assertIs(select_current([garmin, older, latest], MetricKind.CTL), latest)
        self.assertIsNone(select_current([garmin], MetricKind.ATL))

    def test_intervals_thresholds_tie_keeps_the_first_input(self) -> None:
        first = _obs(MetricKind.FTP, 250.0, TODAY, sport=Sport.RIDE)
        second = _obs(MetricKind.FTP, 240.0, TODAY, sport=Sport.RIDE)

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


class DailySelectionTests(unittest.TestCase):
    def test_garmin_overwrites_intervals_on_the_same_day_only(self) -> None:
        intervals_same = _obs(MetricKind.SLEEP_DURATION, 25_200.0, TODAY)
        intervals_other = _obs(MetricKind.SLEEP_DURATION, 23_400.0, date(2026, 5, 3))
        garmin_same = _obs(MetricKind.SLEEP_DURATION, 28_800.0, TODAY, GARMIN)

        result = select_daily(
            [intervals_same, intervals_other, garmin_same], MetricKind.SLEEP_DURATION
        )

        self.assertIs(result[TODAY], garmin_same)
        self.assertIs(result[date(2026, 5, 3)], intervals_other)

    def test_daily_rules_do_not_apply_bounds(self) -> None:
        implausible = _obs(MetricKind.RESTING_HR, 240.0, TODAY, GARMIN)

        result = select_daily([implausible], MetricKind.RESTING_HR)

        self.assertIs(result[TODAY], implausible)

    def test_readiness_is_intervals_first_and_garmin_fills_gaps(self) -> None:
        intervals = _obs(MetricKind.READINESS, 71.0, TODAY)
        garmin_same = _obs(MetricKind.READINESS, 75.0, TODAY, GARMIN)
        garmin_gap = _obs(MetricKind.READINESS, 68.0, date(2026, 5, 3), GARMIN)

        result = select_daily(
            [garmin_same, garmin_gap, intervals], MetricKind.READINESS
        )

        self.assertEqual(_day_values(result), {TODAY: 71.0, date(2026, 5, 3): 68.0})

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


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=lambda row: str(row["id"]))


def _latest_day(rows: list[dict[str, Any]]) -> date:
    return date.fromisoformat(str(_latest_row(rows)["id"]))


class ParityWithLegacyReadersTests(unittest.TestCase):
    """Canonical selection over mapped data equals the legacy readers' output."""

    def setUp(self) -> None:
        self.observations = _mapped(WELLNESS_ROWS, ATHLETE, GARMIN_SECTIONS)
        self.garmin_metrics = garmin_performance_metrics(GARMIN_SECTIONS, TODAY)
        self.snapshot: dict[str, Any] = {
            "athlete": LEGACY_ATHLETE,
            "recent_wellness": WELLNESS_ROWS,
            "recent_activities": [],
        }
        self.legacy = current_performance_metrics(
            self.snapshot, {}, self.garmin_metrics
        )

    def pick(self, kind: MetricKind, sport: Sport | None = None) -> float | None:
        """Select from the fixture data, as the caller does with the latest row."""
        return _values(
            select_current(
                self.observations,
                kind,
                sport=sport,
                latest_wellness_day=LATEST_DAY,
            )
        )

    def test_zero_garmin_sleep_score_is_kept_like_legacy(self) -> None:
        garmin = {
            "sleep": [
                _garmin_record("2026-05-04", sleepTimeSeconds=28_800, sleepScore=0)
            ]
        }
        observations = _mapped(WELLNESS_ROWS, None, garmin)

        legacy = performance_recovery_context(
            garmin, _latest_row(WELLNESS_ROWS), WELLNESS_ROWS, TODAY
        )
        self.assertEqual(legacy["sleep_score"], 0)
        self.assertEqual(
            _values(
                select_current(
                    observations,
                    MetricKind.SLEEP_SCORE,
                    latest_wellness_day=LATEST_DAY,
                )
            ),
            0.0,
        )

    def test_garmin_heart_rate_zone_max_hr_matches_legacy_observation(self) -> None:
        garmin = {
            "heart_rate_zones": [
                _garmin_record("2026-05-04", sport="CYCLING", maxHeartRateUsed=188)
            ]
        }
        observations = _mapped(WELLNESS_ROWS, ATHLETE, garmin)

        legacy = current_performance_metrics(
            self.snapshot, {}, garmin_performance_metrics(garmin, TODAY)
        )
        self.assertEqual(legacy["cycling_max_hr_bpm"]["value"], 188)
        self.assertEqual(
            _values(select_current(observations, MetricKind.MAX_HR, sport=Sport.RIDE)),
            188.0,
        )

    def test_weight_is_garmin_newest_over_latest_wellness(self) -> None:
        self.assertEqual(self.legacy["weight_kg"]["value"], 80.5)
        self.assertEqual(self.legacy["weight_kg"]["source"], "Garmin Connect")
        self.assertEqual(
            self.pick(MetricKind.WEIGHT), self.legacy["weight_kg"]["value"]
        )

    def test_body_fat_ignores_the_garmin_weight_payload(self) -> None:
        self.assertEqual(self.legacy["body_fat_pct"]["value"], 14.0)
        self.assertEqual(
            self.pick(MetricKind.BODY_FAT), self.legacy["body_fat_pct"]["value"]
        )

    def test_cycling_ftp_is_garmin_then_matches_the_sport_setting(self) -> None:
        self.assertEqual(self.legacy["cycling_ftp_watts"]["value"], 302)
        self.assertEqual(
            self.pick(MetricKind.FTP, Sport.RIDE),
            self.legacy["cycling_ftp_watts"]["value"],
        )

        without_garmin = _mapped(WELLNESS_ROWS, ATHLETE, {})
        legacy_without = current_performance_metrics(
            self.snapshot,
            {},
            garmin_performance_metrics({}, TODAY),
        )
        self.assertEqual(legacy_without["cycling_ftp_watts"]["value"], 250)
        self.assertEqual(
            _values(
                select_current(
                    without_garmin,
                    MetricKind.FTP,
                    sport=Sport.RIDE,
                    latest_wellness_day=LATEST_DAY,
                )
            ),
            250,
        )

    def test_cycling_ftp_is_date_blind_and_keeps_the_last_garmin_record(self) -> None:
        # Legacy current FTP reads the last numeric input record and ignores dates,
        # so the older-dated 300 wins because it comes last.
        garmin = {
            "cycling_ftp": [
                _garmin_record("2026-05-04", functionalThresholdPower=302),
                _garmin_record("2026-05-03", functionalThresholdPower=300),
            ]
        }
        legacy = garmin_performance_metrics(garmin, TODAY)
        self.assertEqual(legacy["cycling_ftp_watts"]["value"], 300)
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

        legacy = garmin_performance_metrics(garmin, TODAY)
        self.assertEqual(legacy["cycling_ftp_watts"]["value"], 260)
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

        legacy = performance_recovery_context(
            garmin, _latest_row(WELLNESS_ROWS), WELLNESS_ROWS, TODAY
        )
        self.assertEqual(legacy["resting_hr"], 46)
        self.assertEqual(
            _values(
                select_current(
                    _mapped(WELLNESS_ROWS, None, garmin),
                    MetricKind.RESTING_HR,
                    latest_wellness_day=LATEST_DAY,
                )
            ),
            46,
        )

    def test_latest_row_without_the_field_gives_no_intervals_fallback(self) -> None:
        # Legacy recovery reads only the latest wellness row, so an older row that
        # has restingHR is never used. The policy matches once the caller passes
        # the latest row date.
        rows = [_wellness("2026-05-03", restingHR=47), _wellness("2026-05-04", hrv=60)]
        observations = _mapped(rows, None, {})

        legacy = performance_recovery_context({}, _latest_row(rows), rows, TODAY)
        self.assertIsNone(legacy["resting_hr"])
        self.assertIsNone(
            select_current(
                observations,
                MetricKind.RESTING_HR,
                latest_wellness_day=_latest_day(rows),
            )
        )

    def test_newest_row_without_weight_gives_no_intervals_fallback(self) -> None:
        # Legacy current weight reads only the newest wellness row, so an older
        # row's weight is not used when the newest row lacks it.
        rows = [_wellness("2026-05-03", weight=80.0), _wellness("2026-05-04", hrv=60)]
        observations = _mapped(rows, None, {})

        legacy = current_performance_metrics(
            {"athlete": {}, "recent_wellness": rows, "recent_activities": []},
            {},
            garmin_performance_metrics({}, TODAY),
        )
        self.assertIsNone(legacy["weight_kg"]["value"])
        self.assertIsNone(
            select_current(
                observations,
                MetricKind.WEIGHT,
                latest_wellness_day=_latest_day(rows),
            )
        )

    def test_thresholds_follow_the_sport_settings(self) -> None:
        self.assertEqual(self.legacy["bike_threshold_hr_bpm"]["value"], 165)
        self.assertEqual(self.legacy["run_threshold_hr_bpm"]["value"], 170)
        self.assertEqual(self.legacy["run_threshold_pace_seconds_per_km"]["value"], 250)
        self.assertEqual(self.pick(MetricKind.THRESHOLD_HR, Sport.RIDE), 165)
        self.assertEqual(self.pick(MetricKind.THRESHOLD_HR, Sport.RUN), 170)
        pace = self.pick(MetricKind.THRESHOLD_PACE, Sport.RUN)
        assert pace is not None
        self.assertEqual(round(1000 / pace), 250)

    def test_max_hr_is_the_sport_setting_value(self) -> None:
        self.assertEqual(self.legacy["cycling_max_hr_bpm"]["value"], 185)
        self.assertEqual(self.pick(MetricKind.MAX_HR, Sport.RIDE), 185)

    def test_load_is_the_latest_intervals_row(self) -> None:
        load = performance_load_context(
            [], WELLNESS_ROWS, _latest_row(WELLNESS_ROWS), TODAY
        )["load"]
        self.assertEqual(load["ctl"], 60.0)
        self.assertEqual(load["atl"], 55.0)
        self.assertEqual(self.pick(MetricKind.CTL), 60.0)
        self.assertEqual(self.pick(MetricKind.ATL), 55.0)

    def test_recovery_context_matches_the_policy_for_each_metric(self) -> None:
        recovery = performance_recovery_context(
            GARMIN_SECTIONS, _latest_row(WELLNESS_ROWS), WELLNESS_ROWS, TODAY
        )

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
        self.assertEqual(recovery["readiness"], 71)
        self.assertEqual(self.pick(MetricKind.READINESS), recovery["readiness"])

    def test_planning_view_matches_the_daily_policy(self) -> None:
        planning = planning_recovery_by_date(WELLNESS_ROWS, GARMIN_SECTIONS, {}, None)

        sleep = _day_values(select_daily(self.observations, MetricKind.SLEEP_DURATION))
        self.assertEqual(
            {day: round(seconds / 3600, 1) for day, seconds in sleep.items()},
            {
                date(2026, 5, 3): planning["2026-05-03"]["sleep_hours"],
                date(2026, 5, 4): planning["2026-05-04"]["sleep_hours"],
            },
        )
        self.assertEqual(
            _day_values(select_daily(self.observations, MetricKind.HRV_RMSSD)),
            {date(2026, 5, 3): 58, date(2026, 5, 4): 70},
        )
        self.assertEqual(planning["2026-05-04"]["hrv"], 70)
        self.assertEqual(planning["2026-05-03"]["hrv"], 58)
        self.assertEqual(
            _day_values(select_daily(self.observations, MetricKind.RESTING_HR))[TODAY],
            planning["2026-05-04"]["resting_hr"],
        )
        readiness = _day_values(select_daily(self.observations, MetricKind.READINESS))
        self.assertEqual(readiness[TODAY], planning["2026-05-04"]["readiness"])
        self.assertEqual(
            readiness[date(2026, 5, 3)], planning["2026-05-03"]["readiness"]
        )

    def test_planning_same_day_hrv_duplicates_keep_the_first_record(self) -> None:
        garmin = {
            "hrv": [
                _garmin_record("2026-05-04", hrvLastNight=60),
                _garmin_record("2026-05-04", hrvLastNight=70),
            ]
        }

        planning = planning_recovery_by_date([], garmin, {}, None)
        self.assertEqual(planning["2026-05-04"]["hrv"], 60)
        self.assertEqual(
            _day_values(select_daily(_mapped([], None, garmin), MetricKind.HRV_RMSSD)),
            {TODAY: 60},
        )


class IntentionalDeviationTests(unittest.TestCase):
    """Named cases where the canonical policy differs from a legacy reader."""

    def test_sleep_score_is_chosen_independently_of_sleep_duration(self) -> None:
        # Deviation: the legacy reader drops the whole Garmin sleep block when the
        # Garmin record has no duration, so Intervals' score is used. The policy
        # ranks sleep score on its own and keeps the Garmin score.
        garmin = {"sleep": [_garmin_record("2026-05-04", sleepScore=85)]}
        observations = _mapped(WELLNESS_ROWS, None, garmin)

        legacy = performance_recovery_context(
            garmin, _latest_row(WELLNESS_ROWS), WELLNESS_ROWS, TODAY
        )
        self.assertEqual(legacy["sleep_score"], 78)
        self.assertEqual(
            _values(
                select_current(
                    observations,
                    MetricKind.SLEEP_SCORE,
                    latest_wellness_day=LATEST_DAY,
                )
            ),
            85.0,
        )

    def test_planning_ignores_the_weekly_hrv_average(self) -> None:
        # Deviation: the legacy planning view falls back to hrvWeeklyAvg. The
        # Garmin mapper only uses the last-night average, because the weekly
        # average covers a different window.
        garmin = {"hrv": [_garmin_record("2026-05-04", hrvWeeklyAvg=65)]}
        observations = _mapped([], None, garmin)

        legacy = planning_recovery_by_date([], garmin, {}, None)
        self.assertEqual(legacy["2026-05-04"]["hrv"], 65)
        self.assertEqual(select_daily(observations, MetricKind.HRV_RMSSD), {})

    def test_planning_keeps_garmin_values_that_the_mapper_rejects(self) -> None:
        # Deviation: the legacy planning view overwrites without a plausibility
        # check. The canonical mapper rejects a 15 bpm resting HR, so the
        # Intervals value stays for that day.
        garmin = {"resting_hr": [_garmin_record("2026-05-04", restingHeartRate=15)]}
        observations = _mapped(WELLNESS_ROWS, None, garmin)

        legacy = planning_recovery_by_date(WELLNESS_ROWS, garmin, {}, None)
        self.assertEqual(legacy["2026-05-04"]["resting_hr"], 15)
        self.assertEqual(
            _day_values(select_daily(observations, MetricKind.RESTING_HR))[TODAY],
            48.0,
        )

    def test_garmin_generic_vo2max_is_not_applied_to_a_sport_query(self) -> None:
        # Deviation: the legacy reader applies a generic Garmin VO2max to running.
        # The canonical observation has no sport, so a sport-specific query skips
        # it. The caller decides whether a generic value should apply.
        garmin = {"max_metrics": {"generic": {"vo2MaxPreciseValue": 55.0}}}
        observations = _mapped([], None, garmin)

        legacy = current_performance_metrics(
            {"athlete": {}, "recent_wellness": [], "recent_activities": []},
            {},
            garmin_performance_metrics(garmin, TODAY),
        )
        self.assertEqual(legacy["running_vo2max_ml_kg_min"]["value"], 55)
        self.assertIsNone(
            select_current(observations, MetricKind.VO2MAX, sport=Sport.RUN)
        )

    def test_garmin_ftp_history_is_observed_but_legacy_ignores_it(self) -> None:
        # Gap: the mapper observes cycling_ftp_history, but legacy current FTP reads
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

        legacy = garmin_performance_metrics(garmin, TODAY)
        self.assertEqual(legacy["cycling_ftp_watts"]["value"], 302)
        self.assertEqual(
            _values(select_current(observations, MetricKind.FTP, sport=Sport.RIDE)),
            290,
        )

    def test_athlete_level_weight_matches_the_legacy_fallback(self) -> None:
        # Parity: the legacy weight chain reads the latest wellness weight first and
        # the athlete weight only when that is missing. Athlete values are undated,
        # so they rank below dated Intervals values, even on the same day.
        cases: tuple[tuple[str, list[dict[str, Any]], float, float], ...] = (
            ("no wellness rows", [], 81.0, 81.0),
            (
                "same-day wellness weight wins over the athlete weight",
                [_wellness(LATEST_DAY.isoformat(), weight=81.0)],
                80.0,
                81.0,
            ),
            (
                "newest row without weight falls back to the athlete weight",
                [
                    _wellness("2026-05-03", weight=79.0),
                    _wellness("2026-05-04", restingHR=50),
                ],
                80.0,
                80.0,
            ),
        )
        for label, rows, athlete_weight, expected in cases:
            with self.subTest(label):
                athlete = {"weight": athlete_weight}
                legacy = current_performance_metrics(
                    {
                        "athlete": athlete,
                        "recent_wellness": rows,
                        "recent_activities": [],
                    },
                    {},
                    garmin_performance_metrics({}, TODAY),
                )
                # The athlete observation is listed first to show that input order
                # does not decide between an undated and a dated weight.
                observations = [
                    *map_intervals_athlete_thresholds(
                        athlete, observed_on=TODAY, retrieved_at=RETRIEVED_AT
                    ).records,
                    *map_intervals_wellness(rows, retrieved_at=RETRIEVED_AT).records,
                ]
                latest = _latest_day(rows) if rows else None
                self.assertEqual(legacy["weight_kg"]["value"], expected)
                self.assertEqual(
                    _values(
                        select_current(
                            observations,
                            MetricKind.WEIGHT,
                            latest_wellness_day=latest,
                        )
                    ),
                    expected,
                )

    def test_sport_setting_vo2max_matches_the_legacy_reader(self) -> None:
        # Parity: the sport-setting VO2max is selected for its own sport only.
        athlete = {"sportSettings": [{"types": ["Ride"], "vo2max": 58}]}
        observations = _mapped([], athlete, {})

        legacy = current_performance_metrics(
            {
                "athlete": {"sport_settings": athlete["sportSettings"]},
                "recent_wellness": [],
                "recent_activities": [],
            },
            {},
            garmin_performance_metrics({}, TODAY),
        )
        self.assertEqual(legacy["cycling_vo2max_ml_kg_min"]["value"], 58)
        self.assertEqual(
            _values(select_current(observations, MetricKind.VO2MAX, sport=Sport.RIDE)),
            58,
        )
        self.assertIsNone(
            select_current(observations, MetricKind.VO2MAX, sport=Sport.RUN)
        )

    @staticmethod
    def snapshot_without_wellness() -> dict[str, Any]:
        return {
            "athlete": LEGACY_ATHLETE,
            "recent_wellness": [],
            "recent_activities": [],
        }


if __name__ == "__main__":
    unittest.main()
