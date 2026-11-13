"""Local mean-maximal curve from canonical full-resolution streams (#1430)."""

import sqlite3
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
from backend.db.activity_detail_store import (
    detail_sets_for,
    full_stream_keys,
    lap_set_keys,
    lap_sets_for_session,
    replace_detail_set,
)
from backend.db.schema import initialize_schema
from backend.performance import mean_max_curve
from backend.performance.canonical_detail import CanonicalDetailReader
from backend.performance.mean_max_curve import SessionCurveReader
from backend.performance.report_service import TrainingProfileSelectionService
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.sync.canonical_table_reader import CanonicalTableReader

STAMP = "2026-10-18T08:00:00+00:00"
RETRIEVED = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
TIME = tuple(float(second) for second in range(901))
INTERVALS = ProviderId.INTERVALS
GARMIN = ProviderId.GARMIN
WAHOO = ProviderId.WAHOO


def ride_power(peak: float) -> tuple[float, ...]:
    """200 W with a 3-min block at ``peak`` from second 300."""
    return tuple(peak if 300 <= second < 480 else 200.0 for second in range(len(TIME)))


def add_session(db, activity_id, state="active", merged_into=None):
    db.execute(
        "INSERT INTO activity_sessions(activity_id, primary_provider, "
        "primary_provider_activity_id, state, merged_into, started_at, "
        "created_at, updated_at) VALUES (?, 'garmin', ?, ?, ?, ?, ?, ?)",
        (activity_id, activity_id, state, merged_into, STAMP, STAMP, STAMP),
    )


def add_record(
    db, provider, provider_activity_id, activity_id, sport="ride", started_at=STAMP
):
    db.execute(
        "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
        "state, mapper_version, source_kind, recorded_by, sport, environment, "
        "started_at, load_model, fetched_at, created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', 1, 'provider_reported', 'garmin', ?, 'outdoor', "
        "?, 'unknown', ?, ?, ?)",
        (
            provider.value,
            provider_activity_id,
            activity_id,
            sport,
            started_at,
            STAMP,
            STAMP,
            STAMP,
        ),
    )


def store_summary(db, provider_activity_id, payload_hash):
    """Store the Garmin raw summary whose hash decides whether a set is current."""
    db.execute(
        "INSERT INTO provider_records(provider, record_kind, source_record_id, "
        "payload_hash, fetched_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(provider, record_kind, source_record_id) "
        "DO UPDATE SET payload_hash=excluded.payload_hash",
        (
            GARMIN.value,
            ACTIVITY_RECORD_KIND,
            provider_activity_id,
            payload_hash,
            STAMP,
            STAMP,
            STAMP,
        ),
    )


def store_streams(
    db,
    provider,
    provider_activity_id,
    watts,
    resolution,
    summary_sha256=None,
    retrieved_at=RETRIEVED,
):
    detail = ActivityStreamSet(
        provider_activity_id=provider_activity_id,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=retrieved_at,
            label=provider.value.title(),
        ),
        origin=ActivityDetailOrigin.FETCH,
        resolution=resolution,
        channels={StreamChannel.TIME_S: TIME, StreamChannel.POWER_W: watts},
    )
    replace_detail_set(
        db, detail, mapper_version=1, summary_sha256=summary_sha256, now=STAMP
    )


def store_laps(db, provider, provider_activity_id, windows, summary_sha256=None):
    """Lap set of (kind, start, end) windows on the stream clock."""
    detail = ActivityLapSet(
        provider_activity_id=provider_activity_id,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=RETRIEVED,
            label=provider.value.title(),
        ),
        origin=ActivityDetailOrigin.FETCH,
        lap_source=LapSource.DEVICE_LAPS,
        laps=tuple(
            ActivityLap(
                index=index,
                kind=LapKind(kind),
                start_offset_s=start,
                end_offset_s=end,
            )
            for index, (kind, start, end) in enumerate(windows)
        ),
    )
    replace_detail_set(
        db, detail, mapper_version=1, summary_sha256=summary_sha256, now=STAMP
    )


