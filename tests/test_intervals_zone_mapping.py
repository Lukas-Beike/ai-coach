"""Canonical zone configurations from the stored Intervals.icu athlete record.

Synthetic sport settings only; no account, network or real data is used.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import (
    Environment,
    ProviderId,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)
from backend.providers import canonical_plans
from backend.providers.intervals_zone_mapping import map_intervals_zone_configurations

ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)
RIDE = {
    "types": ["Ride", "VirtualRide"],
    "ftp": 260,
    "indoor_ftp": 250,
    "lthr": 168,
    "max_hr": 190,
    "power_zones": [55, 75, 90, 105, 120, 150, 999],
    "hr_zones": [137, 153, 159, 168, 174, 179, 190],
}
RUN = {
    "types": ["Run"],
    "threshold_pace": 4.2,
    "pace_zones": [77.5, 87.7, 94.3, 100, 103.4, 111.5, 999],
}


def configurations(athlete: object) -> dict:
    return {
        (c.metric, c.sport, c.environment): c
        for c in map_intervals_zone_configurations(
            athlete, source_record_id="athlete", retrieved_at=RETRIEVED_AT
        )
    }


class ZoneMappingTests(unittest.TestCase):
    def test_every_zone_list_is_kept_with_its_threshold(self) -> None:
        found = configurations({"sportSettings": [RIDE, RUN]})
        self.assertEqual(
            sorted(
                (m.value, s.value, "-" if e is None else e.value) for m, s, e in found
            ),
            [
                ("heart_rate", "ride", "-"),
                ("pace", "run", "-"),
                ("power", "ride", "-"),
                ("power", "ride", "indoor"),
            ],
        )
        hr = found[(ZoneConfigurationMetric.HEART_RATE, Sport.RIDE, None)]
        self.assertEqual(hr.limits, (137, 153, 159, 168, 174, 179, 190))
        self.assertEqual(
            (hr.threshold, hr.maximum, hr.percent_limits), (168, 190, None)
        )
        power = found[(ZoneConfigurationMetric.POWER, Sport.RIDE, None)]
        self.assertEqual(power.percent_limits, (55, 75, 90, 105, 120, 150, 999))
        self.assertIs(power.percent_basis, ZonePercentBasis.THRESHOLD)
        self.assertEqual((power.threshold, power.limits), (260, None))
        indoor = found[(ZoneConfigurationMetric.POWER, Sport.RIDE, Environment.INDOOR)]
        self.assertEqual(indoor.threshold, 250)
        pace = found[(ZoneConfigurationMetric.PACE, Sport.RUN, None)]
        self.assertEqual(pace.threshold, 4.2)
        self.assertEqual(pace.provenance.provider, ProviderId.INTERVALS)
        self.assertIs(pace.provenance.source_kind, SourceKind.PROVIDER_REPORTED)
        self.assertEqual(pace.provenance.source_record_id, "athlete")

    def test_seconds_per_km_threshold_pace_becomes_metres_per_second(self) -> None:
        found = configurations({"sport_settings": [{**RUN, "threshold_pace": 250}]})
        self.assertEqual(
            found[(ZoneConfigurationMetric.PACE, Sport.RUN, None)].threshold, 4.0
        )

    def test_the_first_setting_of_a_sport_wins(self) -> None:
        found = configurations(
            {"sportSettings": [RIDE, {**RIDE, "ftp": 300, "types": ["Ride"]}]}
        )
        self.assertEqual(
            found[(ZoneConfigurationMetric.POWER, Sport.RIDE, None)].threshold, 260
        )

    def test_invalid_lists_are_left_out_without_dropping_the_rest(self) -> None:
        for zones in (
            [55, 75],
            [55, 75, 90, 105, 120, 150, 200, 999],
            [55, 90, 75],
            [55, "75", 90],
            [0, 75, 90],
            "55,75,90",
        ):
            with self.subTest(zones=zones):
                found = configurations(
                    {"sportSettings": [{**RIDE, "power_zones": zones}]}
                )
                self.assertNotIn(
                    (ZoneConfigurationMetric.POWER, Sport.RIDE, None), found
                )
                self.assertIn(
                    (ZoneConfigurationMetric.HEART_RATE, Sport.RIDE, None), found
                )

    def test_out_of_bounds_heart_rate_limits_are_left_out(self) -> None:
        found = configurations(
            {
                "sportSettings": [
                    {**RIDE, "hr_zones": [137, 153, 159, 168, 174, 179, 999]}
                ]
            }
        )
        self.assertNotIn((ZoneConfigurationMetric.HEART_RATE, Sport.RIDE, None), found)
        self.assertIn((ZoneConfigurationMetric.POWER, Sport.RIDE, None), found)

    def test_missing_settings_have_no_configuration(self) -> None:
        for athlete in (
            {},
            {"sportSettings": "x"},
            "junk",
            {"sportSettings": [{"types": ["Ride"], "ftp": 250}]},
        ):
            with self.subTest(athlete=athlete):
                self.assertEqual(configurations(athlete), {})


class MalformedZoneTests(unittest.TestCase):
    def test_numbers_beyond_the_float_range_are_skipped_not_raised(self) -> None:
        found = configurations(
            {
                "sportSettings": [
                    {**RIDE, "lthr": 10**400, "hr_zones": [120, 140, 10**400]},
                    {**RUN, "threshold_pace": 10**400},
                ]
            }
        )
        self.assertNotIn((ZoneConfigurationMetric.HEART_RATE, Sport.RIDE, None), found)
        pace = found[ZoneConfigurationMetric.PACE, Sport.RUN, None]
        self.assertIsNone(pace.threshold)


class PlanTests(unittest.TestCase):
    def test_athlete_record_carries_its_zones_and_reprojects_them(self) -> None:
        athlete = {"id": "i1", "sportSettings": [RIDE, RUN]}
        plan = canonical_plans.intervals_ingest_plan(
            {"athlete": athlete}, zone=ZONE, retrieved_at=RETRIEVED_AT
        )
        (batch,) = plan.domain_batches
        self.assertEqual(batch.source_record_id, canonical_plans.ATHLETE_RECORD_ID)
        self.assertEqual(len(batch.zones), 4)
        reprojected = canonical_plans.reprojection_plan(
            {
                "provider": "intervals",
                "record_kind": canonical_plans.ATHLETE_RECORD_KIND,
                "source_record_id": canonical_plans.ATHLETE_RECORD_ID,
                "payload": json.dumps(athlete),
                "fetched_at": RETRIEVED_AT.isoformat(),
            },
            zone=ZONE,
        )
        assert reprojected is not None
        self.assertEqual(reprojected.domain_batches, (batch,))


if __name__ == "__main__":
    unittest.main()
