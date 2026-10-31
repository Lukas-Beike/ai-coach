"""Parity of the served ``activity_detail.v1`` document with the old projection.

One synthetic workout is stored the way each provider delivers it: Intervals.icu
as a legacy detail record over its summary row, Garmin Connect through its
detail mapper, and a Wahoo recording through the FIT mapper. The values the old
Intervals-only projection showed for that workout must appear in the v1 fields.
"""

import tempfile
import unittest
from datetime import UTC, date, datetime

from activity_row_support import NoObservations, SnapshotActivityRows, StoredCoverage
from canonical_detail_support import (
    NOW,
    add_session_record,
    open_manager,
    seed_intervals_activity,
)

from backend.activities.detail_store import summary_fingerprint
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, SourceKind
from backend.db.activity_detail_store import replace_detail_set
from backend.http_api.activity_assembly import ActivityReadAssembly, ActivityReadSources
from backend.providers.fit_activity_detail_mapping import map_fit_activity_detail
from backend.providers.garmin_activity_detail_mapping import (
    map_garmin_activity_detail,
)
from backend.providers.intervals_activity_detail_mapping import STREAM_KEY_CHANNELS
from backend.providers.intervals_activity_detail_projection import detailed_activity
from backend.sync.activity_detail_canonical import CanonicalDetailWriter
from tests import test_fit_file as fit_builder

TODAY = date(2026, 9, 20)
RETRIEVED = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
# The workout: ten minutes, 3 km, two five-minute laps, one sample per minute.
SECONDS = [60 * minute for minute in range(11)]
HEART_RATE = [100 + 5 * minute for minute in range(11)]
POWER = [150 + 10 * minute for minute in range(11)]
LAP_OFFSETS = [(0.0, 300.0), (300.0, 600.0)]
HR_ZONE_SECONDS = [120, 240, 180, 60]
DURATION_S = 600
DISTANCE_M = 3000.0
SUMMARY = {
    "name": "Parity ride",
    "type": "Ride",
    "start_date_local": "2026-09-10T07:00:00",
    "moving_time": DURATION_S,
    "distance": DISTANCE_M,
    "icu_hr_zone_times": HR_ZONE_SECONDS,
    "icu_weighted_avg_watts": 205,
    "average_cadence": 88,
    "total_elevation_gain": 40,
}
INTERVALS_DETAIL = {
    "streams": {"time": SECONDS, "heartrate": HEART_RATE, "watts": POWER},
    "laps": [
        {"type": "work", "start_time": start, "end_time": end}
        for start, end in LAP_OFFSETS
    ],
}


class _Snapshots:
    def __init__(self, activities):
        self.snapshot = {
            "synced_at": NOW,
            "athlete": {},
            "raw_provider_data": {"activities": activities},
        }

    def latest_snapshot(self, _db):
        return self.snapshot


class _Feedback:
    def list(self, _limit=100):
        return []


def _garmin_collected(activity_id: str) -> dict:
    return {
        "activity_id": activity_id,
        "details": {
            "metricDescriptors": [
                {"metricsIndex": 0, "key": "sumDuration"},
                {"metricsIndex": 1, "key": "directHeartRate"},
                {"metricsIndex": 2, "key": "directPower"},
            ],
            "activityDetailMetrics": [
                {"metrics": [float(second), float(hr), float(watts)]}
                for second, hr, watts in zip(SECONDS, HEART_RATE, POWER, strict=True)
            ],
        },
        "splits": {
            "lapDTOs": [
                {"lapIndex": index + 1, "duration": end - start}
                for index, (start, end) in enumerate(LAP_OFFSETS)
            ]
        },
        "hr_zones": [
            {
                "zoneNumber": number,
                "zoneLowBoundary": 100 + 20 * number,
                "secsInZone": s,
            }
            for number, s in enumerate(HR_ZONE_SECONDS, start=1)
        ],
    }


def _fit_recording() -> bytes:
    builder = fit_builder.FitBuilder()
    builder.define(
        0,
        20,
        [(253, fit_builder.UINT32), (3, fit_builder.UINT8), (7, fit_builder.UINT16)],
    )
    for second, hr, watts in zip(SECONDS, HEART_RATE, POWER, strict=True):
        builder.data(0, {253: 1000 + second, 3: hr, 7: watts})
    builder.define(1, 19, [(2, fit_builder.UINT32), (7, fit_builder.UINT32)])
    for start, end in LAP_OFFSETS:
        builder.data(1, {2: 1000 + int(start), 7: int((end - start) * 1000)})
    return builder.build()


class ActivityDetailParityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        snapshots = _Snapshots([{"id": "i1", **SUMMARY}])
        self.assembly = ActivityReadAssembly(
            lambda: self.manager,
            ActivityReadSources(
                snapshots,
                lambda: SnapshotActivityRows(snapshots),
                observation_reader=NoObservations,
                coverage=lambda: StoredCoverage(None),
            ),
            _Feedback,
            lambda _activity_id: {"items": [], "assignments": []},
            refreshable_providers=lambda: ("intervals", "garmin"),
        )
        # The old projection read the summary row overlaid with the cached detail.
        self.old = detailed_activity({**SUMMARY, **INTERVALS_DETAIL})

    def detail(self, activity_id):
        return self.assembly.activity_read().detail(
            activity_id, garmin_snapshot={}, profile={}, today=TODAY
        )

    def store_intervals(self, summary_sha256):
        seed_intervals_activity(self.manager, "i1", **SUMMARY)
        with self.manager.unit_of_work() as db:
            CanonicalDetailWriter().write_legacy(
                db,
                record={
                    "activity_id": "i1",
                    "activity": INTERVALS_DETAIL,
                    "observed_at": NOW,
                    "summary_sha256": summary_sha256,
                    "full_resolution": True,
                },
                now=NOW,
            )
        return self.detail("i1")

    def store_mapped(
        self, provider, provider_activity_id, activity_id, result, recorded_by
    ):
        add_session_record(
            self.manager,
            provider,
            provider_activity_id,
            activity_id,
            recorded_by=recorded_by,
            duration_s=float(DURATION_S),
            distance_m=DISTANCE_M,
        )
        self.assertEqual((), result.issues)
        with self.manager.unit_of_work() as db:
            for record in result.records:
                replace_detail_set(
                    db, record, mapper_version=1, summary_sha256=None, now=NOW
                )
        return self.detail(activity_id)

    def documents(self):
        """The served document of the workout, by its providers' label."""
        intervals = self.store_intervals(summary_fingerprint({"id": "i1", **SUMMARY}))
        garmin = self.store_mapped(
            ProviderId.GARMIN,
            "g1",
            "act_g",
            map_garmin_activity_detail(
                _garmin_collected("g1"),
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=RETRIEVED,
            ),
            "garmin",
        )
        wahoo = self.store_mapped(
            ProviderId.WAHOO,
            "w1",
            "act_w",
            map_fit_activity_detail(
                _fit_recording(),
                provider_activity_id="w1",
                provenance=Provenance(
                    provider=ProviderId.WAHOO,
                    source_kind=SourceKind.PROVIDER_REPORTED,
                    source_record_id=None,
                    recorded_by=RecordingOrigin.WAHOO,
                    retrieved_at=RETRIEVED,
                    label=None,
                ),
            ),
            "wahoo",
        )
        return {"intervals": intervals, "garmin": garmin, "wahoo": wahoo}

    def test_old_projection_values_appear_in_the_v1_fields(self):
        old_laps = [(lap["start_time"], lap["end_time"]) for lap in self.old["laps"]]
        old_channels = {
            STREAM_KEY_CHANNELS[key].value: values
            for key, values in self.old["streams"].items()
        }
        old_time = old_channels.pop("time_s")
        for provider, document in self.documents().items():
            with self.subTest(provider):
                metrics = document["metrics"]
                self.assertEqual(
                    self.old["moving_time"], metrics["duration_s"]["value"]
                )
                self.assertEqual(self.old["distance"], metrics["distance_m"]["value"])
                self.assertEqual(old_time, document["streams"]["time_s"])
                self.assertEqual(
                    old_channels,
                    {
                        channel: stream["values"]
                        for channel, stream in document["streams"]["channels"].items()
                    },
                )
                self.assertEqual(
                    old_laps,
                    [
                        (lap["start_offset_s"], lap["end_offset_s"])
                        for lap in document["laps"]["laps"]
                    ],
                )
                if provider == "wahoo":
                    # A FIT recording carries no zone times to compare.
                    self.assertEqual({}, document["zones"])
                    continue
                self.assertEqual(
                    self.old["icu_hr_zone_times"],
                    [
                        bucket["seconds"]
                        for bucket in document["zones"]["heart_rate"]["buckets"]
                    ],
                )

    def test_intervals_summary_scalars_appear_in_the_v1_metrics(self):
        metrics = self.documents()["intervals"]["metrics"]

        self.assertEqual(
            (
                self.old["icu_weighted_avg_watts"],
                self.old["average_cadence"],
                self.old["total_elevation_gain"],
            ),
            (
                metrics["normalized_power"]["value"],
                metrics["avg_cadence"]["value"],
                metrics["elevation_gain_m"]["value"],
            ),
        )

    def test_data_scope_names_the_provider_and_the_recorder(self):
        scopes = {
            provider: document["data_scope"]
            for provider, document in self.documents().items()
        }
        prefix = (
            "bounded sanitized activity_detail.v1 document of exactly one local session"
        )
        self.assertEqual(
            {
                "intervals": f"{prefix}; providers: Intervals.icu; recorded by: unknown",
                "garmin": f"{prefix}; providers: Garmin Connect; recorded by: garmin",
                "wahoo": f"{prefix}; providers: Wahoo; recorded by: wahoo",
            },
            scopes,
        )

    def test_merged_session_names_every_provider(self):
        add_session_record(
            self.manager, ProviderId.WAHOO, "w2", "act_m", recorded_by="wahoo"
        )
        document = self.store_mapped(
            ProviderId.GARMIN,
            "g2",
            "act_m",
            map_garmin_activity_detail(
                _garmin_collected("g2"),
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=RETRIEVED,
            ),
            "garmin",
        )
        self.assertEqual(
            ["garmin", "wahoo"],
            [entry["provider"] for entry in document["detail_data"]["providers"]],
        )
        # The recorder is the one of the record whose measured values lead.
        self.assertTrue(
            document["data_scope"].endswith(
                "; providers: Garmin Connect, Wahoo; recorded by: garmin"
            )
        )

    def test_analysis_is_shown_when_fresh_and_withheld_when_stale(self):
        for provider, document in self.documents().items():
            with self.subTest(provider):
                (entry,) = document["detail_data"]["providers"]
                self.assertEqual(provider, entry["provider"])
                self.assertFalse(entry["stale"])
                self.assertTrue(document["analysis"])
        # The old projection hid the analysis of details older than the summary.
        stale = self.store_intervals("0" * 64)
        (entry,) = stale["detail_data"]["providers"]
        self.assertTrue(entry["stale"])
        self.assertIsNone(stale["analysis"])
        self.assertEqual(DURATION_S, stale["metrics"]["duration_s"]["value"])


if __name__ == "__main__":
    unittest.main()
