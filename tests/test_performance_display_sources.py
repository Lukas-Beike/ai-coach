import unittest

from backend.canonical.vocabulary import ProviderId
from backend.performance.display_sources import (
    _DISPLAY_KINDS,
    _DISPLAY_ONLY,
    preferred_providers,
)
from backend.performance.source_policy import CURRENT_RULES, preferences_from_profile


class DisplaySourcesTests(unittest.TestCase):
    def test_derived_preferences_equal_the_selection_policy(self) -> None:
        payload = preferred_providers()

        for key, kind in _DISPLAY_KINDS.items():
            self.assertEqual(payload[key], CURRENT_RULES[kind].order[0].value, key)
        self.assertNotIn("cycling_eftp_watts", payload)
        self.assertEqual(
            payload["run_threshold_pace_seconds_per_km"], ProviderId.GARMIN.value
        )

    def test_display_only_keys_keep_the_chart_providers(self) -> None:
        payload = preferred_providers()

        # The FTP history and the FTP-based W/kg series exist only for Garmin.
        self.assertEqual(payload["cycling_ftp_watts"], ProviderId.GARMIN.value)
        self.assertEqual(payload["cycling_w_per_kg"], ProviderId.GARMIN.value)
        self.assertFalse(set(_DISPLAY_ONLY) & set(_DISPLAY_KINDS))

    def test_body_and_recovery_follow_the_policy(self) -> None:
        payload = preferred_providers()

        for key in ("weight_kg", "body_fat_pct", "sleep", "hrv", "resting_hr"):
            self.assertIn(key, _DISPLAY_KINDS)
            self.assertEqual(payload[key], ProviderId.GARMIN.value, key)

    def test_each_call_returns_a_fresh_mapping(self):
        first = preferred_providers()
        first["sleep"] = "changed"

        self.assertEqual(preferred_providers()["sleep"], ProviderId.GARMIN.value)


class PreferredDisplayTests(unittest.TestCase):
    def test_a_preferred_group_source_replaces_its_display_keys(self):
        payload = preferred_providers(
            preferences_from_profile(
                {
                    "preferred_source_hrv": "garmin",
                    "preferred_source_body": "garmin",
                    "preferred_source_resting_hr": "intervals",
                }
            )
        )

        self.assertEqual(payload["hrv"], ProviderId.GARMIN.value)
        self.assertEqual(payload["weight_kg"], ProviderId.GARMIN.value)
        self.assertEqual(payload["body_fat_pct"], ProviderId.GARMIN.value)
        # A stored Intervals.icu preference is ignored.
        self.assertEqual(payload["resting_hr"], ProviderId.GARMIN.value)
        self.assertEqual(payload["cycling_ftp_watts"], ProviderId.GARMIN.value)


if __name__ == "__main__":
    unittest.main()
