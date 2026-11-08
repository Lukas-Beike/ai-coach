"""Card M3 v4: nights read outside the profile zone stay out of the timing comparison."""

import unittest
from datetime import UTC, date, datetime, timedelta

from backend.canonical.domain_records import SleepPeriod
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ProviderId,
    RecordingOrigin,
    SleepKind,
    SourceKind,
)
from backend.performance.personal_recovery import sleep_timing_variability

TODAY = date(2026, 10, 31)
BOUNDS = "sleepstarttimestampgmt.sleependtimestampgmt"
PROVENANCE = Provenance(
    provider=ProviderId.GARMIN,
    source_kind=SourceKind.DEVICE_MEASURED,
    source_record_id="night",
    recorded_by=RecordingOrigin.GARMIN,
    retrieved_at=datetime(2026, 10, 31, tzinfo=UTC),
    label="Garmin",
)


def _night(days_ago: int, *, onset_hour: int = 22, zone: str | None = "UTC"):
    wake = TODAY - timedelta(days=days_ago)
    # An onset from noon on falls on the evening before the wake day.
    start = datetime(wake.year, wake.month, wake.day, tzinfo=UTC) + timedelta(
        hours=onset_hour - (24 if onset_hour >= 12 else 0)
    )
    return SleepPeriod(
        start=start,
        end=start + timedelta(hours=8),
        wake_date=wake,
        kind=SleepKind.NIGHT,
        timezone=zone,
        reported_duration_s=8 * 3600,
        bounds_method=BOUNDS,
        provenance=PROVENANCE,
    )


def _series(periods):
    result = sleep_timing_variability("UTC", TODAY, periods=periods)
    return result["method"], result["series"][0]


class OtherTimezoneNightTests(unittest.TestCase):
    def test_travel_night_is_flagged_and_left_out_of_the_comparison(self):
        # 20 regular nights at 22:00; three nights ago one read in another zone
        # appears at 04:00 profile time.
        periods = [_night(days) for days in range(1, 21) if days != 3]
        periods.append(_night(3, onset_hour=4, zone=None))
        method, series = _series(periods)
        self.assertEqual("sleep-timing-variability-v3", method)
        self.assertEqual(18, series["coverage"]["baseline_nights"])
        self.assertEqual(0, series["baseline"]["onset_deviation_median_minutes"])
        travel = [point for point in series["points"] if point["other_timezone"]]
        self.assertEqual(1, len(travel))
        self.assertIsNone(travel[0]["onset_deviation_minutes"])
        regular = [p for p in series["points"] if not p["other_timezone"]]
        self.assertTrue(all(p["onset_deviation_minutes"] == 0 for p in regular))

    def test_travel_night_never_displaces_a_profile_zone_night_of_the_same_day(self):
        periods = [_night(days) for days in range(1, 21)]
        later_travel = _night(3, onset_hour=23, zone=None)
        _method, series = _series([*periods, later_travel])
        day = (TODAY - timedelta(days=3)).isoformat()
        kept = [p for p in series["points_84"] if p["date"] == day]
        self.assertEqual([False], [p["other_timezone"] for p in kept])


if __name__ == "__main__":
    unittest.main()
