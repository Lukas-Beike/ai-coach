"""Sensor sources per channel, the sensor registry and the power meter marker (#1869)."""

import json
import sqlite3
import unittest
from datetime import UTC, date, datetime

from backend.activities.detail_merge import (
    DetailCandidate,
    channel_sources,
    merge_details,
)
from backend.canonical import sensor_registry
from backend.canonical.activity_detail import ActivitySensor, ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    DeviceType,
    HeartRateSource,
    PowerSource,
    ProviderId,
    RecordingOrigin,
    SensorRole,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db import activity_detail_store, row_factory
from backend.db.activity_detail_store import (
    StoredDetailSet,
    detail_sets_for,
    replace_detail_set,
)
from backend.db.canonical_store import WriteOutcome
from backend.db.schema import initialize_schema
from backend.providers.fit_activity_detail_mapping import map_fit_activity_detail
from tests.test_fit_sensor_mapping import GARMIN, device, fit_file

SERIAL = "3351234567"
STAMP = "2026-11-09T08:00:00+00:00"
DIGEST = "b" * 64


def key(label: str) -> str:
    return (label * 64)[:64]


def sensor(role: SensorRole, label: str) -> ActivitySensor:
    return ActivitySensor(
        role=role, key=key(label), connection="antplus", manufacturer=1, product=2
    )


def stream_set(
    activity="g1",
    *,
    provider=ProviderId.GARMIN,
    hr=HeartRateSource.CHEST_STRAP,
    power=PowerSource.POWER_METER,
    sensors=(),
    hr_values=(120.0, 121.0, 122.0),
    power_values=(200.0, 210.0, 220.0),
):
    return ActivityStreamSet(
        provider_activity_id=activity,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=datetime(2026, 11, 9, 8, tzinfo=UTC),
            label=None,
        ),
        origin=ActivityDetailOrigin.FETCH,
        resolution=StreamResolution.FULL,
        channels={
            StreamChannel.TIME_S: (0.0, 1.0, 2.0),
            StreamChannel.HEART_RATE_BPM: hr_values,
            StreamChannel.POWER_W: power_values,
        },
        hr_source=hr,
        power_source=power,
        sensors=tuple(sensors),
    )


def candidate(detail, device_type=None):
    return DetailCandidate(
        stored=StoredDetailSet(
            provider=detail.provenance.provider.value,
            provider_activity_id=detail.provider_activity_id,
            activity_id="act_s1",
            mapper_version=1,
            summary_sha256=None,
            fetched_at=STAMP,
            detail=detail,
        ),
        started_at=datetime(2026, 11, 9, 7, tzinfo=UTC),
        device_type=device_type,
    )


class RankingTests(unittest.TestCase):
    def test_a_chest_strap_beats_optical_heart_rate_whatever_the_device_class(self):
        watch_strap = candidate(
            stream_set("g1", hr=HeartRateSource.CHEST_STRAP, hr_values=(150.0,) * 3),
            DeviceType.WATCH,
        )
        computer_optical = candidate(
            stream_set(
                "w1",
                provider=ProviderId.WAHOO,
                hr=HeartRateSource.OPTICAL,
                hr_values=(90.0,) * 3,
            ),
            DeviceType.CHEST_STRAP,
        )
        merged = merge_details([computer_optical, watch_strap])
        assert merged.streams is not None
        choice = merged.streams.channels[StreamChannel.HEART_RATE_BPM]
        self.assertIs(choice.source, watch_strap)
        self.assertEqual(
            channel_sources(merged.streams)[0], HeartRateSource.CHEST_STRAP
        )

    def test_a_power_meter_beats_a_trainer_and_an_estimate(self):
        estimate = candidate(
            stream_set("w1", provider=ProviderId.WAHOO, power=PowerSource.ESTIMATED)
        )
        meter = candidate(stream_set("g1", power=PowerSource.POWER_METER))
        trainer = candidate(
            stream_set("g2", power=PowerSource.TRAINER, power_values=(1.0, 2.0, 3.0))
        )
        merged = merge_details([estimate, trainer, meter])
        assert merged.streams is not None
        self.assertIs(merged.streams.channels[StreamChannel.POWER_W].source, meter)

    def test_sets_without_a_source_keep_the_device_class_ranking(self):
        watch = candidate(
            stream_set("g1", hr=None, power=None, hr_values=(100.0,) * 3),
            DeviceType.WATCH,
        )
        strap = candidate(
            stream_set(
                "w1",
                provider=ProviderId.WAHOO,
                hr=None,
                power=None,
                hr_values=(99.0,) * 3,
            ),
            DeviceType.CHEST_STRAP,
        )
        merged = merge_details([watch, strap])
        assert merged.streams is not None
        self.assertIs(
            merged.streams.channels[StreamChannel.HEART_RATE_BPM].source, strap
        )


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.db.execute("PRAGMA foreign_keys = ON")

    def add(self, session, activity, started_at, sport="ride", state="active"):
        self.db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, state, started_at, created_at, updated_at) "
            "VALUES (?, 'garmin', ?, ?, ?, ?, ?)",
            (session, activity, state, started_at, STAMP, STAMP),
        )
        self.db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
            "state, mapper_version, source_kind, recorded_by, sport, environment, "
            "started_at, load_model, fetched_at, created_at, updated_at) "
            "VALUES ('garmin', ?, ?, 'active', 1, 'provider_reported', 'garmin', ?, "
            "'outdoor', ?, 'unknown', ?, ?, ?)",
            (activity, session, sport, started_at, STAMP, STAMP, STAMP),
        )

    def store(self, detail):
        return replace_detail_set(
            self.db, detail, mapper_version=4, summary_sha256=DIGEST, now=STAMP
        )


