import unittest

from backend.canonical.vocabulary import ProviderId
from backend.performance.display_sources import (
    _DISPLAY_KINDS,
    PREFERRED_PROVIDER,
    preferred_providers,
)
from backend.performance.source_policy import CURRENT_RULES


class DisplaySourcesTests(unittest.TestCase):
    def test_payload_maps_each_policy_key_to_its_provider_id_value(self):
        payload = preferred_providers()

        self.assertEqual(set(payload), set(PREFERRED_PROVIDER))
        for key, provider in PREFERRED_PROVIDER.items():
            self.assertIs(type(payload[key]), str)
            self.assertEqual(payload[key], provider.value)

    def test_display_preferences_equal_the_selection_policy(self):
        payload = preferred_providers()

        for key, kind in _DISPLAY_KINDS.items():
            self.assertEqual(payload[key], CURRENT_RULES[kind].order[0].value, key)
        self.assertEqual(payload["cycling_eftp_watts"], ProviderId.INTERVALS.value)
        self.assertEqual(payload["cycling_ftp_watts"], ProviderId.INTERVALS.value)
        self.assertEqual(payload["cycling_w_per_kg"], ProviderId.INTERVALS.value)
        self.assertEqual(
            payload["run_threshold_pace_seconds_per_km"], ProviderId.GARMIN.value
        )
        self.assertEqual(payload["body_fat_pct"], ProviderId.INTERVALS.value)
        for key in ("sleep", "hrv", "resting_hr"):
            self.assertEqual(payload[key], ProviderId.GARMIN.value, key)

    def test_each_call_returns_a_fresh_mapping(self):
        first = preferred_providers()
        first["sleep"] = "changed"

        self.assertEqual(preferred_providers()["sleep"], ProviderId.GARMIN.value)


if __name__ == "__main__":
    unittest.main()
