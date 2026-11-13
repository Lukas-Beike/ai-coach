"""Canonical detail reader: the stored ``activity_detail.v1`` document of one session."""

import json
import sqlite3
import unittest
from datetime import UTC, datetime

from backend.activities.zone_settings import ZoneSettings
from backend.canonical.activity_detail import (
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    LapKind,
    LapSource,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db import row_factory
from backend.db.activity_detail_store import replace_detail_set, save_analysis
from backend.db.schema import initialize_schema
from backend.performance.canonical_detail import CanonicalDetailReader, read_reference
from backend.sync.canonical_table_reader import CanonicalTableReader

STAMP = "2026-10-18T08:00:00+00:00"
RETRIEVED = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
TIME = tuple(float(second) for second in range(2701))
HR = StreamChannel.HEART_RATE_BPM
POWER = StreamChannel.POWER_W
INTERVALS = ProviderId.INTERVALS
GARMIN = ProviderId.GARMIN
WAHOO = ProviderId.WAHOO
TARGETS = {
    "steps": [{"kind": "power", "target": "100%", "duration": 600}] * 3,
    "basis": {"ftp": 200},
}
WORK_LAPS = tuple(
    ActivityLap(index=index, kind=LapKind.WORK, start_offset_s=start, end_offset_s=end)
    for index, (start, end) in enumerate(
        ((0.0, 600.0), (900.0, 1500.0), (1800.0, 2400.0))
    )
)
ANALYSIS_KEYS = {
    "interval_quality",
    "sensors",
    "execution",
    "aerobic",
    "power_profile",
    "running_profile",
}


def heart_rate() -> tuple[float, ...]:
    return tuple(100.0 + index % 50 for index in range(len(TIME)))


def power() -> tuple[float, ...]:
    return tuple(200.0 + index % 7 for index in range(len(TIME)))


class CanonicalDetailReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities,
            refreshable=lambda: frozenset({INTERVALS}),
        )

    def add_session(
        self, activity_id, state="active", merged_into=None, provider=GARMIN
    ) -> None:
        self.db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, state, merged_into, started_at, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                activity_id,
                provider.value,
                activity_id,
                state,
                merged_into,
                STAMP,
                STAMP,
                STAMP,
            ),
        )

    def add_record(
        self, provider, provider_activity_id, activity_id, *, state="active"
    ):
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

    def provenance(self, provider, recorded_by=RecordingOrigin.GARMIN) -> Provenance:
        return Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED,
            label=provider.value.title(),
        )

    def store_streams(self, provider, provider_activity_id, channels, **kwargs) -> None:
        detail = ActivityStreamSet(
            provider_activity_id=provider_activity_id,
            provenance=self.provenance(provider, **kwargs),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={StreamChannel.TIME_S: TIME, **channels},
        )
        replace_detail_set(
            self.db, detail, mapper_version=1, summary_sha256=None, now=STAMP
        )

    def store_laps(self, provider, provider_activity_id) -> None:
        detail = ActivityLapSet(
            provider_activity_id=provider_activity_id,
            provenance=self.provenance(provider, RecordingOrigin.WAHOO),
            origin=ActivityDetailOrigin.FETCH,
            lap_source=LapSource.PROVIDER_INTERVALS,
            laps=WORK_LAPS,
        )
        replace_detail_set(
            self.db, detail, mapper_version=1, summary_sha256=None, now=STAMP
        )

    def ride_session(self) -> None:
        """A Wahoo ride with laps and streams, a Garmin duplicate and an Intervals copy.

        The Intervals.icu copy carries its own sets, which are never read (#1685).
        """
        self.add_session("act_1", provider=WAHOO)
        self.add_record(WAHOO, "w-ride-99", "act_1")
        self.store_streams(
            WAHOO,
            "w-ride-99",
            {HR: heart_rate(), POWER: power()},
            recorded_by=RecordingOrigin.WAHOO,
        )
        self.store_laps(WAHOO, "w-ride-99")
        self.add_record(INTERVALS, "i-ride-99", "act_1")
        self.store_streams(INTERVALS, "i-ride-99", {HR: heart_rate(), POWER: power()})
        self.add_session("act_2", "duplicate", merged_into="act_1")
        self.add_record(GARMIN, "g-ride-99", "act_2")
        self.store_streams(GARMIN, "g-ride-99", {HR: heart_rate()})

    def read(self, activity_id):
        return self.reader.read(self.db, activity_id)

    def test_session_document_merges_duplicates_and_downsamples_streams(self) -> None:
        self.ride_session()

        doc = self.read("act_1")

        self.assertIsNotNone(doc)
        self.assertEqual("act_1", doc["session"]["activity_id"])
        self.assertEqual(
            [("garmin", False), ("wahoo", False)],
            sorted(
                (item["provider"], item["refreshable"])
                for item in doc["detail_data"]["providers"]
            ),
        )
        streams = doc["streams"]
        self.assertLessEqual(len(streams["time_s"]), 2000)
        self.assertEqual({HR.value, POWER.value}, set(streams["channels"]))
        for channel in streams["channels"].values():
            self.assertEqual(len(streams["time_s"]), len(channel["values"]))
        self.assertEqual("provider_intervals", doc["laps"]["lap_source"])
        self.assertEqual(3, len(doc["laps"]["laps"]))
        json.dumps(doc, allow_nan=False)

    def test_analysis_is_recomputed_from_the_merged_streams(self) -> None:
        self.ride_session()

        doc = self.read("act_1")

        self.assertEqual(ANALYSIS_KEYS, set(doc["analysis"]))

    def test_garmin_only_session_is_read_from_its_own_record(self) -> None:
        self.add_session("act_3")
        self.add_record(GARMIN, "g-only-99", "act_3")
        self.store_streams(GARMIN, "g-only-99", {HR: heart_rate()})

        doc = self.read("act_3")

        self.assertEqual("act_3", doc["session"]["activity_id"])
        self.assertEqual(
            [
                {
                    "provider": "garmin",
                    "label": "Garmin Connect",
                    "kinds": ["streams"],
                    "fetched_at": STAMP,
                    "refreshable": False,
                    "stale": False,
                    "load_error": None,
                    "coverage": {HR.value: {"points": 2701, "valid_points": 2701}},
                }
            ],
            doc["detail_data"]["providers"],
        )

    def test_garmin_only_session_gets_zone_times_from_its_stream(self) -> None:
        # #1724: the Personal API serves no zone times; LTHR 160 with default limits.
        self.add_session("act_3")
        self.add_record(GARMIN, "g-only-99", "act_3")
        self.store_streams(GARMIN, "g-only-99", {HR: heart_rate()})
        reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities,
            refreshable=frozenset,
            zone_settings=lambda _db, _record: ZoneSettings(lthr=160.0),
        )

        doc = reader.read(self.db, "act_3")
        assert doc is not None
        zones = doc["zones"]["heart_rate"]

        # 100..149 bpm repeating: per 50 s, 9 s up to 108.8, 24 s up to 132.8,
        # 17 s up to 150.4; 54 full cycles, the last sample counts nothing.
        self.assertEqual(
            [486.0, 1296.0, 918.0, 0.0, 0.0],
            [bucket["seconds"] for bucket in zones["buckets"]],
        )
        self.assertEqual("derived", zones["source"]["kind"])

    def test_deleted_and_unknown_sessions_read_as_none(self) -> None:
        self.add_session("act_4", "deleted")
        self.add_record(INTERVALS, "i-deleted-99", "act_4")

        self.assertIsNone(self.read("act_4"))
        self.assertIsNone(self.read("act_missing"))

    def garmin_ride(self, activity_id="act_5", provider_id="g-ride-98") -> None:
        """A Garmin ride with power, heart rate and work laps."""
        self.add_session(activity_id)
        self.add_record(GARMIN, provider_id, activity_id)
        self.store_streams(GARMIN, provider_id, {HR: heart_rate(), POWER: power()})
        self.store_laps(GARMIN, provider_id)

    def test_stored_target_snapshot_reaches_interval_quality(self) -> None:
        self.garmin_ride()
        without_targets = self.read("act_5")["analysis"]["interval_quality"]

        save_analysis(
            self.db,
            "act_5",
            analysis_version=1,
            input_sha256="0" * 64,
            payload={"target_snapshot": TARGETS},
            now=STAMP,
        )
        with_targets = self.read("act_5")["analysis"]["interval_quality"]

        self.assertEqual("ok", with_targets["status"])
        self.assertNotEqual(without_targets, with_targets)

    def test_intervals_detail_and_decoupling_are_never_analysis_inputs(self) -> None:
        # Athlete decision 2026-11-07 (#1685): Garmin, Wahoo and local data only.
        # A session of a stored Intervals.icu copy alone has nothing to read (#2148).
        self.add_session("act_7")
        self.add_record(INTERVALS, "i-only-97", "act_7")
        self.store_streams(INTERVALS, "i-only-97", {HR: heart_rate(), POWER: power()})
        self.assertIsNone(self.read("act_7"))

        self.garmin_ride()
        save_analysis(
            self.db,
            "act_5",
            analysis_version=2,
            input_sha256="0" * 64,
            payload={
                "session_analysis": {"aerobic": {"provider_decoupling": {"value": 4.2}}}
            },
            now=STAMP,
        )
        aerobic = self.read("act_5")["analysis"]["aerobic"]
        self.assertNotIn("provider_decoupling", aerobic)

    def test_target_snapshot_of_a_merged_session_is_read(self) -> None:
        self.garmin_ride()
        self.add_session("act_6", "duplicate", merged_into="act_5", provider=WAHOO)
        self.add_record(WAHOO, "w-ride-98", "act_6")
        save_analysis(
            self.db,
            "act_6",
            analysis_version=2,
            input_sha256="0" * 64,
            payload={"target_snapshot": TARGETS},
            now=STAMP,
        )

        quality = self.read("act_5")["analysis"]["interval_quality"]

        self.assertEqual("ok", quality["status"])

    def test_stored_sets_carry_the_labels_of_their_records(self) -> None:
        self.ride_session()

        doc = self.read("act_1")

        labels = {
            item["provider"]: item["label"] for item in doc["detail_data"]["providers"]
        }
        sources = [
            doc["streams"]["source"],
            doc["laps"]["source"],
            *(channel["source"] for channel in doc["streams"]["channels"].values()),
        ]
        self.assertEqual({"wahoo", "garmin"}, {s["provider"] for s in sources})
        for source in sources:
            self.assertIsNotNone(source["label"])
            self.assertEqual(labels[source["provider"]], source["label"])

    def test_sets_without_a_matching_session_record_are_skipped(self) -> None:
        self.ride_session()
        wahoo_only = CanonicalDetailReader(
            lambda db, activity_id: [
                record
                for record in CanonicalTableReader().session_activities(db, activity_id)
                if record.provenance.provider is WAHOO
            ],
            refreshable=frozenset,
        )

        doc = wahoo_only.read(self.db, "act_1")
        assert doc is not None

        self.assertEqual(
            ["wahoo"],
            [item["provider"] for item in doc["detail_data"]["providers"]],
        )
        self.assertEqual(
            {"wahoo"},
            {
                channel["source"]["provider"]
                for channel in doc["streams"]["channels"].values()
            },
        )

    def test_intervals_copies_are_never_served(self) -> None:
        # Athlete decision 2026-11-07 (#1685): no Intervals.icu fallback. Since
        # #2148 the stored copy is not even named, nor offered for refresh,
        # though Intervals.icu is configured as refreshable here.
        self.ride_session()

        doc = self.read("act_1")

        self.assertEqual(
            ["garmin", "wahoo"],
            sorted(item["provider"] for item in doc["detail_data"]["providers"]),
        )
        self.assertNotIn("Intervals", doc["analysis"]["aerobic"]["source"])