class StoreTests(StoreCase):
    def test_sources_and_sensors_round_trip_and_changes_rewrite_the_set(self):
        self.add("act_s1", "g1", "2026-11-01T07:00:00+00:00")
        detail = stream_set(sensors=[sensor(SensorRole.HEART_RATE, "a")])
        self.assertIs(self.store(detail), WriteOutcome.WRITTEN)
        (stored,) = detail_sets_for(self.db, "garmin", "g1")
        self.assertEqual(stored.detail, detail)
        self.assertIs(self.store(detail), WriteOutcome.UNCHANGED)
        changed = stream_set(hr=HeartRateSource.OPTICAL)
        self.assertIs(self.store(changed), WriteOutcome.UPDATED)
        (stored,) = detail_sets_for(self.db, "garmin", "g1")
        self.assertIs(stored.detail.hr_source, HeartRateSource.OPTICAL)
        self.assertEqual(stored.detail.sensors, ())

    def test_a_set_without_sources_stores_null_columns(self):
        self.add("act_s1", "g1", "2026-11-01T07:00:00+00:00")
        self.store(stream_set(hr=None, power=None))
        row = self.db.execute(
            "SELECT hr_source, power_source, sensors FROM activity_detail_sets"
        ).fetchone()
        self.assertEqual(
            (row["hr_source"], row["power_source"], row["sensors"]),
            (None, None, None),
        )

    def test_registry_deduplicates_a_sensor_across_sessions(self):
        meter = sensor(SensorRole.POWER_METER, "a")
        strap = sensor(SensorRole.HEART_RATE, "b")
        for session, activity, day in (
            ("act_s1", "g1", "2026-10-01"),
            ("act_s2", "g2", "2026-11-05"),
        ):
            self.add(session, activity, f"{day}T07:00:00+00:00")
            self.store(stream_set(activity, sensors=[meter, strap]))
        uses = activity_detail_store.sensor_uses(self.db)
        rows = sensor_registry.registry(uses, {meter.key: "bike-1"})
        self.assertEqual(len(rows), 2)
        by_role = {row["role"]: row for row in rows}
        power = by_role["power_meter"]
        self.assertEqual(
            (power["first_seen"], power["last_seen"], power["sessions"]),
            ("2026-10-01", "2026-11-05", 2),
        )
        self.assertEqual(power["equipment_id"], "bike-1")
        self.assertIsNone(by_role["heart_rate"]["equipment_id"])
        self.assertEqual(power["id"], meter.key[:16])

    def test_an_unreadable_sensor_list_does_not_hide_the_streams(self):
        self.add("act_s1", "g1", "2026-11-01T07:00:00+00:00")
        self.store(stream_set(sensors=[sensor(SensorRole.HEART_RATE, "a")]))
        self.db.execute("UPDATE activity_detail_sets SET sensors = '[{\"role\":1}]'")
        (stored,) = detail_sets_for(self.db, "garmin", "g1")
        self.assertEqual(stored.detail.sensors, ())
        self.assertIs(stored.detail.hr_source, HeartRateSource.CHEST_STRAP)
        self.assertEqual(activity_detail_store.sensor_uses(self.db), [])

    def test_deleted_sessions_leave_the_registry(self):
        self.add("act_s1", "g1", "2026-11-01T07:00:00+00:00", state="deleted")
        self.store(stream_set(sensors=[sensor(SensorRole.HEART_RATE, "a")]))
        self.assertEqual(activity_detail_store.sensor_uses(self.db), [])


