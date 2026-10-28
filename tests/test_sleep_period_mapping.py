"""Canonical sleep periods from stored Garmin sleep and Intervals.icu wellness rows.

Synthetic rows only; no account, network or real data is used.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.sleep_bounds import bounds_fields, bounds_method
from backend.canonical.vocabulary import ProviderId, SleepKind, SourceKind
from backend.performance import personal_recovery
from backend.providers import canonical_plans
from backend.providers.sleep_period_mapping import map_sleep_periods

ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)


def epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def garmin_night(start: datetime, hours: float = 8, **extra: Any) -> dict[str, Any]:
    return {
        "calendarDate": (start + timedelta(hours=hours)).date().isoformat(),
        "sleepStartTimestampGMT": epoch_ms(start),
        "sleepEndTimestampGMT": epoch_ms(start + timedelta(hours=hours)),
        "sleepTimeSeconds": int(hours * 3600) - 600,
        **extra,
    }


def garmin(element: object, source_id: str = "sleep/2026-10-10") -> tuple:
    return map_sleep_periods(
        element,
        provider=ProviderId.GARMIN,
        source_record_id=source_id,
        retrieved_at=RETRIEVED_AT,
        zone=ZONE,
    )


class GarminSleepTests(unittest.TestCase):
    def test_daily_sleep_record_is_the_main_night(self) -> None:
        start = datetime(2026, 10, 9, 21, 30, tzinfo=UTC)
        (period,) = garmin(garmin_night(start))
        self.assertIs(period.kind, SleepKind.NIGHT)
        self.assertEqual(period.start, start)
        self.assertEqual(period.end, start + timedelta(hours=8))
        self.assertEqual(period.wake_date, date(2026, 10, 10))
        self.assertEqual(period.timezone, "Europe/Berlin")
        self.assertEqual(period.reported_duration_s, 8 * 3600 - 600)
        self.assertEqual(
            period.bounds_method, "sleepstarttimestampgmt.sleependtimestampgmt"
        )
        self.assertIs(period.provenance.source_kind, SourceKind.DEVICE_MEASURED)
        self.assertEqual(period.provenance.source_record_id, "sleep/2026-10-10")
        self.assertTrue(period.provenance.context.is_unknown)

    def test_daytime_main_sleep_of_a_shift_worker_is_night(self) -> None:
        (period,) = garmin(garmin_night(datetime(2026, 10, 10, 7, 0, tzinfo=UTC), 7))
        self.assertIs(period.kind, SleepKind.NIGHT)

    def test_daily_sleep_dto_is_the_main_night_and_deeper_objects_are_unknown(
        self,
    ) -> None:
        night = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
        other = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
        periods = garmin(
            {
                "dailySleepDTO": garmin_night(night),
                "extra": [garmin_night(other, 1)],
            }
        )
        self.assertEqual(
            sorted((p.start, p.kind) for p in periods),
            [(night, SleepKind.NIGHT), (other, SleepKind.UNKNOWN)],
        )

    def test_midnight_and_dst_keep_the_true_duration_and_the_wake_date(self) -> None:
        # Berlin leaves summer time at 01:00 UTC on 2026-10-25.
        start = datetime(2026, 10, 24, 21, 0, tzinfo=UTC)
        (period,) = garmin(garmin_night(start, 9))
        self.assertEqual(period.end - period.start, timedelta(hours=9))
        self.assertEqual(period.wake_date, date(2026, 10, 25))

    def test_invalid_reversed_and_overlong_intervals_are_skipped(self) -> None:
        start = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
        for element in (
            {"sleepStartTimestampGMT": "soon", "sleepEndTimestampGMT": 5},
            {
                "sleepStartTimestampGMT": epoch_ms(start),
                "sleepEndTimestampGMT": epoch_ms(start - timedelta(hours=1)),
            },
            garmin_night(start, 25),
            {"sleepTimeSeconds": 25_000},
            "junk",
        ):
            with self.subTest(element=element):
                self.assertEqual(garmin(element), ())

    def test_repeated_instants_are_one_period(self) -> None:
        start = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
        night = garmin_night(start)
        (period,) = garmin({"dailySleepDTO": night, "copy": dict(night)})
        self.assertEqual(period.start, start)

    def test_implausible_reported_duration_is_left_out(self) -> None:
        start = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
        (period,) = garmin(garmin_night(start, sleepTimeSeconds=999_999))
        self.assertIsNone(period.reported_duration_s)


class IntervalsSleepTests(unittest.TestCase):
    def test_wellness_bounds_are_an_unknown_kind_provider_period(self) -> None:
        (period,) = map_sleep_periods(
            {
                "id": "2026-10-10",
                "sleep_start_at": "2026-10-09T22:15:00+02:00",
                "sleep_end_at": "2026-10-10T06:45:00+02:00",
                "sleepSecs": 28_800,
            },
            provider=ProviderId.INTERVALS,
            source_record_id="2026-10-10",
            retrieved_at=RETRIEVED_AT,
            zone=ZONE,
        )
        self.assertIs(period.kind, SleepKind.UNKNOWN)
        self.assertEqual(period.reported_duration_s, 28_800)
        self.assertEqual(period.bounds_method, "sleep_start_at.sleep_end_at")
        self.assertIs(period.provenance.source_kind, SourceKind.PROVIDER_REPORTED)

    def test_bounds_at_the_edge_of_the_datetime_range_are_skipped(self) -> None:
        self.assertEqual(
            map_sleep_periods(
                {
                    "id": "2026-10-10",
                    "sleep_start_at": "0001-01-01T00:30:00+01:00",
                    "sleep_end_at": "0001-01-01T05:30:00+01:00",
                },
                provider=ProviderId.INTERVALS,
                source_record_id="2026-10-10",
                retrieved_at=RETRIEVED_AT,
                zone=ZONE,
            ),
            (),
        )

    def test_wellness_without_bounds_has_no_period(self) -> None:
        self.assertEqual(
            map_sleep_periods(
                {"id": "2026-10-10", "sleepSecs": 28_800},
                provider=ProviderId.INTERVALS,
                source_record_id="2026-10-10",
                retrieved_at=RETRIEVED_AT,
                zone=ZONE,
            ),
            (),
        )


class BoundsMethodTests(unittest.TestCase):
    def test_every_field_pair_round_trips(self) -> None:
        from backend.canonical.sleep_bounds import SLEEP_END_FIELDS, SLEEP_START_FIELDS

        for start in SLEEP_START_FIELDS:
            for end in SLEEP_END_FIELDS:
                self.assertEqual(bounds_fields(bounds_method(start, end)), (start, end))
        self.assertIsNone(bounds_fields("unknown.pair"))

    def test_regularity_reads_the_same_intervals(self) -> None:
        """The mapper and sleep-timing-variability-v1 find the same instants and field pairs."""
        today = date(2026, 10, 12)
        nights = [
            garmin_night(datetime(2026, 10, day, 21, 0, tzinfo=UTC)) for day in (8, 9)
        ]
        legacy = personal_recovery._sleep_intervals(nights, ZONE, today)
        mapped = [period for night in nights for period in garmin(night)]
        self.assertEqual(
            sorted(
                (item["onset_at_utc"], item["wake_at_utc"], item["method"])
                for item in legacy
            ),
            sorted(
                (
                    period.start.isoformat(),
                    period.end.isoformat(),
                    "/".join(bounds_fields(period.bounds_method or "") or ()),
                )
                for period in mapped
            ),
        )


class PlanTests(unittest.TestCase):
    def test_garmin_sleep_records_carry_their_batch_and_reproject_without_refetch(
        self,
    ) -> None:
        start = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
        payload = {
            "synced_at": "2026-10-11T06:00:00+00:00",
            "sleep": [garmin_night(start)],
        }
        plan = canonical_plans.garmin_ingest_plan(payload, zone=ZONE)
        (raw,) = [r for r in plan.raw_records if r.source_record_id.startswith("sleep")]
        (batch,) = plan.domain_batches
        self.assertEqual(batch.source_record_id, raw.source_record_id)
        self.assertEqual(batch.mapper_version, canonical_plans.GARMIN_HEALTH_VERSION)
        self.assertEqual(len(batch.sleep_periods), 1)

        stored = {
            "provider": "garmin",
            "record_kind": raw.record_kind,
            "source_record_id": raw.source_record_id,
            "payload": json.dumps(raw.payload),
            "fetched_at": (raw.retrieved_at or RETRIEVED_AT).isoformat(),
        }
        reprojected = canonical_plans.reprojection_plan(stored, zone=ZONE)
        self.assertIsNotNone(reprojected)
        assert reprojected is not None
        self.assertEqual(reprojected.domain_batches, (batch,))

    def test_other_garmin_sections_carry_no_batch(self) -> None:
        plan = canonical_plans.garmin_ingest_plan(
            {
                "synced_at": "2026-10-11T06:00:00+00:00",
                "resting_hr": [{"calendarDate": "2026-10-10", "restingHeartRate": 48}],
            },
            zone=ZONE,
        )
        self.assertEqual(plan.domain_batches, ())

    def test_every_wellness_row_carries_a_batch_and_reprojects_it(self) -> None:
        row = {
            "id": "2026-10-10",
            "sleep_start_at": "2026-10-09T22:15:00+02:00",
            "sleep_end_at": "2026-10-10T06:45:00+02:00",
        }
        plan = canonical_plans.intervals_ingest_plan(
            {"wellness": [row, {"id": "2026-10-11"}]},
            zone=ZONE,
            retrieved_at=RETRIEVED_AT,
        )
        self.assertEqual(
            [(b.source_record_id, len(b.sleep_periods)) for b in plan.domain_batches],
            [("2026-10-10", 1), ("2026-10-11", 0)],
        )
        reprojected = canonical_plans.reprojection_plan(
            {
                "provider": "intervals",
                "record_kind": "wellness",
                "source_record_id": "2026-10-10",
                "payload": json.dumps(row),
                "fetched_at": RETRIEVED_AT.isoformat(),
            },
            zone=ZONE,
        )
        assert reprojected is not None
        self.assertEqual(reprojected.domain_batches, plan.domain_batches[:1])


if __name__ == "__main__":
    unittest.main()
