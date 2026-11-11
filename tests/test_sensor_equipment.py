"""Reading the equipment link of a recorded sensor (#1869)."""

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.athlete.equipment import EquipmentService
from backend.canonical.activity_detail import ActivitySensor
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    HeartRateSource,
    PowerSource,
    ProviderId,
    RecordingOrigin,
    SensorRole,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db import DatabaseManager, row_factory
from backend.db.activity_detail_store import replace_detail_set
from backend.db.schema import initialize_schema

STAMP = "2026-11-09T08:00:00+00:00"
KEY = "ab" * 32
SERIAL = "3351234567"


class SensorEquipmentTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "sensors.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO activity_sessions(activity_id, primary_provider, "
                "primary_provider_activity_id, started_at, created_at, updated_at) "
                "VALUES ('act_1', 'garmin', 'g1', ?, ?, ?)",
                (STAMP, STAMP, STAMP),
            )
            db.execute(
                "INSERT INTO activity_records(provider, provider_activity_id, "
                "activity_id, state, mapper_version, source_kind, recorded_by, sport, "
                "environment, started_at, load_model, fetched_at, created_at, "
                "updated_at) VALUES ('garmin', 'g1', 'act_1', 'active', 1, "
                "'provider_reported', 'garmin', 'ride', 'outdoor', ?, 'unknown', ?, "
                "?, ?)",
                (STAMP, STAMP, STAMP, STAMP),
            )
            from backend.canonical.activity_detail import ActivityStreamSet

            replace_detail_set(
                db,
                ActivityStreamSet(
                    provider_activity_id="g1",
                    provenance=Provenance(
                        provider=ProviderId.GARMIN,
                        source_kind=SourceKind.PROVIDER_REPORTED,
                        source_record_id=None,
                        recorded_by=RecordingOrigin.GARMIN,
                        retrieved_at=datetime(2026, 11, 9, 8, tzinfo=UTC),
                        label=None,
                    ),
                    origin=ActivityDetailOrigin.FETCH,
                    resolution=StreamResolution.FULL,
                    channels={
                        StreamChannel.TIME_S: (0.0, 1.0),
                        StreamChannel.POWER_W: (200.0, 210.0),
                    },
                    hr_source=HeartRateSource.UNKNOWN,
                    power_source=PowerSource.POWER_METER,
                    sensors=(
                        ActivitySensor(
                            role=SensorRole.POWER_METER,
                            key=KEY,
                            connection="antplus",
                            manufacturer=7,
                            product=5,
                        ),
                    ),
                ),
                mapper_version=4,
                summary_sha256=None,
                now=STAMP,
            )
        self.service = EquipmentService(
            self.manager,
            list,
            lambda: datetime(2026, 11, 9, tzinfo=UTC).date(),
            lambda: STAMP,
        )
        made = {}
        for name in ("bike", "old"):
            made[name] = self.service.save(
                {
                    "name": name,
                    "sport": "Ride",
                    "kind": "bike",
                    "start_date": "2026-01-01",
                    "initial_distance_km": 0,
                    "initial_hours": 0,
                }
            )["equipment"]
        self.service.save(
            {
                "id": made["old"]["id"],
                "expected_revision": made["old"]["revision"],
                "name": "old",
                "sport": "Ride",
                "kind": "bike",
                "status": "archived",
                "start_date": "2026-01-01",
                "initial_distance_km": 0,
                "initial_hours": 0,
            }
        )
        wheel = self.service.save(
            {
                "name": "wheel",
                "sport": "Ride",
                "kind": "component",
                "parent_id": made["bike"]["id"],
                "start_date": "2026-01-01",
                "initial_distance_km": 0,
                "initial_hours": 0,
            }
        )["equipment"]
        self.bike, self.old, self.wheel = (
            made["bike"]["id"],
            made["old"]["id"],
            wheel["id"],
        )

    def sensors(self):
        return self.service.read()["sensors"]

    def test_the_read_lists_the_sensor_with_its_short_id_and_no_equipment(self):
        (sensor,) = self.sensors()
        self.assertEqual(sensor["id"], KEY[:16])
        self.assertEqual(sensor["role"], "power_meter")
        self.assertIsNone(sensor["equipment_id"])
        self.assertEqual(sensor["sessions"], 1)

    def link_sensor(self, equipment_id):
        """Store a link as an earlier release wrote it."""
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                (
                    f"sensor_equipment:{KEY}",
                    json.dumps({"equipment_id": equipment_id, "observed_at": STAMP}),
                    STAMP,
                ),
            )

    def test_a_stored_link_to_active_main_equipment_is_reported(self):
        self.link_sensor(self.bike)
        self.assertEqual(self.sensors()[0]["equipment_id"], self.bike)

    def test_a_link_to_unknown_equipment_is_not_reported(self):
        self.link_sensor("gone")
        self.assertIsNone(self.sensors()[0]["equipment_id"])

    def test_the_read_never_carries_a_serial_number(self):
        self.link_sensor(self.bike)
        self.assertNotIn(SERIAL, json.dumps(self.service.read()))


if __name__ == "__main__":
    unittest.main()
