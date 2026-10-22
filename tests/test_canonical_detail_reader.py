"""Canonical detail reader: the stored ``activity_detail.v1`` document of one session."""

import json
import sqlite3
import unittest
from datetime import UTC, datetime

from backend.activities.detail_store import summary_fingerprint
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
TARGETS = {
    "steps": [{"kind": "power", "target": "100%", "duration": 600}] * 3,
    "basis": {"icu_ftp": 200},
}
WORK_LAPS = tuple(
    ActivityLap(index=index, kind=LapKind.WORK, start_offset_s=start, end_offset_s=end)
    for index, (start, end) in enumerate(
        ((0.0, 600.0), (900.0, 1500.0), (1800.0, 2400.0))
    )
)
ANALYSIS_KEYS = {"interval_quality", "aerobic", "power_profile", "running_profile"}


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
            refreshable=frozenset({INTERVALS}),
        )

    def add_session(self, activity_id, state="active", merged_into=None) -> None:
        self.db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, state, merged_into, started_at, "
            "created_at, updated_at) VALUES (?, 'intervals', ?, ?, ?, ?, ?, ?)",
            (activity_id, activity_id, state, merged_into, STAMP, STAMP, STAMP),
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
        """An Intervals ride with laps and streams, merged with a Garmin duplicate."""
        self.add_session("act_1")
        self.add_record(INTERVALS, "i-ride-99", "act_1")
        self.store_streams(
            INTERVALS,
            "i-ride-99",
            {HR: heart_rate(), POWER: power()},
            recorded_by=RecordingOrigin.WAHOO,
        )
        self.store_laps(INTERVALS, "i-ride-99")
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
            [("garmin", False), ("intervals", True)],
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

    def test_deleted_and_unknown_sessions_read_as_none(self) -> None:
        self.add_session("act_4", "deleted")
        self.add_record(INTERVALS, "i-deleted-99", "act_4")

        self.assertIsNone(self.read("act_4"))
        self.assertIsNone(self.read("act_missing"))

    def test_stored_target_snapshot_reaches_interval_quality(self) -> None:
        self.ride_session()
        without_targets = self.read("act_1")["analysis"]["interval_quality"]

        save_analysis(
            self.db,
            "act_1",
            analysis_version=1,
            input_sha256="0" * 64,
            payload={"target_snapshot": TARGETS},
            now=STAMP,
        )
        with_targets = self.read("act_1")["analysis"]["interval_quality"]

        self.assertEqual("ok", with_targets["status"])
        self.assertNotEqual(without_targets, with_targets)

    def test_stored_decoupling_reaches_the_aerobic_analysis(self) -> None:
        self.ride_session()
        save_analysis(
            self.db,
            "act_1",
            analysis_version=1,
            input_sha256="0" * 64,
            payload={
                "session_analysis": {"aerobic": {"provider_decoupling": {"value": 4.2}}}
            },
            now=STAMP,
        )

        aerobic = self.read("act_1")["analysis"]["aerobic"]

        self.assertEqual(4.2, aerobic["provider_decoupling"]["value"])

    def test_analysis_of_a_merged_intervals_session_is_read(self) -> None:
        self.add_session("act_5")
        self.add_record(GARMIN, "g-ride-98", "act_5")
        self.store_streams(GARMIN, "g-ride-98", {HR: heart_rate(), POWER: power()})
        self.add_session("act_6", "duplicate", merged_into="act_5")
        self.add_record(INTERVALS, "i-ride-98", "act_6")
        self.store_streams(
            INTERVALS,
            "i-ride-98",
            {HR: heart_rate(), POWER: power()},
            recorded_by=RecordingOrigin.WAHOO,
        )
        save_analysis(
            self.db,
            "act_6",
            analysis_version=1,
            input_sha256="0" * 64,
            payload={
                "session_analysis": {"aerobic": {"provider_decoupling": {"value": 4.2}}}
            },
            now=STAMP,
        )

        aerobic = self.read("act_5")["analysis"]["aerobic"]

        self.assertEqual(4.2, aerobic["provider_decoupling"]["value"])

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
        self.assertEqual({"intervals", "garmin"}, {s["provider"] for s in sources})
        for source in sources:
            self.assertIsNotNone(source["label"])
            self.assertEqual(labels[source["provider"]], source["label"])

    def test_sets_without_a_matching_session_record_are_skipped(self) -> None:
        self.ride_session()
        intervals_only = CanonicalDetailReader(
            lambda db, activity_id: [
                record
                for record in CanonicalTableReader().session_activities(db, activity_id)
                if record.provenance.provider is INTERVALS
            ],
            refreshable=frozenset({INTERVALS}),
        )

        doc = intervals_only.read(self.db, "act_1")
        assert doc is not None

        self.assertEqual(
            ["intervals"],
            [item["provider"] for item in doc["detail_data"]["providers"]],
        )
        self.assertEqual(
            {"intervals"},
            {
                channel["source"]["provider"]
                for channel in doc["streams"]["channels"].values()
            },
        )


SUMMARY = {"name": "Synthetic ride", "moving_time": 2700, "average_speed": 8.5}


