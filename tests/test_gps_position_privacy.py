"""GPS positions are stored and exported, but never reach a read model."""

import json
import sqlite3
import unittest
from unittest.mock import Mock

from backend.activities.detail_contract import _coverage, _streams
from backend.activities.detail_merge import merge_details
from backend.canonical.activity_detail import (
    ActivityDfaAlpha1,
    ActivitySensor,
    ActivityStreamSet,
    without_positions,
)
from backend.canonical.vocabulary import (
    POSITION_CHANNELS,
    ActivityDetailOrigin,
    DfaQuality,
    HeartRateSource,
    PowerSource,
    ProviderId,
    SensorRole,
    StreamChannel,
    StreamResolution,
)
from backend.db import row_factory
from backend.db.activity_detail_store import (
    GPS_TRACKS_KEY,
    _child_rows,
    _content_hash,
    _header,
    delete_stored_tracks,
    detail_sets_for,
    gps_tracks_enabled,
    stored_track_count,
    stream_export_rows,
)
from backend.db.canonical_store import WriteOutcome
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.privacy import (
    GPS_TRACKS_DELETE_CONFIRMATION_TEXT,
    PrivacyDeleteService,
)
from tests import test_activity_detail_store as store_tests
from tests.test_activity_detail_merge import candidate
from tests.test_activity_detail_store import GARMIN, STAMP, provenance

LAT = StreamChannel.LATITUDE_DEG
LON = StreamChannel.LONGITUDE_DEG


def track_set(activity_id="g1", provider=GARMIN):
    return ActivityStreamSet(
        provider_activity_id=activity_id,
        provenance=provenance(provider),
        origin=ActivityDetailOrigin.FETCH,
        resolution=StreamResolution.FULL,
        channels={
            StreamChannel.TIME_S: (0.0, 1.0, 2.0),
            StreamChannel.HEART_RATE_BPM: (120.0, 121.0, 122.0),
            LAT: (52.5, 52.5001, None),
            LON: (13.4, 13.4001, None),
        },
    )


def sensor_track_set(activity_id="g1", provider=GARMIN):
    """A track set that also names its heart rate and power sources and sensors."""
    base = track_set(activity_id, provider)
    return ActivityStreamSet(
        provider_activity_id=base.provider_activity_id,
        provenance=base.provenance,
        origin=base.origin,
        resolution=base.resolution,
        channels=base.channels,
        hr_source=HeartRateSource.CHEST_STRAP,
        power_source=PowerSource.POWER_METER,
        sensors=(
            ActivitySensor(
                role=SensorRole.HEART_RATE,
                key="a" * 64,
                connection="antplus",
                manufacturer=1,
                product=2,
            ),
            ActivitySensor(role=SensorRole.POWER_METER, key="b" * 64),
        ),
        dfa_alpha1=ActivityDfaAlpha1(
            estimate_bpm=150,
            windows=40,
            artifact_share=0.01,
            quality=DfaQuality.GOOD,
            method=1,
        ),
    )


class PositionChannelTests(unittest.TestCase):
    def test_position_channels_are_bounded_degrees(self):
        self.assertEqual(POSITION_CHANNELS, {LAT, LON})
        for values in ((91.0,), (-91.0,)):
            with self.assertRaises(ValueError):
                ActivityStreamSet(
                    provider_activity_id="g1",
                    provenance=provenance(GARMIN),
                    origin=ActivityDetailOrigin.FETCH,
                    resolution=StreamResolution.FULL,
                    channels={StreamChannel.TIME_S: (0.0,), LAT: values},
                )

    def test_without_positions_keeps_other_channels_or_nothing(self):
        stripped = without_positions(track_set())
        self.assertEqual(
            set(stripped.channels),
            {StreamChannel.TIME_S, StreamChannel.HEART_RATE_BPM},
        )
        only_positions = ActivityStreamSet(
            provider_activity_id="g2",
            provenance=provenance(GARMIN),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={StreamChannel.TIME_S: (0.0, 1.0), LAT: (1.0, 2.0)},
        )
        self.assertIsNone(without_positions(only_positions))

    def test_merged_streams_contract_and_coverage_never_carry_positions(self):
        detail = track_set()
        merged = merge_details([candidate(detail)])
        self.assertTrue(POSITION_CHANNELS.isdisjoint(merged.streams.channels))
        document = _streams(merged.streams)
        text = json.dumps(
            [document, _coverage([candidate(detail).stored])], sort_keys=True
        )
        for needle in ("latitude", "longitude", "52.5", "13.4"):
            self.assertNotIn(needle, text)


class PositionRankTests(unittest.TestCase):
    def test_positions_do_not_change_the_primary_stream_choice(self):
        from backend.activities.detail_merge import _populated_channel_count

        self.assertEqual(
            _populated_channel_count(track_set()),
            _populated_channel_count(without_positions(track_set())),
        )