INTERVAL_LAPS = (
    ("warmup", 0.0, 300.0),
    ("work", 300.0, 480.0),
    ("recovery", 480.0, 600.0),
    ("work", 600.0, 780.0),
    ("cooldown", 780.0, 900.0),
)


def interval_power() -> tuple[float, ...]:
    return tuple(
        300.0 if 300 <= second < 480 or 600 <= second < 780 else 150.0
        for second in range(len(TIME))
    )


def watts_at(curve, duration):
    return next(
        point["watts"]
        for point in curve.power["duration_curve"]
        if point["duration_seconds"] == duration
    )


class SessionCurveReaderTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.reader = SessionCurveReader(CanonicalTableReader().session_activities)

    def test_only_full_resolution_streams_enter_the_curve(self):
        add_session(self.db, "act_1")
        add_record(self.db, WAHOO, "w-1", "act_1")
        store_streams(self.db, WAHOO, "w-1", ride_power(350.0), StreamResolution.FULL)
        add_record(self.db, GARMIN, "g-1", "act_1")
        store_streams(
            self.db, GARMIN, "g-1", ride_power(999.0), StreamResolution.DOWNSAMPLED
        )
        add_session(self.db, "act_2")
        add_record(self.db, GARMIN, "g-2", "act_2")
        store_streams(
            self.db, GARMIN, "g-2", ride_power(999.0), StreamResolution.DOWNSAMPLED
        )

        curves = self.reader.curves(self.db, ["act_1", "act_2"])

        self.assertEqual({"act_1"}, set(curves))
        self.assertEqual(350.0, watts_at(curves["act_1"], 180))
        self.assertEqual("Wahoo original watts stream", curves["act_1"].power["source"])
        # The power-at-heart-rate bins (#2427) come from the same streams; this
        # ride has no heart rate, so it gives none.
        self.assertEqual(
            ("power-at-heart-rate-v1", "insufficient_data"),
            (
                curves["act_1"].power_at_hr["method"],
                curves["act_1"].power_at_hr["status"],
            ),
        )

    def test_merged_duplicate_counts_once_under_its_session(self):
        add_session(self.db, "act_1")
        add_record(self.db, GARMIN, "g-1", "act_1")
        store_streams(self.db, GARMIN, "g-1", ride_power(350.0), StreamResolution.FULL)
        add_session(self.db, "act_2", "duplicate", merged_into="act_1")
        add_record(self.db, WAHOO, "w-1", "act_2")
        store_streams(self.db, WAHOO, "w-1", ride_power(350.0), StreamResolution.FULL)

        curves = self.reader.curves(self.db, ["act_1", "act_2"])

        self.assertEqual({"act_1"}, set(curves))
        self.assertEqual(350.0, watts_at(curves["act_1"], 180))

    def test_curves_are_recomputed_only_when_the_stream_content_changes(self):
        add_session(self.db, "act_1")
        add_record(self.db, GARMIN, "g-1", "act_1")
        store_streams(self.db, GARMIN, "g-1", ride_power(350.0), StreamResolution.FULL)

        with patch.object(
            mean_max_curve, "power_profile", wraps=mean_max_curve.power_profile
        ) as computed:
            first = self.reader.curves(self.db, ["act_1"])["act_1"]
            again = self.reader.curves(self.db, ["act_1"])["act_1"]
            store_streams(
                self.db, GARMIN, "g-1", ride_power(380.0), StreamResolution.FULL
            )
            changed = self.reader.curves(self.db, ["act_1"])["act_1"]

        self.assertEqual(2, computed.call_count)
        self.assertIs(first, again)
        self.assertNotEqual(first.fingerprint, changed.fingerprint)
        self.assertEqual(380.0, watts_at(changed, 180))

    def test_a_refetch_that_changes_the_chosen_set_recomputes_the_curve(self):
        add_session(self.db, "act_1")
        add_record(self.db, WAHOO, "w-1", "act_1")
        store_streams(self.db, WAHOO, "w-1", ride_power(350.0), StreamResolution.FULL)
        add_session(self.db, "act_2", "duplicate", merged_into="act_1")
        add_record(self.db, WAHOO, "w-2", "act_2")
        store_streams(self.db, WAHOO, "w-2", ride_power(450.0), StreamResolution.FULL)
        before = self.reader.curves(self.db, ["act_1"])["act_1"]

        # Same content fetched later: the merge now prefers this set.
        later = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
        for provider_activity_id, peak in (("w-1", 350.0), ("w-2", 450.0)):
            if watts_at(before, 180) != peak:
                store_streams(
                    self.db,
                    WAHOO,
                    provider_activity_id,
                    ride_power(peak),
                    StreamResolution.FULL,
                    retrieved_at=later,
                )
        cached = self.reader.curves(self.db, ["act_1"])["act_1"]
        fresh = SessionCurveReader(CanonicalTableReader().session_activities).curves(
            self.db, ["act_1"]
        )["act_1"]

        self.assertNotEqual(watts_at(before, 180), watts_at(fresh, 180))
        self.assertEqual(watts_at(fresh, 180), watts_at(cached, 180))

    def test_a_stored_intervals_copy_is_ignored_but_kept(self):
        # #2148: an Intervals.icu stream set counts nowhere, yet stays stored.
        add_session(self.db, "act_1")
        add_record(self.db, INTERVALS, "i-1", "act_1")
        store_streams(
            self.db, INTERVALS, "i-1", ride_power(350.0), StreamResolution.FULL
        )

        self.assertEqual({}, self.reader.curves(self.db, ["act_1"]))
        # Since #2650 the detail store serves it as no key, yet keeps it.
        self.assertEqual({}, full_stream_keys(self.db, ["act_1"]))
        stored = detail_sets_for(self.db, INTERVALS.value, "i-1")
        self.assertEqual(["i-1"], [item.provider_activity_id for item in stored])

    def test_a_set_fetched_for_an_older_summary_is_left_out(self):
        add_session(self.db, "act_1")
        add_record(self.db, GARMIN, "g-1", "act_1")
        store_streams(
            self.db,
            GARMIN,
            "g-1",
            ride_power(350.0),
            StreamResolution.FULL,
            summary_sha256="a" * 64,
        )

        store_summary(self.db, "g-1", "a" * 64)
        current = self.reader.curves(self.db, ["act_1"])
        store_summary(self.db, "g-1", "b" * 64)
        changed = self.reader.curves(self.db, ["act_1"])

        self.assertEqual(350.0, watts_at(current["act_1"], 180))
        self.assertEqual({}, changed)

    def test_detail_view_labels_a_profile_from_downsampled_streams(self):
        add_session(self.db, "act_1")
        add_record(self.db, GARMIN, "g-1", "act_1")
        store_streams(
            self.db, GARMIN, "g-1", ride_power(350.0), StreamResolution.DOWNSAMPLED
        )
        add_session(self.db, "act_2")
        add_record(self.db, WAHOO, "w-2", "act_2")
        store_streams(self.db, WAHOO, "w-2", ride_power(350.0), StreamResolution.FULL)
        reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities,
            refreshable=lambda: frozenset({INTERVALS}),
        )

        labels = {
            activity_id: reader.read(self.db, activity_id)["analysis"]["power_profile"][
                "stream_resolution"
            ]
            for activity_id in ("act_1", "act_2")
        }

        self.assertEqual({"act_1": "downsampled", "act_2": "full"}, labels)


class SessionExecutionCurveTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.reader = SessionCurveReader(CanonicalTableReader().session_activities)
        add_session(self.db, "act_1")
        add_record(self.db, GARMIN, "g-1", "act_1")
        store_streams(self.db, GARMIN, "g-1", interval_power(), StreamResolution.FULL)

    def test_lap_sets_are_read_by_key_and_alone(self):
        store_laps(self.db, GARMIN, "g-1", INTERVAL_LAPS)
        keys = lap_set_keys(self.db, ["act_1"])
        self.assertEqual(["g-1"], [key.provider_activity_id for key in keys["act_1"]])
        sets = lap_sets_for_session(self.db, "act_1")
        self.assertEqual(1, len(sets))
        self.assertIsInstance(sets[0].detail, ActivityLapSet)

    def test_the_curve_holds_the_execution_summary_of_its_laps(self):
        store_laps(self.db, GARMIN, "g-1", INTERVAL_LAPS)
        curve = self.reader.curves(self.db, ["act_1"])["act_1"]
        self.assertEqual("interval", curve.execution_summary["structure"])
        self.assertEqual(2, curve.execution_summary["rep_count"])
        self.assertEqual(300, curve.execution_summary["rep_output_mean"])

    def test_a_lap_change_recomputes_and_a_stale_lap_set_stays_out(self):
        store_laps(self.db, GARMIN, "g-1", INTERVAL_LAPS)
        first = self.reader.curves(self.db, ["act_1"])["act_1"]
        store_laps(self.db, GARMIN, "g-1", INTERVAL_LAPS, summary_sha256="a" * 64)
        store_summary(self.db, "g-1", "a" * 64)
        current = self.reader.curves(self.db, ["act_1"])["act_1"]
        store_summary(self.db, "g-1", "b" * 64)
        stale = self.reader.curves(self.db, ["act_1"])["act_1"]
        assert current.execution_summary is not None
        assert stale.execution_summary is not None
        self.assertNotEqual(first.fingerprint, stale.fingerprint)
        # The same laps count while current and stay out once stale.
        self.assertEqual("interval", current.execution_summary["structure"])
        self.assertEqual("continuous", stale.execution_summary["structure"])


class ProfileSelectionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.session_records = Mock(wraps=CanonicalTableReader().session_activities)
        self.day = date(2026, 10, 18)

    def service(self, summaries):
        @contextmanager
        def read_snapshot():
            yield self.db

        canonical = SimpleNamespace(
            activity_summary_reader=lambda: SimpleNamespace(
                activity_summaries=lambda _db, **_bounds: summaries,
            ),
            database_manager=lambda: SimpleNamespace(read_snapshot=read_snapshot),
        )
        return TrainingProfileSelectionService(
            lambda: self.day,
            canonical=canonical,
            curves=SessionCurveReader(self.session_records),
        )

    def add_ride(self, summaries, activity_id, day="2026-10-10", peak=350.0):
        add_session(self.db, activity_id)
        add_record(self.db, GARMIN, f"g-{activity_id}", activity_id)
        store_streams(
            self.db, GARMIN, f"g-{activity_id}", ride_power(peak), StreamResolution.FULL
        )
        summaries.append(
            {
                "id": activity_id,
                "sport": "ride",
                "environment": "outdoor",
                "started_at": f"{day}T08:00:00+00:00",
                "started_at_local": f"{day}T10:00:00",
                "record_ids": {"garmin": f"g-{activity_id}"},
                "source": "Garmin",
            }
        )

    def test_window_reads_canonical_sessions_and_counts_missing_streams(self):
        summaries = []
        for activity_id, day, peak, resolution in (
            ("act_1", "2026-10-10", 350.0, StreamResolution.FULL),
            ("act_2", "2026-10-12", 999.0, StreamResolution.DOWNSAMPLED),
            ("act_3", "2026-07-01", 999.0, StreamResolution.FULL),
            ("act_4", "2026-10-19", 999.0, StreamResolution.FULL),
        ):
            add_session(self.db, activity_id)
            add_record(self.db, GARMIN, f"g-{activity_id}", activity_id)
            store_streams(
                self.db, GARMIN, f"g-{activity_id}", ride_power(peak), resolution
            )
            summaries.append(
                {
                    "id": activity_id,
                    "sport": "ride",
                    "environment": "outdoor",
                    "started_at": f"{day}T08:00:00+00:00",
                    "started_at_local": f"{day}T10:00:00",
                    "record_ids": {"garmin": f"g-{activity_id}"},
                    "source": "Intervals.icu",
                }
            )

        result = self.service(summaries).power_profiles()

        window = result["windows"]["90"]
        self.assertEqual(
            {"records": 2, "usable_records": 1, "unknown_records": 1},
            {
                key: window["cache_coverage"][key]
                for key in ("records", "usable_records", "unknown_records")
            },
        )
        best = next(
            point
            for point in window["power"]
            if point["duration_seconds"] == 180 and point["environment"] == "outdoor"
        )
        self.assertEqual("Garmin Connect original watts stream", best["source"])
        self.assertEqual(
            (350.0, "act_1", 300.0),
            (best["watts"], best["activity_id"], best["start_seconds"]),
        )
        self.assertEqual(
            ("mean-max-curve", 2), (result["method"], result["method_version"])
        )
        self.assertRegex(window["input_fingerprint"], r"^[0-9a-f]{64}$")

    def test_a_shared_read_queries_no_session_while_the_inputs_are_unchanged(self):
        summaries = []
        for activity_id in ("act_1", "act_2", "act_3"):
            self.add_ride(summaries, activity_id)
        service = self.service(summaries)

        with patch.object(
            mean_max_curve.activity_detail_store,
            "full_stream_keys",
            wraps=full_stream_keys,
        ) as stream_keys:
            first = service.curve_records(60, shared=True)
            self.assertEqual((1, 3), (stream_keys.call_count, len(first)))
            self.assertEqual(3, self.session_records.call_count)
            again = service.curve_records(60, shared=True)

        # The second read of the day touches no stream key and no session.
        self.assertEqual(1, stream_keys.call_count)
        self.assertEqual(3, self.session_records.call_count)
        self.assertIs(first, again)
        self.assertEqual(list(first), service.curve_records(60))
        # One tuple of read-only records: a caller cannot change what others read.
        self.assertIsInstance(first, tuple)
        with self.assertRaises(TypeError):
            first[0]["date"] = "2000-01-01"

    def test_a_shared_read_is_built_again_on_a_new_day_or_window(self):
        summaries = []
        self.add_ride(summaries, "act_1")
        service = self.service(summaries)
        service.curve_records(60, shared=True)

        for day, days in ((date(2026, 10, 19), 60), (date(2026, 10, 19), 30)):
            self.day = day
            with self.subTest(day=day, days=days):
                before = self.session_records.call_count
                service.curve_records(days, shared=True)
                self.assertEqual(before + 1, self.session_records.call_count)
                service.curve_records(days, shared=True)
                self.assertEqual(before + 1, self.session_records.call_count)

    def test_a_shared_read_follows_a_changed_session_stream_or_summary(self):
        summaries = []
        self.add_ride(summaries, "act_1")
        service = self.service(summaries)
        store_summary(self.db, "g-act_1", "a" * 64)
        store_streams(
            self.db,
            GARMIN,
            "g-act_1",
            ride_power(350.0),
            StreamResolution.FULL,
            summary_sha256="a" * 64,
        )

        def peaks():
            return [
                row["power_profile"].get("duration_curve")
                and next(
                    point["watts"]
                    for point in row["power_profile"]["duration_curve"]
                    if point["duration_seconds"] == 180
                )
                for row in service.curve_records(60, shared=True)
            ]

        self.assertEqual([350.0], peaks())
        store_streams(
            self.db,
            GARMIN,
            "g-act_1",
            ride_power(380.0),
            StreamResolution.FULL,
            summary_sha256="a" * 64,
        )
        self.assertEqual([380.0], peaks())
        self.add_ride(summaries, "act_2", peak=300.0)
        self.assertEqual([380.0, 300.0], peaks())
        # A newer provider summary makes the set stale: the profile is empty.
        store_summary(self.db, "g-act_1", "b" * 64)
        self.assertEqual([None, 300.0], peaks())
        # A change of the session's own summary (the athlete marks it a
        # commute) leaves the records and sets alone and still counts.
        summaries[1]["purpose"] = "commute"
        self.assertEqual([None], peaks())

    def test_a_shared_read_follows_a_linked_record_with_a_wrong_device_clock(self):
        summaries = []
        self.add_ride(summaries, "act_1")
        # The session's streams come from a linked record that starts months
        # before the window: only the session link, not its date, ties it in.
        add_record(
            self.db,
            WAHOO,
            "w-act_1",
            "act_1",
            started_at="2026-01-01T08:00:00+00:00",
        )
        store_streams(
            self.db, WAHOO, "w-act_1", ride_power(330.0), StreamResolution.FULL
        )
        self.db.execute("DELETE FROM activity_detail_sets WHERE provider = 'garmin'")
        service = self.service(summaries)

        def peak():
            (row,) = service.curve_records(60, shared=True)
            return next(
                point["watts"]
                for point in row["power_profile"]["duration_curve"]
                if point["duration_seconds"] == 180
            )

        self.assertEqual(330.0, peak())
        store_streams(
            self.db, WAHOO, "w-act_1", ride_power(360.0), StreamResolution.FULL
        )
        self.assertEqual(360.0, peak())

    def test_a_shared_read_ignores_changes_the_records_do_not_show(self):
        summaries = []
        self.add_ride(summaries, "act_1")
        service = self.service(summaries)
        service.curve_records(60, shared=True)
        calls = self.session_records.call_count

        summaries[0].update(load=99.0, zone_times={"z2": 600}, notes="x")
        service.curve_records(60, shared=True)
        self.assertEqual(calls, self.session_records.call_count)
        # A field the records show is read again.
        summaries[0]["name"] = "Morning ride"
        (row,) = service.curve_records(60, shared=True)
        self.assertEqual(
            (calls + 1, "Morning ride"), (self.session_records.call_count, row["name"])
        )

    def test_a_shared_read_follows_a_merge_a_lap_set_and_a_record_update(self):
        summaries = []
        self.add_ride(summaries, "act_1")
        add_session(self.db, "act_2")
        add_record(self.db, WAHOO, "w-act_2", "act_2")
        store_streams(
            self.db, WAHOO, "w-act_2", ride_power(400.0), StreamResolution.FULL
        )
        service = self.service(summaries)
        service.curve_records(60, shared=True)
        changes = {
            "merge": lambda: self.db.execute(
                "UPDATE activity_sessions SET state = 'duplicate', "
                "merged_into = 'act_1' WHERE activity_id = 'act_2'"
            ),
            "lap set": lambda: store_laps(self.db, GARMIN, "g-act_1", INTERVAL_LAPS),
            "record update": lambda: self.db.execute(
                "UPDATE activity_records SET updated_at = '2026-10-17T00:00:00+00:00' "
                "WHERE provider_activity_id = 'g-act_1'"
            ),
        }
        for name, change in changes.items():
            with self.subTest(name):
                calls = self.session_records.call_count
                change()
                service.curve_records(60, shared=True)
                self.assertEqual(calls + 1, self.session_records.call_count)

    def test_a_concurrent_build_finishing_later_keeps_the_first_result(self):
        self.add_ride([], "act_1")
        reader = SessionCurveReader(self.session_records)
        builds = []

        def build(name):
            builds.append(name)
            return [{"build": name}]

        def older():
            # A newer read finishes while this build is still running.
            reader.shared_records(self.db, ["act_1"], "newer", lambda: build("newer"))
            return build("older")

        reader.shared_records(self.db, ["act_1"], "older", older)
        self.assertEqual(["newer", "older"], builds)
        (kept,) = reader.shared_records(self.db, ["act_1"], "newer", lambda: build("x"))
        self.assertEqual("newer", kept["build"])
        self.assertEqual(["newer", "older"], builds)

    def test_e_bike_sessions_stay_out_of_the_bests_and_fits(self):
        summaries = []
        for activity_id, peak, assist in (
            ("act_1", 300.0, None),
            ("act_2", 900.0, "electric"),
        ):
            add_session(self.db, activity_id)
            add_record(self.db, GARMIN, f"g-{activity_id}", activity_id)
            store_streams(
                self.db,
                GARMIN,
                f"g-{activity_id}",
                ride_power(peak),
                StreamResolution.FULL,
            )
            summary = {
                "id": activity_id,
                "sport": "ride",
                "environment": "outdoor",
                "started_at": "2026-10-10T08:00:00+00:00",
                "started_at_local": "2026-10-10T10:00:00",
                "record_ids": {"garmin": f"g-{activity_id}"},
                "source": "Intervals.icu",
            }
            if assist:
                summary["assist"] = assist
            summaries.append(summary)

        result = self.service(summaries).power_profiles()

        self.assertEqual(
            ["act_1"], [row["activity_id"] for row in result["activities"]]
        )
        bests = {
            point["watts"]
            for point in result["windows"]["90"]["power"]
            if point["watts"] is not None
        }
        self.assertTrue(bests)
        self.assertLessEqual(max(bests), 300.0)

    def test_commutes_stay_out_and_races_are_flagged(self):
        summaries = []
        for activity_id, peak, purpose in (
            ("act_1", 300.0, "race"),
            ("act_2", 900.0, "commute"),
            ("act_3", 950.0, "warmup"),
        ):
            add_session(self.db, activity_id)
            add_record(self.db, GARMIN, f"g-{activity_id}", activity_id)
            store_streams(
                self.db,
                GARMIN,
                f"g-{activity_id}",
                ride_power(peak),
                StreamResolution.FULL,
            )
            summaries.append(
                {
                    "id": activity_id,
                    "sport": "ride",
                    "environment": "outdoor",
                    "started_at": "2026-10-10T08:00:00+00:00",
                    "started_at_local": "2026-10-10T10:00:00",
                    "record_ids": {"garmin": f"g-{activity_id}"},
                    "source": "Intervals.icu",
                    "purpose": purpose,
                }
            )

        records = self.service(summaries).curve_records()

        self.assertEqual(
            [("act_1", "race")],
            [(row["activity_id"], row["effort_context"]) for row in records],
        )

    def test_overlapping_bests_of_one_effort_share_an_effort_group(self):
        def ride(activity_id, curve):
            return {
                "activity_id": activity_id,
                "date": "2026-10-10",
                "sport": "ride",
                "environment": "outdoor",
                "fingerprint": activity_id,
                "power_profile": {
                    "status": "ok",
                    "points": [],
                    "duration_curve": [
                        {"duration_seconds": d, "watts": w, "start_seconds": s}
                        for d, w, s in curve
                    ],
                },
            }

        records = [
            # 3 and 7 min overlap within a; its 12 min starts after both end.
            ride("a", [(180, 400.0, 100.0), (420, 330.0, 0.0), (720, 250.0, 1000.0)]),
            ride("b", [(180, 300.0, 0.0), (420, 300.0, 0.0), (720, 300.0, 0.0)]),
        ]
        service = TrainingProfileSelectionService(lambda: date(2026, 10, 18))

        window = service.power_profiles(records)["windows"]["90"]

        groups = {
            point["duration_seconds"]: (point["activity_id"], point["effort_group"])
            for point in window["power"]
            if point["environment"] == "outdoor" and point["status"] == "ok"
        }
        self.assertEqual(groups[180][1], groups[420][1])
        self.assertEqual("b", groups[720][0])
        self.assertNotEqual(groups[180][1], groups[720][1])
        reordered = service.power_profiles(records[::-1])["windows"]["90"]
        self.assertEqual(window["input_fingerprint"], reordered["input_fingerprint"])


if __name__ == "__main__":
    unittest.main()
