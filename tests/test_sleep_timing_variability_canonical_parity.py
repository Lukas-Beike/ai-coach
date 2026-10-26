"""sleep-timing-variability-v1 gives the same result from canonical periods as raw rows.

Each case maps synthetic Garmin sleep and Intervals.icu wellness rows to canonical
periods with the production mapper and compares the full timing result with
the legacy walk over the same rows. No account, network or real data is used.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import ProviderId
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.canonical_recovery import (
    RECOVERY_HISTORY_DAYS,
    read_recovery_inputs,
)
from backend.performance.personal_recovery import (
    personal_recovery,
    sleep_timing_variability,
)
from backend.providers.sleep_period_mapping import map_sleep_periods

INGEST_ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
TODAY = date(2026, 11, 1)


def epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def garmin_night(end: datetime, hours: float, *, nested: bool = False) -> dict:
    start = end - timedelta(hours=hours)
    record = {
        "calendarDate": end.date().isoformat(),
        "sleepStartTimestampGMT": epoch_ms(start),
        "sleepEndTimestampGMT": epoch_ms(end),
    }
    return {"dailySleepDTO": record} if nested else record


def wellness_night(end: datetime, hours: float) -> dict:
    start = end - timedelta(hours=hours)
    return {
        "id": end.date().isoformat(),
        "sleep_start_at": start.isoformat(),
        "sleep_end_at": end.isoformat(),
    }


def nights(count: int, *, skip: tuple[int, ...] = (), hour: int = 5) -> list[datetime]:
    """Wake instants (UTC) for ``count`` days ending today, varying a little."""
    return [
        datetime(d.year, d.month, d.day, hour, (offset * 7) % 50, tzinfo=UTC)
        for offset in range(count)
        if offset not in skip
        for d in (TODAY - timedelta(days=offset),)
    ]


def canonical_periods(garmin_rows: list[dict], wellness_rows: list[dict]) -> list:
    periods: list[Any] = []
    for index, element in enumerate(garmin_rows):
        periods.extend(
            map_sleep_periods(
                element,
                provider=ProviderId.GARMIN,
                source_record_id=f"sleep/{index}",
                retrieved_at=RETRIEVED_AT,
                zone=INGEST_ZONE,
            )
        )
    for row in wellness_rows:
        periods.extend(
            map_sleep_periods(
                row,
                provider=ProviderId.INTERVALS,
                source_record_id=row["id"],
                retrieved_at=RETRIEVED_AT,
                zone=INGEST_ZONE,
            )
        )
    return periods


class ParityTests(unittest.TestCase):
    def assert_parity(
        self, garmin_rows: list[dict], wellness_rows: list[dict], timezone: str
    ) -> dict:
        legacy = sleep_timing_variability(
            wellness_rows, {"sleep": garmin_rows}, timezone, TODAY
        )
        canonical = sleep_timing_variability(
            [],
            {},
            timezone,
            TODAY,
            periods=canonical_periods(garmin_rows, wellness_rows),
        )
        self.assertEqual(canonical, legacy)
        return canonical

    def test_a_full_garmin_history(self) -> None:
        result = self.assert_parity(
            [garmin_night(end, 7.5) for end in nights(40)], [], "Europe/Berlin"
        )
        self.assertEqual(result["status"], "ok")

    def test_midnight_and_dst_in_another_profile_zone(self) -> None:
        # Berlin and New York leave summer time on 2026-10-25 and 2026-11-01.
        ends = nights(30, hour=6)
        self.assert_parity(
            [garmin_night(end, 9.25) for end in ends], [], "America/New_York"
        )
        self.assert_parity(
            [garmin_night(end, 9.25) for end in ends], [], "Europe/Berlin"
        )

    def test_missing_nights_are_not_fabricated(self) -> None:
        result = self.assert_parity(
            [garmin_night(end, 8) for end in nights(30, skip=(3, 4, 10, 17))],
            [],
            "Europe/Berlin",
        )
        dates = {p["date"] for p in result["points_84"] if p.get("wake_at")}
        self.assertNotIn((TODAY - timedelta(days=3)).isoformat(), dates)

    def test_overlapping_providers_stay_separate(self) -> None:
        ends = nights(20)
        result = self.assert_parity(
            [garmin_night(end, 8, nested=True) for end in ends],
            [wellness_night(end, 7.75) for end in ends],
            "Europe/Berlin",
        )
        self.assertEqual(
            sorted(series["source"] for series in result["series"]),
            ["Garmin Connect", "Intervals.icu"],
        )

    def test_no_intervals_is_insufficient_data(self) -> None:
        self.assert_parity([], [{"id": "2026-10-30", "sleepSecs": 25_000}], "UTC")


class FakeReader:
    def __init__(self, periods: tuple | None) -> None:
        self.periods = periods

    def observations(self, db: Any, kind: Any, **_: Any) -> tuple:
        return ()


class PeriodReader(FakeReader):
    def sleep_periods(self, db: Any, *, start: Any = None, end: Any = None) -> tuple:
        self.start = start
        return self.periods or ()


class ReadPathTests(unittest.TestCase):
    def test_a_source_with_periods_feeds_the_regularity(self) -> None:
        periods = tuple(
            canonical_periods([garmin_night(end, 8) for end in nights(30)], [])
        )
        reader = PeriodReader(periods)
        inputs = read_recovery_inputs(
            reader, None, as_of=TODAY, latest_wellness_day=None
        )
        self.assertEqual(inputs.sleep_periods, periods)
        self.assertEqual(reader.start, TODAY - timedelta(days=RECOVERY_HISTORY_DAYS))
        regularity = personal_recovery(
            [], {}, {"timezone": "Europe/Berlin"}, TODAY, canonical=inputs
        )["regularity"]
        self.assertEqual(regularity["status"], "ok")

    def test_the_performance_read_keeps_the_periods(self) -> None:
        periods = tuple(
            canonical_periods([garmin_night(end, 8) for end in nights(30)], [])
        )

        class NoActivities:
            def activity_rows(self, db: Any, **_: Any) -> tuple:
                return ()

        inputs = read_performance_inputs(
            PeriodReader(periods),
            None,
            None,
            activity_reader=NoActivities(),
            as_of=TODAY,
        )
        assert inputs is not None and inputs.recovery is not None
        self.assertEqual(inputs.recovery.sleep_periods, periods)

    def test_a_source_without_periods_keeps_the_legacy_rows(self) -> None:
        inputs = read_recovery_inputs(
            FakeReader(None), None, as_of=TODAY, latest_wellness_day=None
        )
        self.assertIsNone(inputs.sleep_periods)
        garmin = {"sleep": [garmin_night(end, 8) for end in nights(30)]}
        self.assertEqual(
            personal_recovery([], garmin, {}, TODAY, canonical=inputs)["regularity"],
            personal_recovery([], garmin, {}, TODAY)["regularity"],
        )


if __name__ == "__main__":
    unittest.main()
