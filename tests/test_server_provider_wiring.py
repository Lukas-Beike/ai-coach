"""Production wiring of the built-in provider runtime in server.py."""

from __future__ import annotations

import unittest

from server_test_support import server

from backend.providers.descriptors import (
    CALENDAR_ID,
    GARMIN_ID,
    INTERVALS_ID,
    WEATHER_ID,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY

SQLCIPHER_SKIP_REASON = "SQLCipher requires the Docker runtime on Windows"


class ProductionProviderWiringTests(unittest.TestCase):
    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, SQLCIPHER_SKIP_REASON)
    def test_runtime_binds_each_builtin_provider_once_in_descriptor_order(self) -> None:
        runtime = server.provider_runtime()
        expected = (INTERVALS_ID, GARMIN_ID, WEATHER_ID, CALENDAR_ID)

        self.assertEqual(expected, tuple(runtime.job_owners()))
        self.assertEqual(expected, tuple(runtime.freshness_sources()))
        self.assertEqual((INTERVALS_ID, GARMIN_ID), tuple(runtime.resync_handlers()))
        self.assertIs(DEFAULT_PROVIDER_REGISTRY, runtime.static)

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, SQLCIPHER_SKIP_REASON)
    def test_schedule_orders_follow_registry_ranks(self) -> None:
        policies = server.provider_runtime().schedule_policies()

        self.assertEqual(
            (WEATHER_ID, CALENDAR_ID, GARMIN_ID, INTERVALS_ID),
            tuple(policies["daily"]),
        )
        self.assertEqual(
            (CALENDAR_ID, INTERVALS_ID, GARMIN_ID, WEATHER_ID),
            tuple(policies["startup"]),
        )
        self.assertEqual(
            DEFAULT_PROVIDER_REGISTRY.daily_order(), tuple(policies["daily"])
        )
        self.assertEqual(
            DEFAULT_PROVIDER_REGISTRY.startup_order(), tuple(policies["startup"])
        )

    def test_sync_period_defaults_are_derived_from_the_registry(self) -> None:
        self.assertEqual({"intervals": 84, "garmin": 84}, server.SYNC_PERIOD_DEFAULTS)
        self.assertEqual(
            DEFAULT_PROVIDER_REGISTRY.sync_period_defaults(),
            server.SYNC_PERIOD_DEFAULTS,
        )

    def test_runtime_factory_returns_a_fresh_registry_per_build(self) -> None:
        self.assertIsNot(server.provider_runtime(), server.provider_runtime())


if __name__ == "__main__":
    unittest.main()
