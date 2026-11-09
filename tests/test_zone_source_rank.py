"""Which zone configuration applies when several sources hold one (#1826)."""

from __future__ import annotations

import unittest

from canonical_domain_support import (
    local_zone_configuration,
    provenance,
    zone_configuration,
)

from backend.activities.zone_settings import effective_zone_configuration
from backend.canonical.vocabulary import ProviderId, Sport, ZoneConfigurationMetric

METRIC = ZoneConfigurationMetric.HEART_RATE


def configuration(provider: ProviderId, threshold: float):
    return zone_configuration(
        threshold=threshold, provenance=provenance("zones", provider=provider)
    )


def chosen(*configurations):
    result = effective_zone_configuration(configurations, METRIC, Sport.RUN)
    assert result is not None
    return result.threshold


class ZoneSourceRankTests(unittest.TestCase):
    def test_the_provider_order_is_garmin_wahoo_then_output_only_intervals(
        self,
    ) -> None:
        garmin = configuration(ProviderId.GARMIN, 170.0)
        wahoo = configuration(ProviderId.WAHOO, 171.0)
        intervals = configuration(ProviderId.INTERVALS, 172.0)
        self.assertEqual(chosen(intervals, wahoo, garmin), 170.0)
        self.assertEqual(chosen(intervals, wahoo), 171.0)
        self.assertEqual(chosen(intervals), 172.0)

    def test_a_confirmed_local_value_beats_every_provider(self) -> None:
        local = local_zone_configuration(threshold=165.0)
        garmin = configuration(ProviderId.GARMIN, 170.0)
        self.assertEqual(chosen(garmin, local), 165.0)


if __name__ == "__main__":
    unittest.main()
