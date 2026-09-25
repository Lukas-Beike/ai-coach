import unittest
from datetime import datetime, timedelta, timezone

from backend.athlete.clock import AthleteLocalClock


class AthleteLocalClockTests(unittest.TestCase):
    def test_uses_timezone_from_current_profile(self):
        profile = {"timezone": "America/Los_Angeles"}
        clock = AthleteLocalClock(
            lambda: profile["timezone"],
            lambda zone=None: datetime(2026, 1, 15, 12, tzinfo=zone),
        )

        result = clock.now()

        self.assertEqual(result.tzinfo.key, "America/Los_Angeles")
        self.assertEqual(result.utcoffset(), timedelta(hours=-8))

    def test_invalid_profile_timezone_uses_existing_default(self):
        clock = AthleteLocalClock(
            lambda: "not/a-timezone",
            lambda zone=None: datetime(2026, 1, 15, 12, tzinfo=zone),
        )

        self.assertEqual(clock.now().tzinfo.key, "Europe/Berlin")

    def test_timezone_lookup_failure_falls_back_to_system_local_time(self):
        def failing_clock(zone=None):
            if zone is not None:
                raise RuntimeError("timezone database unavailable")
            return datetime(2026, 1, 15, 12, tzinfo=timezone.utc)

        clock = AthleteLocalClock(lambda: "Europe/Berlin", failing_clock)

        self.assertEqual(clock.now(), datetime(2026, 1, 15, 12, tzinfo=timezone.utc).astimezone())


if __name__ == "__main__":
    unittest.main()
