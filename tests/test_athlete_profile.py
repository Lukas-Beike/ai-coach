import os
import unittest

from backend.athlete.profile import (
    DEFAULT_PROFILE,
    DEFAULT_TIMEZONE,
    normalize_profile,
    timezone_name,
)
from backend.errors import AppError


class AthleteProfileTests(unittest.TestCase):
    def test_defaults_preserve_profile_contract_and_import_time_timezone_fallback(self):
        self.assertEqual(
            DEFAULT_PROFILE,
            {
                "name": "",
                "goals": "",
                "sports": "Cycling",
                "training_background": "",
                "typical_weekly_volume": "",
                "availability": "",
                "constraints": "",
                "equipment": "",
                "training_preferences": "",
                "performance_notes": "",
                "weight_kg": "",
                "body_fat_pct": "",
                "height_cm": "",
                "coaching_style": "Supportive, direct, and evidence-aware",
                "timezone": os.environ.get("TZ", DEFAULT_TIMEZONE),
                "weather_location": "",
            },
        )

    def test_unknown_fields_are_ignored(self):
        result = normalize_profile({"name": "Ada", "admin": True})
        self.assertEqual(result["name"], "Ada")
        self.assertNotIn("admin", result)

    def test_known_values_are_stringified_trimmed_and_limited(self):
        result = normalize_profile({"name": "  Ada  ", "weight_kg": 72, "goals": " x " * 5000})
        self.assertEqual(result["name"], "Ada")
        self.assertEqual(result["weight_kg"], "72")
        self.assertEqual(len(result["goals"]), 4000)
        self.assertEqual(result["goals"], (" x " * 5000).strip()[:4000])

    def test_timezone_name_accepts_valid_iana_timezone(self):
        self.assertEqual(timezone_name("  UTC  "), "UTC")

    def test_timezone_name_falls_back_for_invalid_non_strict_value(self):
        self.assertEqual(timezone_name("Mars/NotAZone"), DEFAULT_TIMEZONE)

    def test_timezone_name_raises_exact_strict_error(self):
        with self.assertRaises(AppError) as raised:
            timezone_name("Mars/NotAZone", strict=True)
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, "Die Zeitzone muss eine gültige IANA-Zeitzone sein.")

    def test_normalize_profile_validates_timezone_only_when_requested(self):
        invalid = {"timezone": "Mars/NotAZone"}
        self.assertEqual(normalize_profile(invalid)["timezone"], DEFAULT_TIMEZONE)
        with self.assertRaises(AppError):
            normalize_profile(invalid, validate_timezone=True)

    def test_normalize_profile_does_not_mutate_input(self):
        value = {"name": "  Ada  ", "timezone": "UTC", "unknown": ["keep"]}
        original = {key: item.copy() if isinstance(item, list) else item for key, item in value.items()}
        normalize_profile(value, validate_timezone=True)
        self.assertEqual(value, original)


if __name__ == "__main__":
    unittest.main()
