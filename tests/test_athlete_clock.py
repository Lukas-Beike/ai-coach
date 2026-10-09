import threading
import unittest
from datetime import UTC, datetime, timedelta

from backend.athlete.clock import AthleteLocalClock
from backend.db.manager import DATABASE_LOCK


class Profile:
    def __init__(self, timezone_name: str):
        self.timezone_name = timezone_name

    def get(self) -> dict[str, str]:
        return {"timezone": self.timezone_name}


class AthleteLocalClockTests(unittest.TestCase):
    def test_profile_timezone_read_does_not_require_a_global_database_lock(self):
        clock = AthleteLocalClock(
            Profile("UTC"),
            lambda zone=None: datetime(2026, 1, 15, 12, tzinfo=zone),
        )

        self.assertEqual(clock.now().tzinfo.key, "UTC")

    def test_profile_timezone_read_does_not_wait_for_the_global_database_lock(self):
        entered = threading.Event()
        completed = threading.Event()
        clock = AthleteLocalClock(
            Profile("UTC"),
            lambda zone=None: datetime(2026, 1, 15, 12, tzinfo=zone),
        )

        def read_clock():
            entered.set()
            clock.now()
            completed.set()

        with DATABASE_LOCK:
            reader = threading.Thread(target=read_clock)
            reader.start()
            self.assertTrue(entered.wait(1))
            self.assertTrue(completed.wait(0.5))
        reader.join(1)
        self.assertFalse(reader.is_alive())

    def test_uses_timezone_from_current_profile(self):
        profile = Profile("America/Los_Angeles")
        clock = AthleteLocalClock(
            profile,
            lambda zone=None: datetime(2026, 1, 15, 12, tzinfo=zone),
        )

        result = clock.now()

        self.assertEqual(result.tzinfo.key, "America/Los_Angeles")
        self.assertEqual(result.utcoffset(), timedelta(hours=-8))
        profile.timezone_name = "UTC"
        self.assertEqual(clock.now().tzinfo.key, "UTC")

    def test_invalid_profile_timezone_uses_existing_default(self):
        clock = AthleteLocalClock(
            Profile("not/a-timezone"),
            lambda zone=None: datetime(2026, 1, 15, 12, tzinfo=zone),
        )

        self.assertEqual(clock.now().tzinfo.key, "Europe/Berlin")

    def test_timezone_lookup_failure_falls_back_to_system_local_time(self):
        def failing_clock(zone=None):
            if zone is not None:
                raise RuntimeError("timezone database unavailable")
            return datetime(2026, 1, 15, 12, tzinfo=UTC)

        clock = AthleteLocalClock(
            Profile("Europe/Berlin"),
            failing_clock,
        )

        self.assertEqual(
            clock.now(), datetime(2026, 1, 15, 12, tzinfo=UTC).astimezone()
        )

    def test_local_date_is_stable_across_utc_midnight(self):
        profile = Profile("Europe/Berlin")
        before = datetime(2026, 1, 1, 22, 59, tzinfo=UTC)
        after = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
        before_clock = AthleteLocalClock(
            profile, lambda zone=None: before.astimezone(zone)
        )
        after_clock = AthleteLocalClock(
            profile, lambda zone=None: after.astimezone(zone)
        )
        self.assertEqual(before_clock.now().date().isoformat(), "2026-01-01")
        self.assertEqual(after_clock.now().date().isoformat(), "2026-01-02")

    def test_local_time_skips_dst_gap(self):
        profile = Profile("Europe/Berlin")
        utc_times = iter(
            (
                datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
                datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
            )
        )
        clock = AthleteLocalClock(
            profile, lambda zone=None: next(utc_times).astimezone(zone)
        )
        self.assertEqual(clock.now().isoformat(), "2026-03-29T01:30:00+01:00")
        self.assertEqual(clock.now().isoformat(), "2026-03-29T03:30:00+02:00")

    def test_local_date_advances_across_dst_midnight(self):
        profile = Profile("Europe/Berlin")
        utc_times = iter(
            (
                datetime(2026, 10, 24, 21, 59, tzinfo=UTC),
                datetime(2026, 10, 24, 22, 0, tzinfo=UTC),
                datetime(2026, 10, 25, 1, 0, tzinfo=UTC),
            )
        )
        clock = AthleteLocalClock(
            profile, lambda zone=None: next(utc_times).astimezone(zone)
        )

        self.assertEqual(clock.now().isoformat(), "2026-10-24T23:59:00+02:00")
        self.assertEqual(clock.now().isoformat(), "2026-10-25T00:00:00+02:00")
        self.assertEqual(clock.now().isoformat(), "2026-10-25T02:00:00+01:00")


if __name__ == "__main__":
    unittest.main()