class PowerMeterChangeTests(unittest.TestCase):
    def use(self, session, day, sport, *labels):
        return sensor_registry.SensorUse(
            session,
            sport,
            datetime.fromisoformat(f"{day}T07:00:00+00:00"),
            tuple(sensor(SensorRole.POWER_METER, label) for label in labels),
        )

    def test_a_new_meter_marks_the_first_session_it_appears_in(self):
        uses = [
            self.use("act_s1", "2026-09-01", "ride", "a"),
            self.use("act_s2", "2026-10-01", "ride", "a"),
            self.use("act_s3", "2026-11-02", "ride", "b"),
            self.use("act_s4", "2026-11-05", "ride", "b"),
        ]
        (change,) = sensor_registry.power_meter_changes(uses)
        self.assertEqual((change["sport"], change["date"]), ("ride", "2026-11-02"))
        self.assertEqual(change["sensor_ids"], [key("b")[:16]])
        self.assertIn("nicht ohne Hinweis vergleichen", change["note"])

    def test_no_change_for_the_same_meter_other_sports_or_trainer_rides(self):
        trainer = sensor_registry.SensorUse(
            "act_s9",
            "ride",
            datetime(2026, 10, 15, 7, tzinfo=UTC),
            (sensor(SensorRole.TRAINER, "e"),),
        )
        uses = [
            self.use("act_s1", "2026-09-01", "ride", "a"),
            trainer,
            self.use("act_s2", "2026-10-20", "ride", "a"),
            self.use("act_s3", "2026-11-02", "run", "b"),
        ]
        self.assertEqual(sensor_registry.power_meter_changes(uses), [])

    def test_one_shared_pedal_is_not_a_new_meter_and_a_new_pair_is(self):
        uses = [
            self.use("act_s1", "2026-09-01", "ride", "a", "b"),
            self.use("act_s2", "2026-10-01", "ride", "a"),
            self.use("act_s3", "2026-11-01", "ride", "c", "d"),
        ]
        (change,) = sensor_registry.power_meter_changes(uses)
        self.assertEqual(change["date"], "2026-11-01")
        self.assertEqual(len(change["sensor_ids"]), 2)

    def test_alternating_between_two_metered_bikes_is_no_change(self):
        uses = [
            self.use("act_s1", "2026-09-01", "ride", "a"),
            self.use("act_s2", "2026-09-05", "ride", "b"),
            self.use("act_s3", "2026-09-10", "ride", "a"),
            self.use("act_s4", "2026-09-15", "ride", "b"),
            self.use("act_s5", "2026-10-15", "ride", "c"),
        ]
        # Only the first ride on each new meter is marked, not every switch back.
        changes = sensor_registry.power_meter_changes(uses)
        self.assertEqual([c["date"] for c in changes], ["2026-10-15", "2026-09-05"])

    def test_changes_since_filters_by_sport_and_day(self):
        changes = [
            {"sport": "ride", "date": "2026-11-02"},
            {"sport": "ride", "date": "2026-08-01"},
            {"sport": "run", "date": "2026-11-02"},
        ]
        found = sensor_registry.changes_since(changes, "ride", date(2026, 10, 1))
        self.assertEqual([c["date"] for c in found], ["2026-11-02"])


class SerialPrivacyTests(StoreCase):
    def test_the_serial_never_reaches_stored_or_shown_data(self):
        data = fit_file([device(1, 11, 7, int(SERIAL), 5, 1)])
        result = map_fit_activity_detail(
            data, provider_activity_id="g1", provenance=GARMIN
        )
        detail = next(r for r in result.records if isinstance(r, ActivityStreamSet))
        self.add("act_s1", "g1", "2026-11-01T07:00:00+00:00")
        self.store(detail)
        dump = "\n".join(self.db.iterdump())
        self.assertNotIn(SERIAL, dump)
        uses = activity_detail_store.sensor_uses(self.db)
        shown = json.dumps(sensor_registry.registry(uses)) + json.dumps(
            sensor_registry.power_meter_changes(uses)
        )
        self.assertNotIn(SERIAL, shown)
        self.assertNotIn(SERIAL, repr(detail))


if __name__ == "__main__":
    unittest.main()
