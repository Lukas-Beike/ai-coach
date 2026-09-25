"""Server integration tests for athlete."""

import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.athlete.checkins import normalize_checkin
from server_test_support import server, ServerTestCase


class ServerAthleteTests(ServerTestCase):

    def test_profile_only_accepts_known_fields_and_trims(self):
        profile = server.normalize_profile({"name": "  Ada  ", "goals": "Finish strong", "admin": True})
        self.assertEqual(profile["name"], "Ada")
        self.assertNotIn("admin", profile)

    def test_profile_timezone_is_validated_and_local_now_uses_it(self):
        with self.assertRaises(server.AppError) as raised:
            server.profile_service().save({"timezone": "Mars/NotAZone"})
        self.assertEqual(raised.exception.status, 400)
        profile = server.profile_service().save({"timezone": "UTC"})
        self.assertEqual(profile["timezone"], "UTC")
        self.assertEqual(getattr(server.ATHLETE_CLOCK.now().tzinfo, "key", None), "UTC")

    def test_structured_weekly_availability_is_not_part_of_profile(self):
        profile = server.normalize_profile({
            "availability": "Dienstag abends möglich",
            "availability_schedule": [{"weekday": 1, "late": {"start": "17:30", "end": "20:00"}}],
        }, validate_timezone=True)
        self.assertEqual(profile["availability"], "Dienstag abends möglich")
        self.assertNotIn("availability_schedule", profile)
        server.profile_service().save({
            "availability": profile["availability"],
            "availability_schedule": [{"weekday": 1, "max_minutes": 90}],
        })
        self.assertNotIn("availability_schedule", server.profile_service().get())
        context = server.coach_structured_context_service().build({"recent_activities": [], "recent_wellness": [], "upcoming_calendar": []})
        self.assertNotIn("weekly_availability", context)

    def test_checkin_uses_local_date_and_rejects_future_dates(self):
        fixed_now = datetime(2026, 8, 31, 23, 30)
        with patch.object(server.ATHLETE_CLOCK, "now", return_value=fixed_now):
            self.assertEqual(
                normalize_checkin({}, today=fixed_now.date())["checkin_date"],
                "2026-08-31",
            )
            with self.assertRaises(server.AppError) as raised:
                server.checkin_service().save({"checkin_date": "2026-09-01"})
        self.assertEqual(raised.exception.status, 400)

    def test_profile_save_resets_button_before_follow_up_refresh(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        save_profile = app[app.index("async function saveProfile"):app.index("function registerServiceWorker")]
        self.assertIn(
            'button.removeAttribute("aria-busy");\n      button.textContent = buttonLabel;\n    }\n    await load();',
            save_profile,
        )


if __name__ == "__main__":
    unittest.main()