class CanonicalDetailStatusTests(CanonicalDetailReaderTests):
    """Reads with the optional summary, failure and envelope dependencies.

    The inherited reads must stay valid with these dependencies wired.
    """

    def setUp(self) -> None:
        super().setUp()
        self.summary = dict(SUMMARY)
        self.failures: dict[str, dict] = {}
        self.reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities,
            refreshable=frozenset({INTERVALS}),
            summary_row=lambda db, activity_id: (
                self.summary if activity_id == "i-ride-99" else None
            ),
            failures=lambda ids: {
                key: value for key, value in self.failures.items() if key in set(ids)
            },
            envelope=lambda db, activity_id, provider_id, summary: {
                "activity_feedback": {"activity_id": provider_id},
                "equipment": [],
            },
        )

    def store(self, fingerprint: str | None, values=None) -> None:
        h = self
        h.add_session("act_1")
        h.add_record(INTERVALS, "i-ride-99", "act_1")
        detail = ActivityStreamSet(
            provider_activity_id="i-ride-99",
            provenance=h.provenance(INTERVALS),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={StreamChannel.TIME_S: TIME, HR: values or heart_rate()},
        )
        replace_detail_set(
            self.db, detail, mapper_version=1, summary_sha256=fingerprint, now=STAMP
        )

    def provider(self, doc, name):
        return next(
            item for item in doc["detail_data"]["providers"] if item["provider"] == name
        )

    def test_local_and_intervals_ids_give_the_same_document(self) -> None:
        self.store(summary_fingerprint(self.summary))

        by_local = self.reader.read(self.db, "act_1")
        assert by_local is not None

        self.assertEqual(by_local, self.reader.read(self.db, "i-ride-99"))
        self.assertEqual("i-ride-99", by_local["activity_feedback"]["activity_id"])
        self.assertEqual(8.5, by_local["metrics"]["avg_speed_mps"]["value"])
        self.assertIsNone(self.reader.read(self.db, "unknown-id"))
        self.assertIsNone(read_reference(self.db, "act_missing"))

    def test_merged_duplicate_resolves_to_the_primary_session(self) -> None:
        h = self
        h.add_session("act_5")
        h.add_record(GARMIN, "g-ride-98", "act_5")
        h.store_streams(GARMIN, "g-ride-98", {HR: heart_rate()})
        h.add_session("act_6", "duplicate", merged_into="act_5")
        h.add_record(INTERVALS, "i-ride-98", "act_6")

        self.assertEqual("act_5", read_reference(self.db, "i-ride-98"))
        self.assertEqual("act_5", read_reference(self.db, "act_6"))
        doc = self.reader.read(self.db, "act_6")
        assert doc is not None
        self.assertEqual("act_5", doc["session"]["activity_id"])

    def test_stale_flips_when_the_summary_changes(self) -> None:
        self.store(summary_fingerprint(self.summary))
        self.assertFalse(
            self.provider(self.reader.read(self.db, "act_1"), "intervals")["stale"]
        )

        self.summary["moving_time"] = 2800

        doc = self.reader.read(self.db, "act_1")
        self.assertTrue(self.provider(doc, "intervals")["stale"])

    def test_load_error_needs_the_current_fingerprint(self) -> None:
        fingerprint = summary_fingerprint(self.summary)
        self.store(fingerprint)
        note = {"message": "boom", "observed_at": STAMP}

        self.failures["i-ride-99"] = {**note, "summary_sha256": "0" * 64}
        self.assertIsNone(
            self.provider(self.reader.read(self.db, "act_1"), "intervals")["load_error"]
        )

        self.failures["i-ride-99"] = {**note, "summary_sha256": fingerprint}
        self.assertEqual(
            note,
            self.provider(self.reader.read(self.db, "act_1"), "intervals")[
                "load_error"
            ],
        )

    def test_garmin_staleness_follows_the_provider_record_hash(self) -> None:
        h = self
        h.add_session("act_3")
        h.add_record(GARMIN, "g-only-99", "act_3")
        detail = ActivityStreamSet(
            provider_activity_id="g-only-99",
            provenance=h.provenance(GARMIN),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={StreamChannel.TIME_S: TIME, HR: heart_rate()},
        )
        replace_detail_set(
            self.db, detail, mapper_version=1, summary_sha256="a" * 64, now=STAMP
        )
        self.db.execute(
            "INSERT INTO provider_records (provider, record_kind, source_record_id, "
            "payload, payload_hash, fetched_at, mapped_version, state, created_at, "
            "updated_at) VALUES ('garmin', 'activity', 'g-only-99', '{}', ?, ?, 1, "
            "'active', ?, ?)",
            ("a" * 64, STAMP, STAMP, STAMP),
        )
        self.assertFalse(
            self.provider(self.reader.read(self.db, "act_3"), "garmin")["stale"]
        )

        self.db.execute("UPDATE provider_records SET payload_hash = ?", ("b" * 64,))

        self.assertTrue(
            self.provider(self.reader.read(self.db, "act_3"), "garmin")["stale"]
        )

    def test_coverage_counts_points_and_valid_points(self) -> None:
        values: list[float | None] = list(heart_rate())
        values[0] = values[10] = None
        self.store(None, tuple(values))

        provider = self.provider(self.reader.read(self.db, "act_1"), "intervals")

        self.assertEqual(
            {HR.value: {"points": 2701, "valid_points": 2699}}, provider["coverage"]
        )

    def test_long_streams_are_reported_as_display_sampled(self) -> None:
        self.store(None)

        doc = self.reader.read(self.db, "act_1")
        assert doc is not None

        self.assertTrue(doc["detail_data"]["display_sampled"])


if __name__ == "__main__":
    unittest.main()
