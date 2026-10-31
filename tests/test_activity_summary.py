"""Neutral activity summary: per-value priority, sources, TSS-like load, order."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_summary import activity_summaries, activity_summary
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)

STARTED = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
BERLIN = ZoneInfo("Europe/Berlin")
LABELS = {
    ProviderId.INTERVALS: "Intervals.icu",
    ProviderId.GARMIN: "Garmin Connect",
    ProviderId.WAHOO: "Wahoo",
}


def record(
    provider: ProviderId,
    activity_id: str,
    *,
    recorded_by: RecordingOrigin = RecordingOrigin.WAHOO,
    started_at: datetime = STARTED,
    **fields: Any,
) -> ActivityRecord:
    values: dict[str, Any] = {
        "duration_s": 3600.0,
        "distance_m": None,
        "load": None,
        "load_model": LoadModel.UNKNOWN,
        "avg_hr": None,
        "avg_power": None,
        "name": "Synthetic ride",
    }
    values.update(fields)
    return ActivityRecord(
        activity_id=activity_id,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=activity_id,
            recorded_by=recorded_by,
            retrieved_at=STARTED + timedelta(hours=2),
            label=LABELS[provider],
        ),
        sport=Sport.RIDE,
        environment=Environment.OUTDOOR,
        started_at=started_at,
        **values,
    )


class ActivitySummaryTests(unittest.TestCase):
    def test_single_intervals_record_maps_to_neutral_keys(self) -> None:
        summary = activity_summary(
            "act_1",
            [
                record(
                    ProviderId.INTERVALS,
                    "i1",
                    moving_duration_s=3500.0,
                    distance_m=30000.0,
                    load=60.0,
                    load_model=LoadModel.INTERVALS_TRAINING_LOAD,
                    intensity=78.0,
                    rpe=6.0,
                    feel=2.0,
                    hr_zone_times_s=(("Z1", 600.0), ("Z2", 1200.0)),
                    planned_event_id="77",
                )
            ],
            BERLIN,
        )

        self.assertEqual("act_1", summary["id"])
        self.assertEqual("2026-10-19T09:00:00", summary["started_at_local"])
        self.assertEqual("ride", summary["sport"])
        self.assertEqual("outdoor", summary["environment"])
        self.assertEqual(3500.0, summary["moving_duration_s"])
        self.assertEqual(60.0, summary["training_load"])
        self.assertEqual("intervals_training_load", summary["load_model"])
        self.assertEqual(78.0, summary["intensity"])
        self.assertEqual(
            [{"id": "Z1", "secs": 600.0}, {"id": "Z2", "secs": 1200.0}],
            summary["heart_rate_zone_times"],
        )
        self.assertEqual("77", summary["planned_event_id"])
        self.assertEqual("Intervals.icu", summary["source"])
        self.assertEqual("Intervals.icu", summary["sources"]["training_load"])
        self.assertNotIn("avg_power", summary)

    def test_measured_values_prefer_the_recording_platform_copy(self) -> None:
        intervals = record(
            ProviderId.INTERVALS,
            "i1",
            recorded_by=RecordingOrigin.GARMIN,
            avg_hr=140.0,
            load=55.0,
            load_model=LoadModel.INTERVALS_TRAINING_LOAD,
            intensity=70.0,
        )
        garmin = record(
            ProviderId.GARMIN,
            "g1",
            recorded_by=RecordingOrigin.GARMIN,
            avg_hr=141.0,
            load=120.0,
            load_model=LoadModel.GARMIN_TRAINING_LOAD,
        )

        summary = activity_summary("act_1", [intervals, garmin], BERLIN)

        self.assertEqual(141.0, summary["avg_hr"])
        self.assertEqual("Garmin Connect", summary["sources"]["avg_hr"])
        self.assertEqual(55.0, summary["training_load"])
        self.assertEqual("Intervals.icu", summary["sources"]["training_load"])
        self.assertEqual(70.0, summary["intensity"])

    def test_garmin_only_load_is_not_a_tss_like_training_load(self) -> None:
        summary = activity_summary(
            "act_1",
            [
                record(
                    ProviderId.GARMIN,
                    "g1",
                    recorded_by=RecordingOrigin.GARMIN,
                    distance_m=10000.0,
                    load=120.0,
                    load_model=LoadModel.GARMIN_TRAINING_LOAD,
                )
            ],
            BERLIN,
        )

        self.assertNotIn("training_load", summary)
        self.assertNotIn("load_model", summary)
        self.assertEqual(10000.0, summary["distance_m"])
        self.assertEqual("Garmin Connect", summary["source"])

    def test_wahoo_tss_counts_as_training_load(self) -> None:
        summary = activity_summary(
            "act_1",
            [record(ProviderId.WAHOO, "w1", load=80.0, load_model=LoadModel.TSS)],
            BERLIN,
        )

        self.assertEqual(80.0, summary["training_load"])
        self.assertEqual("tss", summary["load_model"])

    def test_summaries_are_newest_first_and_limited(self) -> None:
        sessions = [
            ("act_old", (record(ProviderId.INTERVALS, "i1"),)),
            (
                "act_new",
                (
                    record(
                        ProviderId.GARMIN,
                        "g2",
                        started_at=STARTED + timedelta(days=1),
                    ),
                ),
            ),
            ("act_empty", ()),
        ]

        self.assertEqual(
            ["act_new", "act_old"],
            [summary["id"] for summary in activity_summaries(sessions, BERLIN)],
        )
        self.assertEqual(
            ["act_new"],
            [s["id"] for s in activity_summaries(sessions, BERLIN, limit=1)],
        )

    def test_empty_session_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            activity_summary("act_1", [], BERLIN)


if __name__ == "__main__":
    unittest.main()


class StoredKeyTests(unittest.TestCase):
    def test_stored_key_is_the_intervals_record_else_the_session(self) -> None:
        from backend.activities.activity_summary import stored_activity_key

        mixed = activity_summary(
            "act_1",
            [
                record(ProviderId.GARMIN, "g1", recorded_by=RecordingOrigin.GARMIN),
                record(ProviderId.INTERVALS, "i1", recorded_by=RecordingOrigin.GARMIN),
            ],
            BERLIN,
        )
        garmin_only = activity_summary(
            "act_2", [record(ProviderId.GARMIN, "g2")], BERLIN
        )

        self.assertEqual({"garmin": "g1", "intervals": "i1"}, mixed["record_ids"])
        self.assertEqual("i1", stored_activity_key(mixed))
        self.assertEqual("act_2", stored_activity_key(garmin_only))