class StoredPositionTests(unittest.TestCase):
    add_session = store_tests.ActivityDetailStoreTests.add_session
    add_record = store_tests.ActivityDetailStoreTests.add_record
    store = store_tests.ActivityDetailStoreTests.store

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.add_session("act_g")
        self.add_record(ProviderId.GARMIN, "g1", "act_g")

    def stored_channels(self):
        return {
            row["channel"]
            for row in self.db.execute("SELECT channel FROM activity_stream_channels")
        }

    def turn_setting_off(self):
        self.db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, '0', ?)",
            (GPS_TRACKS_KEY, STAMP),
        )

    def test_positions_are_stored_and_exported_by_default(self):
        self.assertTrue(gps_tracks_enabled(self.db))
        self.store(track_set())
        stored = detail_sets_for(self.db, "garmin", "g1")[0].detail
        self.assertEqual(stored.channels[LAT], (52.5, 52.5001, None))
        exported = {row["channel"] for row in stream_export_rows(self.db)}
        self.assertTrue({"latitude_deg", "longitude_deg"} <= exported)
        self.assertEqual(stored_track_count(self.db), 1)

    def test_setting_off_stops_storing_new_tracks(self):
        self.turn_setting_off()
        self.assertFalse(gps_tracks_enabled(self.db))
        self.store(track_set())
        self.assertEqual(self.stored_channels(), {"time_s", "heart_rate_bpm"})
        self.assertEqual(stored_track_count(self.db), 0)

    def test_deleting_tracks_keeps_other_channels_and_a_matching_content_hash(self):
        self.store(track_set())
        self.assertEqual(delete_stored_tracks(self.db), 1)
        self.assertEqual(self.stored_channels(), {"time_s", "heart_rate_bpm"})
        rehashed = self.db.execute(
            "SELECT content_sha256 FROM activity_detail_sets"
        ).fetchone()["content_sha256"]
        # The same set stored fresh with the setting off hashes identically.
        self.db.execute("DELETE FROM activity_stream_channels")
        self.db.execute("DELETE FROM activity_detail_sets")
        self.turn_setting_off()
        self.store(track_set())
        fresh = self.db.execute(
            "SELECT content_sha256 FROM activity_detail_sets"
        ).fetchone()["content_sha256"]
        self.assertEqual(rehashed, fresh)
        self.assertEqual(delete_stored_tracks(self.db), 0)

    def stored_hash_and_updated_at(self):
        row = self.db.execute(
            "SELECT content_sha256, updated_at FROM activity_detail_sets"
        ).fetchone()
        return row["content_sha256"], row["updated_at"]

    def test_deleting_tracks_of_a_set_with_sensors_hashes_like_a_fresh_write(self):
        self.store(sensor_track_set())
        self.assertEqual(delete_stored_tracks(self.db), 1)
        rehashed, _updated = self.stored_hash_and_updated_at()
        stripped = without_positions(sensor_track_set())
        self.assertEqual(
            rehashed, _content_hash(_header(stripped, 1), _child_rows(stripped))
        )
        # The same set stored fresh with the setting off hashes identically.
        self.db.execute("DELETE FROM activity_stream_channels")
        self.db.execute("DELETE FROM activity_detail_sets")
        self.turn_setting_off()
        self.store(sensor_track_set())
        self.assertEqual(rehashed, self.stored_hash_and_updated_at()[0])

    def test_second_pass_over_a_set_with_sensors_rewrites_nothing(self):
        self.store(sensor_track_set())
        delete_stored_tracks(self.db)
        before = self.stored_hash_and_updated_at()
        self.assertEqual(delete_stored_tracks(self.db), 0)
        self.assertEqual(self.stored_hash_and_updated_at(), before)
        # Re-storing the stripped set is recognized as unchanged: no rewrite.
        self.turn_setting_off()
        self.assertIs(self.store(sensor_track_set()), WriteOutcome.UNCHANGED)


class _Context:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *_):
        return False


class _Manager:
    def __init__(self, db):
        self.db = db

    def read_snapshot(self):
        return _Context(self.db)

    def unit_of_work(self):
        return _Context(self.db)

    def reclaim_space(self):
        return True


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Gate:
    def __init__(self):
        self.before_wait = []

    def restore(self, before_wait=None):
        self.before_wait.append(before_wait)
        return _Null()


class _Keys:
    def set(self, db, key, value):
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value, STAMP),
        )

    def delete(self, db, key):
        db.execute("DELETE FROM kv WHERE key = ?", (key,))


class _Dependencies:
    def __init__(self, db):
        self.database_manager = _Manager(db)
        self.database_lock = _Null()
        self.maintenance_gate = _Gate()
        self.key_value_repository = _Keys()
        self.cancel_coach_turns = Mock()


class GpsSettingServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.service = PrivacyDeleteService(_Dependencies(self.db))

    def test_default_on_and_toggle(self):
        state = self.service.gps_state()
        self.assertTrue(state["enabled"])
        self.assertEqual(state["stored_tracks"], 0)
        self.assertFalse(self.service.set_gps_tracks(False)["enabled"])
        self.assertTrue(self.service.set_gps_tracks(True)["enabled"])
        with self.assertRaises(AppError):
            self.service.set_gps_tracks("yes")

    def test_delete_needs_the_exact_confirmation(self):
        with self.assertRaises(AppError):
            self.service.delete_gps_tracks("ja")
        result = self.service.delete_gps_tracks(GPS_TRACKS_DELETE_CONFIRMATION_TEXT)
        self.assertEqual(result["deleted_tracks"], 0)

    def test_delete_cancels_running_coach_turns_before_the_maintenance_drain(self):
        dependencies = _Dependencies(self.db)
        service = PrivacyDeleteService(dependencies)

        service.delete_gps_tracks(GPS_TRACKS_DELETE_CONFIRMATION_TEXT)

        self.assertEqual(
            dependencies.maintenance_gate.before_wait,
            [dependencies.cancel_coach_turns],
        )


if __name__ == "__main__":
    unittest.main()
