import unittest

from backend.canonical.vocabulary import ProviderId
from backend.performance.display_sources import PREFERRED_PROVIDER, preferred_providers


class DisplaySourcesTests(unittest.TestCase):
    def test_payload_maps_each_policy_key_to_its_provider_id_value(self):
        payload = preferred_providers()

        self.assertEqual(set(payload), set(PREFERRED_PROVIDER))
        for key, provider in PREFERRED_PROVIDER.items():
            self.assertIs(type(payload[key]), str)
            self.assertEqual(payload[key], provider.value)

    def test_policy_keeps_the_pwa_display_preferences(self):
        payload = preferred_providers()

        self.assertEqual(payload["cycling_eftp_watts"], ProviderId.INTERVALS.value)
        self.assertEqual(payload["cycling_ftp_watts"], ProviderId.GARMIN.value)
        self.assertEqual(payload["weight_kg"], ProviderId.GARMIN.value)
        self.assertEqual(payload["cycling_w_per_kg"], ProviderId.GARMIN.value)
        self.assertEqual(payload["sleep"], ProviderId.INTERVALS.value)
        self.assertEqual(payload["hrv"], ProviderId.INTERVALS.value)
        self.assertEqual(payload["resting_hr"], ProviderId.INTERVALS.value)

    def test_each_call_returns_a_fresh_mapping(self):
        first = preferred_providers()
        first["sleep"] = "changed"

        self.assertEqual(preferred_providers()["sleep"], ProviderId.INTERVALS.value)


if __name__ == "__main__":
    unittest.main()
