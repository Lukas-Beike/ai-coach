"""Activities are dated where they were recorded (#1669).

Synthetic rows only; no account, network or real data is used.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_summary import activity_summary
from backend.canonical.activity_summary import summary_local_date
from backend.canonical.local_time import (
    wall_clock_offset_minutes,
    wall_time,
    zone_offset_minutes,
)
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store
from backend.providers import canonical_plans
from backend.providers.sleep_period_mapping import map_sleep_periods

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
RETRIEVED_AT = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
# 06:30 in Tokyo on Monday 2026-10-12 is 23:30 in Berlin on Sunday 2026-10-11.
TOKYO_MORNING = datetime(2026, 10, 11, 21, 30, tzinfo=UTC)
JST_MINUTES = 9 * 60


def garmin_payload(**row: Any) -> dict[str, Any]:
    activity = {
        "activityId": 920001,
        "activityName": "Synthetic run",
        "activityType": {"typeKey": "running"},
        "duration": 3600.0,
        **row,
    }
    return {"synced_at": RETRIEVED_AT.isoformat(), "activities": [activity]}


def intervals_raw(**row: Any) -> dict[str, Any]:
    return {"activities": [{"id": "i-travel", "type": "Run", **row}]}


def record(
    offset: int | None, provider: ProviderId = ProviderId.GARMIN
) -> ActivityRecord:
    return ActivityRecord(
        activity_id=f"{provider.value}-1",
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.DEVICE_MEASURED,
            source_record_id=f"{provider.value}-1",
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=RETRIEVED_AT,
            label="Synthetic",
        ),
        sport=Sport.RUN,
        environment=Environment.OUTDOOR,
        started_at=TOKYO_MORNING,
        duration_s=3600.0,
        distance_m=None,
        load=None,
        load_model=LoadModel.UNKNOWN,
        avg_hr=None,
        avg_power=None,
        name=None,
        local_offset_minutes=offset,
    )


def garmin_day(payload: dict[str, Any], zone: ZoneInfo) -> date:
    plan = canonical_plans.garmin_ingest_plan(payload, zone=zone)
    return plan.activities[0].local_date


class OffsetHelperTests(unittest.TestCase):
    def test_wall_clock_text_gives_the_rounded_offset(self) -> None:
        self.assertEqual(
            JST_MINUTES,
            wall_clock_offset_minutes("2026-10-12 06:30:00", TOKYO_MORNING),
        )
        # A device clock a few seconds off still names the quarter hour.
        self.assertEqual(
            JST_MINUTES,
            wall_clock_offset_minutes("2026-10-12 06:30:07", TOKYO_MORNING),
        )
        self.assertEqual(
            -240,
            wall_clock_offset_minutes("2026-10-11T17:30:00-04:00", TOKYO_MORNING),
        )

    def test_unusable_text_or_offsets_beyond_fourteen_hours_are_unknown(self) -> None:
        for text in (None, "", "06:30", "2026-10-13 06:30:00", 17):
            with self.subTest(text=text):
                self.assertIsNone(wall_clock_offset_minutes(text, TOKYO_MORNING))

    def test_zone_offset_follows_daylight_saving_and_rejects_unknown_names(
        self,
    ) -> None:
        summer = datetime(2026, 7, 1, 12, tzinfo=UTC)
        winter = datetime(2026, 12, 1, 12, tzinfo=UTC)
        self.assertEqual(-240, zone_offset_minutes("America/New_York", summer))
        self.assertEqual(-300, zone_offset_minutes("America/New_York", winter))
        for name in (None, "", "Not/AZone", "../etc", 9):
            with self.subTest(name=name):
                self.assertIsNone(zone_offset_minutes(name, summer))

    def test_record_accepts_only_quarter_hour_offsets_within_fourteen_hours(
        self,
    ) -> None:
        for offset in (-14 * 60, 0, 345, 14 * 60):
            self.assertEqual(offset, record(offset).local_offset_minutes)
        for bad in (7, 15 * 60, -15 * 60, True):
            with self.subTest(offset=bad), self.assertRaises(ValueError):
                record(bad)

    def test_wall_time_without_offset_uses_the_zone(self) -> None:
        self.assertEqual(
            date(2026, 10, 11), wall_time(TOKYO_MORNING, BERLIN, None).date()
        )


class ActivityDateTests(unittest.TestCase):
    def test_garmin_activity_abroad_is_dated_in_the_device_zone(self) -> None:
        payload = garmin_payload(
            startTimeGMT="2026-10-11 21:30:00", startTimeLocal="2026-10-12 06:30:00"
        )

        (item,) = canonical_plans.garmin_ingest_plan(payload, zone=BERLIN).activities

        self.assertEqual(JST_MINUTES, item.record.local_offset_minutes)
        self.assertEqual(date(2026, 10, 12), item.local_date)

    def test_intervals_activity_with_a_time_zone_is_dated_there(self) -> None:
        raw = intervals_raw(
            start_date="2026-10-11T21:30:00Z",
            start_date_local="2026-10-11T23:30:00",
            timezone="Asia/Tokyo",
        )

        (item,) = canonical_plans.intervals_ingest_plan(
            raw, zone=BERLIN, retrieved_at=RETRIEVED_AT
        ).activities

        self.assertEqual(JST_MINUTES, item.record.local_offset_minutes)
        self.assertEqual(date(2026, 10, 12), item.local_date)

    def test_intervals_local_start_gives_the_offset_without_a_time_zone(self) -> None:
        raw = intervals_raw(
            start_date="2026-10-11T00:00:00Z", start_date_local="2026-10-10T20:00:00"
        )

        (item,) = canonical_plans.intervals_ingest_plan(
            raw, zone=BERLIN, retrieved_at=RETRIEVED_AT
        ).activities

        # An evening ride in New York is not moved to the next Berlin day.
        self.assertEqual(-240, item.record.local_offset_minutes)
        self.assertEqual(date(2026, 10, 10), item.local_date)

    def test_without_an_offset_the_athlete_zone_dates_the_activity(self) -> None:
        cases = (
            canonical_plans.garmin_ingest_plan(
                garmin_payload(startTimeLocal="2026-10-11 23:30:00"), zone=BERLIN
            ),
            canonical_plans.intervals_ingest_plan(
                intervals_raw(
                    start_date_local="2026-10-11T23:30:00", timezone="Asia/Tokyo"
                ),
                zone=BERLIN,
                retrieved_at=RETRIEVED_AT,
            ),
        )
        for plan in cases:
            with self.subTest(provider=plan.provider):
                (item,) = plan.activities
                self.assertIsNone(item.record.local_offset_minutes)
                self.assertEqual(date(2026, 10, 11), item.local_date)

    def test_a_profile_zone_change_moves_only_activities_without_an_offset(
        self,
    ) -> None:
        with_offset = garmin_payload(
            startTimeGMT="2026-10-11 21:30:00", startTimeLocal="2026-10-12 06:30:00"
        )
        without_offset = garmin_payload(startTimeGMT="2026-10-11 22:30:00")

        self.assertEqual(date(2026, 10, 12), garmin_day(with_offset, BERLIN))
        self.assertEqual(date(2026, 10, 12), garmin_day(with_offset, NEW_YORK))
        self.assertEqual(date(2026, 10, 12), garmin_day(without_offset, BERLIN))
        self.assertEqual(date(2026, 10, 11), garmin_day(without_offset, NEW_YORK))

    def test_the_offset_survives_the_stored_details(self) -> None:
        details = canonical_store._activity_details(record(JST_MINUTES))

        values = canonical_store.activity_summary_values(details)

        self.assertEqual(JST_MINUTES, values["local_offset_minutes"])
        self.assertNotIn(
            "local_offset_minutes",
            canonical_store.activity_summary_values('{"local_offset_minutes": 7}'),
        )


class SummaryTests(unittest.TestCase):
    def test_summary_shows_the_lived_wall_time_and_keeps_its_day_and_week(
        self,
    ) -> None:
        summary = activity_summary("act_travel", [record(JST_MINUTES)], BERLIN)

        self.assertEqual("2026-10-12T06:30:00", summary["started_at_local"])
        self.assertEqual(JST_MINUTES, summary["local_offset_minutes"])
        # Readers that pass the athlete zone keep the lived Monday, so the
        # session counts in the ISO week it was trained in, not the one before.
        day = summary_local_date(summary, "Europe/Berlin")
        self.assertEqual("2026-10-12", day)
        self.assertEqual(42, date.fromisoformat(day).isocalendar().week)

    def test_summary_without_an_offset_keeps_the_athlete_zone(self) -> None:
        summary = activity_summary("act_home", [record(None)], BERLIN)

        self.assertEqual("2026-10-11T23:30:00", summary["started_at_local"])
        self.assertNotIn("local_offset_minutes", summary)
        self.assertEqual("2026-10-11", summary_local_date(summary, "Europe/Berlin"))
        self.assertEqual(41, date(2026, 10, 11).isocalendar().week)

    def test_a_session_takes_the_offset_of_any_record_that_reports_one(self) -> None:
        summary = activity_summary(
            "act_mixed",
            [record(None), record(JST_MINUTES, ProviderId.INTERVALS)],
            BERLIN,
        )

        self.assertEqual("2026-10-12T06:30:00", summary["started_at_local"])


class TravelDaySleepTests(unittest.TestCase):
    def test_garmin_sleep_and_morning_run_abroad_share_the_day(self) -> None:
        wake = datetime(2026, 10, 11, 21, 0, tzinfo=UTC)  # 06:00 in Tokyo
        element = {
            "calendarDate": "2026-10-12",
            "sleepStartTimestampGMT": int(
                (wake - timedelta(hours=8)).timestamp() * 1000
            ),
            "sleepEndTimestampGMT": int(wake.timestamp() * 1000),
        }
        (period,) = map_sleep_periods(
            element,
            provider=ProviderId.GARMIN,
            source_record_id="sleep/2026-10-12",
            retrieved_at=RETRIEVED_AT,
            zone=BERLIN,
        )
        (run,) = canonical_plans.garmin_ingest_plan(
            garmin_payload(
                startTimeGMT="2026-10-11 21:30:00",
                startTimeLocal="2026-10-12 06:30:00",
            ),
            zone=BERLIN,
        ).activities

        self.assertEqual(date(2026, 10, 12), period.wake_date)
        self.assertEqual(run.local_date, period.wake_date)
        # Berlin would name another day, so the period keeps no zone.
        self.assertIsNone(period.timezone)

    def test_intervals_wellness_day_dates_its_sleep(self) -> None:
        (period,) = map_sleep_periods(
            {
                "id": "2026-10-12",
                "sleep_start_at": "2026-10-11T13:00:00Z",
                "sleep_end_at": "2026-10-11T21:00:00Z",
            },
            provider=ProviderId.INTERVALS,
            source_record_id="2026-10-12",
            retrieved_at=RETRIEVED_AT,
            zone=BERLIN,
        )

        self.assertEqual(date(2026, 10, 12), period.wake_date)

    def test_a_provider_day_further_than_a_day_away_is_ignored(self) -> None:
        (period,) = map_sleep_periods(
            {
                "id": "2026-10-20",
                "sleep_start_at": "2026-10-09T22:00:00+02:00",
                "sleep_end_at": "2026-10-10T06:00:00+02:00",
            },
            provider=ProviderId.INTERVALS,
            source_record_id="2026-10-20",
            retrieved_at=RETRIEVED_AT,
            zone=BERLIN,
        )

        self.assertEqual(date(2026, 10, 10), period.wake_date)
        self.assertEqual("Europe/Berlin", period.timezone)


if __name__ == "__main__":
    unittest.main()
