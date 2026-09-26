import unittest
from datetime import datetime, timedelta, timezone

from backend.athlete.clock import AthleteLocalClock


class Profile:
    def __init__(self, timezone_name: str):
        self.timezone_name = timezone_name

    def get(self) -> dict[str, str]:
        return {"timezone": self.timezone_name}


class AthleteLocalClockTests(unittest.TestCase):
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
            return datetime(2026, 1, 15, 12, tzinfo=timezone.utc)

        clock = AthleteLocalClock(
            Profile("Europe/Berlin"),
            failing_clock,
        )

        self.assertEqual(clock.now(), datetime(2026, 1, 15, 12, tzinfo=timezone.utc).astimezone())


if __name__ == "__main__":
    unittest.main()
