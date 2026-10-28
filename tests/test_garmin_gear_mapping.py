"""Canonical gear and gear-to-activity links from stored Garmin gear elements.

Synthetic gear only; no account, network or real data is used.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.canonical.vocabulary import ProviderId
from backend.providers import canonical_plans
from backend.providers.garmin_gear_mapping import map_garmin_gear

ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)
GEAR = {
    "gearUUID": "synthetic-gear-001",
    "gearName": "Synthetic Road Bike",
    "gearTypeName": "Bike",
    "activityTypeName": "Cycling",
    "gearStatusName": "active",
    "maximumMeters": 10_000_000,
    "stats": {"totalDistance": 1_520_000.0, "totalActivities": 41},
    "activity_ids": ["910010", "910011", "910010"],
}


def gear(element: object) -> tuple:
    return map_garmin_gear(
        element, source_record_id="gear/g1", retrieved_at=RETRIEVED_AT
    )


class GearMappingTests(unittest.TestCase):
    def test_item_labels_totals_and_distinct_links(self) -> None:
        (item,), links = gear(GEAR)
        self.assertEqual(
            (
                item.gear_id,
                item.name,
                item.type_label,
                item.activity_type_label,
                item.status_label,
                item.maximum_distance_m,
                item.total_distance_m,
                item.total_activities,
            ),
            (
                "synthetic-gear-001",
                "Synthetic Road Bike",
                "Bike",
                "Cycling",
                "active",
                10_000_000,
                1_520_000.0,
                41,
            ),
        )
        self.assertEqual(item.provenance.provider, ProviderId.GARMIN)
        self.assertEqual(
            [(link.gear_id, link.provider_activity_id) for link in links],
            [("synthetic-gear-001", "910010"), ("synthetic-gear-001", "910011")],
        )

    def test_unknown_links_emit_none(self) -> None:
        element = {key: value for key, value in GEAR.items() if key != "activity_ids"}
        (_item,), links = gear(element)
        self.assertEqual(links, ())

    def test_implausible_totals_are_left_out_without_dropping_the_item(self) -> None:
        (item,), _links = gear(
            {**GEAR, "maximumMeters": -5, "stats": {"totalActivities": 1.5}}
        )
        self.assertIsNone(item.maximum_distance_m)
        self.assertIsNone(item.total_activities)

    def test_gear_without_an_id_is_not_mapped(self) -> None:
        for element in ({**GEAR, "gearUUID": ""}, "junk", {"gearName": "x"}):
            with self.subTest(element=element):
                self.assertEqual(gear(element), ((), ()))


class MalformedGearTests(unittest.TestCase):
    def test_an_overlong_activity_id_is_skipped_not_raised(self) -> None:
        (item,), links = gear({**GEAR, "activity_ids": ["9" * 300, "910010"]})
        self.assertEqual([link.provider_activity_id for link in links], ["910010"])
        self.assertEqual(item.gear_id, "synthetic-gear-001")


class PlanTests(unittest.TestCase):
    def test_gear_elements_carry_their_batch_and_reproject_it(self) -> None:
        plan = canonical_plans.garmin_ingest_plan(
            {"synced_at": "2026-10-11T06:00:00+00:00", "gear": [GEAR]}, zone=ZONE
        )
        (raw,) = plan.raw_records
        (batch,) = plan.domain_batches
        self.assertEqual(batch.source_record_id, raw.source_record_id)
        self.assertEqual(len(batch.gear_items), 1)
        self.assertEqual(len(batch.gear_links), 2)
        reprojected = canonical_plans.reprojection_plan(
            {
                "provider": "garmin",
                "record_kind": raw.record_kind,
                "source_record_id": raw.source_record_id,
                "payload": json.dumps(raw.payload),
                "fetched_at": (raw.retrieved_at or RETRIEVED_AT).isoformat(),
            },
            zone=ZONE,
        )
        assert reprojected is not None
        self.assertEqual(reprojected.domain_batches, (batch,))


if __name__ == "__main__":
    unittest.main()
