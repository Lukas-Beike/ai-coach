"""Production wiring of the providers in server.py."""

from __future__ import annotations

import unittest

from server_test_support import server

from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID

SQLCIPHER_SKIP_REASON = "SQLCipher requires the Docker runtime on Windows"


class ProductionProviderWiringTests(unittest.TestCase):
    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, SQLCIPHER_SKIP_REASON)
    def test_every_provider_has_one_configured_check_and_resync_owners(self) -> None:
        self.assertEqual(
            set(DEFAULT_PROVIDER_REGISTRY.ids()), set(server.PROVIDER_CONFIGURED)
        )
        # Intervals.icu is an output target without a full resync (#1728).
        service = server.PROVIDER_RESYNC.full_resync_service()
        self.assertEqual({GARMIN_ID, WAHOO_ID}, set(service._handlers))

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, SQLCIPHER_SKIP_REASON)
    def test_schedulers_carry_a_policy_for_every_scheduled_provider(self) -> None:
        scheduled = {WEATHER_ID, CALENDAR_ID, GARMIN_ID, WAHOO_ID}
        schedulers = server.SYNC_SCHEDULERS

        self.assertEqual(scheduled, set(schedulers.daily_scheduler()._policies))
        self.assertEqual(scheduled, set(schedulers.startup_scheduler()._policies))
        self.assertEqual(scheduled, set(DEFAULT_PROVIDER_REGISTRY.daily_order()))

    def test_sync_period_defaults_are_derived_from_the_registry(self) -> None:
        self.assertEqual({"garmin": 84, "wahoo": 84}, server.SYNC_PERIOD_DEFAULTS)
        self.assertEqual(
            DEFAULT_PROVIDER_REGISTRY.sync_period_defaults(),
            server.SYNC_PERIOD_DEFAULTS,
        )


if __name__ == "__main__":
    unittest.main()
