"""Canonical activity detail: types, stream codec, store and schema guards."""

import dataclasses
import sqlite3
import unittest
import zlib
from datetime import UTC, datetime

from backend.canonical.activity_detail import (
    LAP_METRIC_FIELDS,
    MAX_STREAM_POINTS,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneBucket,
    ZoneDistribution,
    clean_series,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ZONE_DETAIL_KINDS,
    ActivityDetailKind,
    ActivityDetailOrigin,
    LapKind,
    LapSource,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db import row_factory
from backend.db.activity_detail_store import (
    analysis_rows_for,
    decode_series,
    detail_origins,
    detail_sets_for,
    detail_sets_for_session,
    encode_series,
    refill_lap_metrics,
    remove_detail_sets,
    replace_detail_set,
    save_analysis,
    stream_export_rows,
)
from backend.db.canonical_store import WriteOutcome
from backend.db.schema import initialize_schema

STAMP = "2026-10-18T08:00:00+00:00"
LATER = "2026-10-18T09:00:00+00:00"
RETRIEVED = datetime(2026, 10, 18, 7, 30, tzinfo=UTC)
INTERVALS = ProviderId.INTERVALS
GARMIN = ProviderId.GARMIN
DIGEST = "a" * 64


def provenance(provider=INTERVALS, **overrides):
    values = {
        "provider": provider,
        "source_kind": SourceKind.PROVIDER_REPORTED,
        "source_record_id": None,
        "recorded_by": RecordingOrigin.GARMIN,
        "retrieved_at": RETRIEVED,
        "label": None,
    }
    values.update(overrides)
    return Provenance(**values)


def stream_set(activity_id="i1", provider=INTERVALS, power=(100.0, None, 120.0)):
    return ActivityStreamSet(
        provider_activity_id=activity_id,
        provenance=provenance(provider),
        origin=ActivityDetailOrigin.FETCH,
        resolution=StreamResolution.FULL,
        channels={
            StreamChannel.TIME_S: (0.0, 1.0, 2.0),
            StreamChannel.POWER_W: power,
            StreamChannel.HEART_RATE_BPM: (120.0, 121.0, 122.5),
        },
    )


def lap_set(activity_id="i1", provider=INTERVALS):
    return ActivityLapSet(
        provider_activity_id=activity_id,
        provenance=provenance(provider),
        origin=ActivityDetailOrigin.FETCH,
        lap_source=LapSource.DEVICE_LAPS,
        laps=(
            ActivityLap(0, LapKind.WARMUP, 0.0, 600.0, name="Warm up", avg_hr=120.0),
            ActivityLap(
                1,
                LapKind.WORK,
                600.0,
                900.0,
                avg_power=280.0,
                load=12.5,
                avg_speed_mps=8.0,
                max_speed_mps=11.5,
            ),
        ),
    )


def zone_set(activity_id="i1", provider=INTERVALS):
    return ZoneDistribution(
        provider_activity_id=activity_id,
        provenance=provenance(provider),
        origin=ActivityDetailOrigin.FETCH,
        metric=ZoneMetric.POWER,
        boundary_source=ZoneBoundarySource.PROVIDER_REPORTED,
        buckets=(
            ZoneBucket(1, 300.0, lower=0.0, upper=150.0, label="Z1"),
            ZoneBucket(2, 600.0, lower=150.0, upper=None),
        ),
    )


class ActivityDetailTypeTests(unittest.TestCase):
    def test_clean_series_replaces_unusable_points_with_gaps(self):
        values, rejected = clean_series(
            StreamChannel.HEART_RATE_BPM, [120, None, True, "x", float("nan"), 9999, 10**400]
        )
        self.assertEqual(values, (120.0, None, None, None, None, None, None))
        self.assertEqual(rejected, 5)

    def test_every_zone_metric_has_its_own_detail_kind(self):
        self.assertEqual(set(ZONE_DETAIL_KINDS), set(ZoneMetric))
        self.assertEqual(len(set(ZONE_DETAIL_KINDS.values())), len(ZoneMetric))

    def test_lap_metric_fields_are_lap_attributes_and_table_columns(self):
        lap_fields = {field.name for field in dataclasses.fields(ActivityLap)}
        self.assertLessEqual(set(LAP_METRIC_FIELDS), lap_fields)
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        initialize_schema(db)
        columns = {row[1] for row in db.execute("PRAGMA table_info(activity_laps)")}
        self.assertLessEqual(set(LAP_METRIC_FIELDS), columns)

    def test_stream_set_requires_a_strict_complete_time_axis(self):
        invalid = (
            {StreamChannel.POWER_W: (1.0,)},
            {StreamChannel.TIME_S: (0.0, 1.0)},
            {StreamChannel.TIME_S: (0.0, None), StreamChannel.POWER_W: (1.0, 2.0)},
            {StreamChannel.TIME_S: (1.0, 1.0), StreamChannel.POWER_W: (1.0, 2.0)},
            {StreamChannel.TIME_S: (0.0, 1.0), StreamChannel.POWER_W: (1.0,)},
            {StreamChannel.TIME_S: (0.0,), StreamChannel.POWER_W: (-5.0,)},
        )
        for channels in invalid:
            with self.subTest(channels=channels), self.assertRaises(ValueError):
                ActivityStreamSet(
                    provider_activity_id="i1",
                    provenance=provenance(),
                    origin=ActivityDetailOrigin.FETCH,
                    resolution=StreamResolution.FULL,
                    channels=channels,
                )

    def test_stream_set_channels_are_read_only(self):
        detail = stream_set()
        with self.assertRaises(TypeError):
            detail.channels[StreamChannel.POWER_W] = (1.0, 2.0, 3.0)
        self.assertIs(detail.kind, ActivityDetailKind.STREAMS)

    def test_details_require_a_serving_provider(self):
        with self.assertRaises(ValueError):
            ActivityLapSet(
                provider_activity_id="i1",
                provenance=provenance(None, source_kind=SourceKind.DERIVED),
                origin=ActivityDetailOrigin.FETCH,
                lap_source=LapSource.SPLITS,
                laps=(ActivityLap(0, LapKind.LAP, 0.0, 1.0),),
            )

    def test_laps_and_zones_must_be_consecutive(self):
        with self.assertRaises(ValueError):
            ActivityLapSet(
                provider_activity_id="i1",
                provenance=provenance(),
                origin=ActivityDetailOrigin.FETCH,
                lap_source=LapSource.SPLITS,
                laps=(ActivityLap(1, LapKind.LAP, 0.0, 1.0),),
            )
        with self.assertRaises(ValueError):
            ZoneDistribution(
                provider_activity_id="i1",
                provenance=provenance(),
                origin=ActivityDetailOrigin.FETCH,
                metric=ZoneMetric.HEART_RATE,
                boundary_source=ZoneBoundarySource.UNKNOWN,
                buckets=(ZoneBucket(2, 10.0),),
            )
        self.assertIs(zone_set().kind, ActivityDetailKind.POWER_ZONES)


class StreamCodecTests(unittest.TestCase):
    def test_round_trip_keeps_gaps_and_counts_valid_points(self):
        values = (0.0, None, 1.5, -3.25, None)
        blob, valid = encode_series(values)
        self.assertEqual(valid, 3)
        self.assertEqual(decode_series(blob, len(values)), values)

    def test_decode_rejects_mismatched_corrupt_or_oversized_data(self):
        blob, _ = encode_series((1.0, 2.0))
        bomb = zlib.compress(b"\x00" * (8 * 1000))
        cases = (
            (blob, 3),
            (blob, 1),
            (b"not zlib", 2),
            (bomb, 2),
            (blob + b"trailing", 2),
            (blob, 0),
            (blob, MAX_STREAM_POINTS + 1),
            ("text", 2),
        )
        for data, count in cases:
            with self.subTest(count=count, size=len(data)), self.assertRaises(ValueError):
                decode_series(data, count)

    def test_decode_rejects_a_valid_count_that_disagrees_with_the_gaps(self):
        blob, valid = encode_series((1.0, None, 2.0))
        self.assertEqual(decode_series(blob, 3, valid), (1.0, None, 2.0))
        for wrong in (valid - 1, valid + 1):
            with self.subTest(valid_count=wrong), self.assertRaises(ValueError):
                decode_series(blob, 3, wrong)


class ActivityDetailStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.add_session("act_1")
        self.add_record(INTERVALS, "i1", "act_1")

    def add_session(self, activity_id, state="active", merged_into=None):
        self.db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, state, merged_into, started_at, "
            "created_at, updated_at) VALUES (?, 'intervals', ?, ?, ?, ?, ?, ?)",
            (activity_id, activity_id, state, merged_into, STAMP, STAMP, STAMP),
        )

    def add_record(self, provider, provider_activity_id, activity_id, state="active"):
        self.db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
            "state, mapper_version, source_kind, recorded_by, sport, environment, "
            "started_at, load_model, fetched_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, 'provider_reported', 'garmin', 'ride', 'outdoor', "
            "?, 'unknown', ?, ?, ?)",
            (
                provider.value,
                provider_activity_id,
                activity_id,
                state,
                STAMP,
                STAMP,
                STAMP,
                STAMP,
            ),
        )

    def store(self, detail, **overrides):
        options = {"mapper_version": 1, "summary_sha256": DIGEST, "now": STAMP}
        options.update(overrides)
        return replace_detail_set(self.db, detail, **options)

    def count(self, table):
        return self.db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

    def test_every_kind_round_trips_with_provenance(self):
        details = (stream_set(), lap_set(), zone_set())
        for detail in details:
            self.assertIs(self.store(detail), WriteOutcome.WRITTEN)
        stored = detail_sets_for(self.db, "intervals", "i1")
        self.assertEqual(
            {item.detail.kind for item in stored},
            {detail.kind for detail in details},
        )
        by_kind = {item.detail.kind: item.detail for item in stored}
        for detail in details:
            with self.subTest(kind=detail.kind):
                self.assertEqual(by_kind[detail.kind], detail)
        self.assertEqual(stored[0].activity_id, "act_1")
        self.assertEqual(stored[0].summary_sha256, DIGEST)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_equal_content_only_refreshes_fetch_bookkeeping(self):
        self.store(stream_set())
        later = stream_set()
        object.__setattr__(
            later,
            "provenance",
            provenance(retrieved_at=datetime(2026, 10, 18, 9, tzinfo=UTC)),
        )
        self.assertIs(
            self.store(later, summary_sha256=None, now=LATER), WriteOutcome.UNCHANGED
        )
        row = self.db.execute(
            "SELECT summary_sha256, fetched_at, updated_at FROM activity_detail_sets"
        ).fetchone()
        self.assertEqual(
            (row["summary_sha256"], row["fetched_at"], row["updated_at"]),
            (None, "2026-10-18T09:00:00+00:00", STAMP),
        )

    def test_changed_content_replaces_every_child_row(self):
        self.store(stream_set())
        changed = ActivityStreamSet(
            provider_activity_id="i1",
            provenance=provenance(),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.DOWNSAMPLED,
            channels={
                StreamChannel.TIME_S: (0.0, 5.0),
                StreamChannel.CADENCE_RPM: (80.0, 82.0),
            },
        )
        self.assertIs(self.store(changed, now=LATER), WriteOutcome.UPDATED)
        self.assertEqual(self.count("activity_stream_channels"), 2)
        (stored,) = detail_sets_for(self.db, "intervals", "i1")
        self.assertEqual(stored.detail, changed)
        row = self.db.execute(
            "SELECT created_at, updated_at FROM activity_detail_sets"
        ).fetchone()
        self.assertEqual((row["created_at"], row["updated_at"]), (STAMP, LATER))

    def test_providers_keep_alternative_sets_for_one_session(self):
        self.add_session("act_2", state="duplicate", merged_into="act_1")
        self.add_record(GARMIN, "g1", "act_2")
        self.store(stream_set())
        self.store(stream_set("g1", GARMIN, power=(101.0, 105.0, 119.0)))
        stored = detail_sets_for_session(self.db, "act_1")
        self.assertEqual(
            [(item.provider, item.activity_id) for item in stored],
            [("garmin", "act_2"), ("intervals", "act_1")],
        )
        self.assertEqual(detail_sets_for_session(self.db, "act_2")[0].provider, "garmin")

    def test_tombstoned_records_and_sessions_hide_details_without_deleting(self):
        self.store(stream_set())
        self.db.execute("UPDATE activity_records SET state = 'deleted'")
        self.assertEqual(detail_sets_for(self.db, "intervals", "i1"), [])
        self.db.execute("UPDATE activity_records SET state = 'active'")
        self.db.execute("UPDATE activity_sessions SET state = 'deleted'")
        self.assertEqual(detail_sets_for_session(self.db, "act_1"), [])
        self.assertEqual(self.count("activity_stream_channels"), 3)

    def test_unreadable_stored_set_is_skipped(self):
        self.store(stream_set())
        self.store(lap_set())
        self.db.execute(
            "UPDATE activity_stream_channels SET data = ? WHERE channel = 'power_w'",
            (b"corrupt",),
        )
        with self.assertLogs("intervals_coach", "WARNING") as logs:
            stored = detail_sets_for(self.db, "intervals", "i1")
        self.assertEqual([item.detail.kind for item in stored], [ActivityDetailKind.LAPS])
        (record,) = logs.records
        self.assertEqual(record.event, "activity_detail_unreadable")
        self.assertEqual(
            record.context,
            {"provider": "intervals", "detail_kind": "streams", "error": "ValueError"},
        )

    def test_detail_requires_an_existing_activity_record(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store(stream_set("missing"))

    def test_store_rejects_invalid_bookkeeping(self):
        for options, error in (
            ({"mapper_version": 0}, ValueError),
            ({"mapper_version": True}, TypeError),
            ({"summary_sha256": "short"}, ValueError),
        ):
            with self.subTest(options=options), self.assertRaises(error):
                self.store(stream_set(), **options)
        self.assertEqual(self.count("activity_detail_sets"), 0)

    def test_deleting_a_set_cascades_to_its_children(self):
        self.store(stream_set())
        self.store(lap_set())
        self.store(zone_set())
        self.db.execute("DELETE FROM activity_detail_sets")
        for table in ("activity_stream_channels", "activity_laps", "activity_zone_times"):
            with self.subTest(table=table):
                self.assertEqual(self.count(table), 0)

    def test_remove_detail_sets_keeps_only_the_requested_kinds(self):
        self.store(stream_set())
        self.store(lap_set())
        self.store(zone_set())
        removed = remove_detail_sets(
            self.db, "intervals", "i1", keep={ActivityDetailKind.LAPS}
        )
        self.assertEqual(removed, 2)
        (stored,) = detail_sets_for(self.db, "intervals", "i1")
        self.assertIs(stored.detail.kind, ActivityDetailKind.LAPS)
        self.assertEqual(self.count("activity_stream_channels"), 0)
        self.assertEqual(self.count("activity_zone_times"), 0)
        self.assertEqual(self.count("activity_laps"), 2)

    def test_remove_detail_sets_leaves_other_provider_activities_alone(self):
        self.add_record(GARMIN, "g1", "act_1")
        self.store(stream_set())
        self.store(stream_set("g1", GARMIN))
        self.assertEqual(remove_detail_sets(self.db, "intervals", "i1", keep=()), 1)
        (stored,) = detail_sets_for_session(self.db, "act_1")
        self.assertEqual(
            (stored.provider, stored.provider_activity_id), ("garmin", "g1")
        )
        self.assertEqual(self.count("activity_stream_channels"), 3)

    def test_detail_origins_lists_the_origins_of_stored_sets(self):
        self.assertEqual(detail_origins(self.db, "intervals", "i1"), set())
        self.store(stream_set())
        self.store(
            dataclasses.replace(lap_set(), origin=ActivityDetailOrigin.LEGACY_BACKFILL)
        )
        self.assertEqual(
            detail_origins(self.db, "intervals", "i1"), {"fetch", "legacy_backfill"}
        )

    def lap_set_row(self):
        return dict(
            self.db.execute(
                "SELECT mapper_version, origin, summary_sha256, content_sha256, "
                "fetched_at, created_at, updated_at FROM activity_detail_sets "
                "WHERE detail_kind = 'laps'"
            ).fetchone()
        )

    def test_refill_fills_only_missing_lap_metrics_and_rehashes(self):
        self.store(lap_set())
        before = self.lap_set_row()
        filled = refill_lap_metrics(
            self.db,
            "intervals",
            "i1",
            {
                0: {"max_speed_mps": 9.0, "avg_hr": 999.0},
                1: {"max_speed_mps": 99.0},
                7: {"max_speed_mps": 5.0},
            },
            now=LATER,
        )
        self.assertEqual(1, filled)
        (stored,) = detail_sets_for(self.db, "intervals", "i1")
        warmup, work = stored.detail.laps
        self.assertEqual((9.0, 120.0), (warmup.max_speed_mps, warmup.avg_hr))
        self.assertEqual(11.5, work.max_speed_mps)
        after = self.lap_set_row()
        self.assertNotEqual(before["content_sha256"], after["content_sha256"])
        self.assertEqual(LATER, after["updated_at"])
        for column in ("mapper_version", "origin", "summary_sha256", "fetched_at"):
            self.assertEqual(before[column], after[column])
        # The new hash equals the hash of storing the refilled set directly.
        refilled = dataclasses.replace(
            lap_set(),
            laps=(dataclasses.replace(lap_set().laps[0], max_speed_mps=9.0), work),
        )
        self.assertIs(self.store(refilled, now=LATER), WriteOutcome.UNCHANGED)

    def test_refill_without_missing_metrics_changes_nothing(self):
        self.store(lap_set())
        before = self.lap_set_row()
        self.assertEqual(
            0,
            refill_lap_metrics(
                self.db, "intervals", "i1", {1: {"max_speed_mps": 1.0}}, now=LATER
            ),
        )
        self.assertEqual(0, refill_lap_metrics(self.db, "intervals", "i2", {0: {}}, now=LATER))
        self.assertEqual(before, self.lap_set_row())
        with self.assertRaises(ValueError):
            refill_lap_metrics(self.db, "intervals", "i1", {0: {"name": 1.0}}, now=LATER)

    def test_set_columns_must_match_their_detail_kind(self):
        insert = (
            "INSERT INTO activity_detail_sets(provider, provider_activity_id, "
            "detail_kind, mapper_version, origin, source_kind, recorded_by, "
            "resolution, lap_source, zone_boundary_source, content_sha256, "
            "fetched_at, created_at, updated_at) "
            "VALUES ('intervals', 'i1', ?, 1, 'fetch', 'provider_reported', "
            "'garmin', ?, ?, ?, ?, ?, ?, ?)"
        )
        for kind, resolution, lap_source, boundary in (
            ("streams", None, None, None),
            ("laps", "full", "splits", None),
            ("power_zones", None, None, None),
            ("unknown", "full", None, None),
        ):
            with self.subTest(kind=kind), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(
                    insert,
                    (kind, resolution, lap_source, boundary, DIGEST, STAMP, STAMP, STAMP),
                )

    def test_analysis_is_stored_once_per_visible_session(self):
        payload = {"target": {"kind": "ftp"}, "score": 0.8}
        save = {"analysis_version": 1, "input_sha256": DIGEST, "payload": payload}
        self.assertIs(
            save_analysis(self.db, "act_1", now=STAMP, **save), WriteOutcome.WRITTEN
        )
        self.assertIs(
            save_analysis(self.db, "act_1", now=LATER, **save), WriteOutcome.UNCHANGED
        )
        save["input_sha256"] = "b" * 64
        self.assertIs(
            save_analysis(self.db, "act_1", now=LATER, **save), WriteOutcome.UPDATED
        )
        rows = analysis_rows_for(self.db, ["act_1", "act_1", ""])
        self.assertEqual(rows["act_1"]["payload"], payload)
        self.assertEqual(rows["act_1"]["computed_at"], LATER)
        self.db.execute("UPDATE activity_sessions SET state = 'deleted'")
        self.assertEqual(analysis_rows_for(self.db, ["act_1"]), {})

    def test_stream_export_decodes_points_and_flags_unreadable_channels(self):
        self.store(stream_set())
        self.db.execute(
            "UPDATE activity_stream_channels SET data = ? WHERE channel = 'heart_rate_bpm'",
            (b"corrupt",),
        )
        rows = {row["channel"]: row for row in stream_export_rows(self.db)}
        self.assertEqual(rows["power_w"]["values"], [100.0, None, 120.0])
        self.assertEqual(
            (rows["power_w"]["point_count"], rows["power_w"]["valid_count"]), (3, 2)
        )
        self.assertIsNone(rows["heart_rate_bpm"]["values"])

    def test_analysis_rejects_invalid_input(self):
        for overrides, error in (
            ({"analysis_version": 0}, ValueError),
            ({"input_sha256": "A" * 64}, ValueError),
            ({"payload": ["not", "a", "mapping"]}, TypeError),
        ):
            values = {"analysis_version": 1, "input_sha256": DIGEST, "payload": {}}
            values.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(error):
                save_analysis(self.db, "act_1", now=STAMP, **values)


if __name__ == "__main__":
    unittest.main()
