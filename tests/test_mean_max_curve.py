"""Local mean-maximal curve from canonical full-resolution streams (#1430)."""

import sqlite3
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db import row_factory
from backend.db.activity_detail_store import replace_detail_set
from backend.db.schema import initialize_schema
from backend.performance import mean_max_curve
from backend.performance.canonical_detail import CanonicalDetailReader
from backend.performance.mean_max_curve import SessionCurveReader
from backend.performance.report_service import TrainingProfileSelectionService
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
        "created_at, updated_at) VALUES (?, 'intervals', ?, ?, ?, ?, ?, ?)",
        (activity_id, activity_id, state, merged_into, STAMP, STAMP, STAMP),
    )


def add_record(db, provider, provider_activity_id, activity_id, sport="ride"):
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
            STAMP,
            STAMP,
            STAMP,
            STAMP,
        ),
    )


def store_streams(
    db, provider, provider_activity_id, watts, resolution, summary_sha256=None
):
    detail = ActivityStreamSet(
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
        resolution=resolution,
        channels={StreamChannel.TIME_S: TIME, StreamChannel.POWER_W: watts},
    )
    replace_detail_set(
        db, detail, mapper_version=1, summary_sha256=summary_sha256, now=STAMP
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
        add_record(self.db, INTERVALS, "i-1", "act_1")
        store_streams(
            self.db, INTERVALS, "i-1", ride_power(350.0), StreamResolution.FULL
        )
        add_record(self.db, GARMIN, "g-1", "act_1")
        store_streams(
            self.db, GARMIN, "g-1", ride_power(999.0), StreamResolution.DOWNSAMPLED
        )
        add_session(self.db, "act_2")
        add_record(self.db, GARMIN, "g-2", "act_2")
        store_streams(
            self.db, GARMIN, "g-2", ride_power(999.0), StreamResolution.DOWNSAMPLED
        )

        curves = self.reader.curves(self.db, ["act_1", "act_2"], {})

        self.assertEqual({"act_1"}, set(curves))
        self.assertEqual(350.0, watts_at(curves["act_1"], 180))
        self.assertEqual(
            "Intervals.icu original watts stream", curves["act_1"].power["source"]
        )

    def test_merged_duplicate_counts_once_under_its_session(self):
        add_session(self.db, "act_1")
        add_record(self.db, INTERVALS, "i-1", "act_1")
        store_streams(
            self.db, INTERVALS, "i-1", ride_power(350.0), StreamResolution.FULL
        )
        add_session(self.db, "act_2", "duplicate", merged_into="act_1")
        add_record(self.db, WAHOO, "w-1", "act_2")
        store_streams(self.db, WAHOO, "w-1", ride_power(350.0), StreamResolution.FULL)

        curves = self.reader.curves(self.db, ["act_1", "act_2"], {})

        self.assertEqual({"act_1"}, set(curves))
        self.assertEqual(350.0, watts_at(curves["act_1"], 180))

    def test_curves_are_recomputed_only_when_the_stream_content_changes(self):
        add_session(self.db, "act_1")
        add_record(self.db, INTERVALS, "i-1", "act_1")
        store_streams(
            self.db, INTERVALS, "i-1", ride_power(350.0), StreamResolution.FULL
        )

        with patch.object(
            mean_max_curve, "power_profile", wraps=mean_max_curve.power_profile
        ) as computed:
            first = self.reader.curves(self.db, ["act_1"], {})["act_1"]
            again = self.reader.curves(self.db, ["act_1"], {})["act_1"]
            store_streams(
                self.db, INTERVALS, "i-1", ride_power(380.0), StreamResolution.FULL
            )
            changed = self.reader.curves(self.db, ["act_1"], {})["act_1"]

        self.assertEqual(2, computed.call_count)
        self.assertIs(first, again)
        self.assertNotEqual(first.fingerprint, changed.fingerprint)
        self.assertEqual(380.0, watts_at(changed, 180))

    def test_a_set_fetched_for_an_older_summary_is_left_out(self):
        add_session(self.db, "act_1")
        add_record(self.db, INTERVALS, "i-1", "act_1")
        store_streams(
            self.db,
            INTERVALS,
            "i-1",
            ride_power(350.0),
            StreamResolution.FULL,
            summary_sha256="a" * 64,
        )

        current = self.reader.curves(self.db, ["act_1"], {"i-1": "a" * 64})
        changed = self.reader.curves(self.db, ["act_1"], {"i-1": "b" * 64})

        self.assertEqual(350.0, watts_at(current["act_1"], 180))
        self.assertEqual({}, changed)

    def test_detail_view_labels_a_profile_from_downsampled_streams(self):
        add_session(self.db, "act_1")
        add_record(self.db, GARMIN, "g-1", "act_1")
        store_streams(
            self.db, GARMIN, "g-1", ride_power(350.0), StreamResolution.DOWNSAMPLED
        )
        add_session(self.db, "act_2")
        add_record(self.db, INTERVALS, "i-2", "act_2")
        store_streams(
            self.db, INTERVALS, "i-2", ride_power(350.0), StreamResolution.FULL
        )
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


class ProfileSelectionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)

    def service(self, summaries):
        @contextmanager
        def read_snapshot():
            yield self.db

        canonical = SimpleNamespace(
            activity_summary_reader=lambda: SimpleNamespace(
                activity_summaries=lambda _db, **_bounds: summaries,
                activity_rows=lambda _db, **_bounds: (),
            ),
            database_manager=lambda: SimpleNamespace(read_snapshot=read_snapshot),
        )
        return TrainingProfileSelectionService(
            lambda: date(2026, 10, 18),
            canonical=canonical,
            curves=SessionCurveReader(CanonicalTableReader().session_activities),
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
            add_record(self.db, INTERVALS, f"i-{activity_id}", activity_id)
            store_streams(
                self.db, INTERVALS, f"i-{activity_id}", ride_power(peak), resolution
            )
            summaries.append(
                {
                    "id": activity_id,
                    "sport": "ride",
                    "environment": "outdoor",
                    "started_at": f"{day}T08:00:00+00:00",
                    "started_at_local": f"{day}T10:00:00",
                    "record_ids": {"intervals": f"i-{activity_id}"},
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
        self.assertEqual("Intervals.icu original watts stream", best["source"])
        self.assertEqual(
            (350.0, "i-act_1", 300.0),
            (best["watts"], best["activity_id"], best["start_seconds"]),
        )
        self.assertEqual(
            ("mean-max-curve", 1), (result["method"], result["method_version"])
        )
        self.assertRegex(window["input_fingerprint"], r"^[0-9a-f]{64}$")

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