class CanonicalDetailStatusTests(CanonicalDetailReaderTests):
    """Reads with the fingerprint and envelope dependencies wired.

    The inherited reads must stay valid with these dependencies wired.
    """

    def setUp(self) -> None:
        super().setUp()
        self.reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities,
            refreshable=frozenset,
            envelope=lambda db, activity_id: {
                "activity_feedback": {"activity_id": activity_id},
                "equipment": [],
            },
            fingerprints=CanonicalTableReader(),
        )

    def store(self, fingerprint: str | None, values=None) -> None:
        """A Garmin ride whose provider record hash is ``"a" * 64``."""
        self.add_session("act_1")
        self.add_record(GARMIN, "g-ride-99", "act_1")
        detail = ActivityStreamSet(
            provider_activity_id="g-ride-99",
            provenance=self.provenance(GARMIN),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={StreamChannel.TIME_S: TIME, HR: values or heart_rate()},
        )
        replace_detail_set(
            self.db, detail, mapper_version=1, summary_sha256=fingerprint, now=STAMP
        )
        self.provider_record("g-ride-99", "a" * 64)

    def provider_record(self, provider_activity_id: str, payload_hash: str) -> None:
        self.db.execute(
            "INSERT INTO provider_records (provider, record_kind, source_record_id, "
            "payload, payload_hash, fetched_at, mapped_version, state, created_at, "
            "updated_at) VALUES ('garmin', 'activity', ?, '{}', ?, ?, 1, "
            "'active', ?, ?)",
            (provider_activity_id, payload_hash, STAMP, STAMP, STAMP),
        )

    def change_summary(self) -> None:
        self.db.execute("UPDATE provider_records SET payload_hash = ?", ("b" * 64,))

    def provider(self, doc, name):
        return next(
            item for item in doc["detail_data"]["providers"] if item["provider"] == name
        )

    def test_local_and_intervals_ids_give_the_same_document(self) -> None:
        self.store("a" * 64)
        self.add_record(INTERVALS, "i-ride-99", "act_1")

        by_local = self.reader.read(self.db, "act_1")
        assert by_local is not None

        self.assertEqual(by_local, self.reader.read(self.db, "i-ride-99"))
        self.assertEqual("act_1", by_local["activity_feedback"]["activity_id"])
        self.assertIsNone(self.reader.read(self.db, "unknown-id"))
        self.assertIsNone(read_reference(self.db, "act_missing"))

    def test_an_id_of_records_in_several_sessions_is_not_a_reference(self) -> None:
        self.add_session("act_a")
        self.add_record(INTERVALS, "shared-id", "act_a")
        self.add_session("act_b")
        self.add_record(GARMIN, "shared-id", "act_b")

        self.assertIsNone(read_reference(self.db, "shared-id"))
        self.assertEqual("act_a", read_reference(self.db, "act_a"))

    def test_a_deleted_alias_resolves_to_the_session_it_retained(self) -> None:
        self.add_session("act_8")
        self.add_record(GARMIN, "g-ride-96", "act_8")
        self.add_session("act_9", "deleted")
        self.db.execute(
            "UPDATE activity_sessions SET merged_into_retained = 'act_8' "
            "WHERE activity_id = 'act_9'"
        )

        self.assertEqual("act_8", read_reference(self.db, "act_9"))
        self.assertEqual("act_8", read_reference(self.db, "act_8"))
        self.assertIsNone(read_reference(self.db, "act_unknown"))

    def test_merged_duplicate_resolves_to_the_primary_session(self) -> None:
        self.add_session("act_5")
        self.add_record(GARMIN, "g-ride-98", "act_5")
        self.store_streams(GARMIN, "g-ride-98", {HR: heart_rate()})
        self.add_session("act_6", "duplicate", merged_into="act_5")
        self.add_record(INTERVALS, "i-ride-98", "act_6")

        self.assertEqual("act_5", read_reference(self.db, "i-ride-98"))
        self.assertEqual("act_5", read_reference(self.db, "act_6"))
        doc = self.reader.read(self.db, "act_6")
        assert doc is not None
        self.assertEqual("act_5", doc["session"]["activity_id"])

    def test_stale_flips_when_the_provider_record_changes(self) -> None:
        self.store("a" * 64)
        self.assertFalse(
            self.provider(self.reader.read(self.db, "act_1"), "garmin")["stale"]
        )

        self.change_summary()

        self.assertTrue(
            self.provider(self.reader.read(self.db, "act_1"), "garmin")["stale"]
        )

    def test_coverage_counts_points_and_valid_points(self) -> None:
        values: list[float | None] = list(heart_rate())
        values[0] = values[10] = None
        self.store(None, tuple(values))

        provider = self.provider(self.reader.read(self.db, "act_1"), "garmin")

        self.assertEqual(
            {HR.value: {"points": 2701, "valid_points": 2699}}, provider["coverage"]
        )

    def test_stale_provider_withholds_analysis_and_keeps_the_streams(self) -> None:
        self.store("a" * 64)
        fresh = self.reader.read(self.db, "act_1")
        assert fresh is not None
        self.assertIsNotNone(fresh["analysis"])

        self.change_summary()
        doc = self.reader.read(self.db, "act_1")
        assert doc is not None

        self.assertTrue(self.provider(doc, "garmin")["stale"])
        self.assertIsNone(doc["analysis"])
        self.assertIsNotNone(doc["streams"])

    def test_any_stale_merged_provider_withholds_analysis(self) -> None:
        self.ride_session()
        self.db.execute(
            "UPDATE activity_detail_sets SET summary_sha256 = ? WHERE provider = ?",
            ("a" * 64, "garmin"),
        )
        self.provider_record("g-ride-99", "b" * 64)

        doc = self.reader.read(self.db, "act_1")
        assert doc is not None

        self.assertTrue(self.provider(doc, "garmin")["stale"])
        self.assertFalse(self.provider(doc, "wahoo")["stale"])
        self.assertIsNone(doc["analysis"])

    def test_set_without_a_fingerprint_is_never_stale(self) -> None:
        self.store(None)

        self.change_summary()
        doc = self.reader.read(self.db, "act_1")
        assert doc is not None

        self.assertFalse(self.provider(doc, "garmin")["stale"])
        self.assertEqual(ANALYSIS_KEYS, set(doc["analysis"]))

    def test_refreshable_providers_are_read_per_document(self) -> None:
        self.store(None)
        configured = {GARMIN}
        reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities,
            refreshable=lambda: frozenset(configured),
        )
        self.assertTrue(
            self.provider(reader.read(self.db, "act_1"), "garmin")["refreshable"]
        )

        configured.clear()

        self.assertFalse(
            self.provider(reader.read(self.db, "act_1"), "garmin")["refreshable"]
        )

    def test_long_streams_are_reported_as_display_sampled(self) -> None:
        self.store(None)

        doc = self.reader.read(self.db, "act_1")
        assert doc is not None

        self.assertTrue(doc["detail_data"]["display_sampled"])


if __name__ == "__main__":
    unittest.main()
