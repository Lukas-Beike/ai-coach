"""Garmin RPE, feel and minimum HR: read, merged, ranked before the Intervals copy."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_summary import activity_summary
from backend.activities.detail_contract import activity_detail_contract
from backend.activities.detail_merge import merge_details
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance.session_rpe_load import session_load
from backend.providers.canonical_plans import garmin_ingest_plan
from backend.providers.garmin import (
    MAX_ACTIVITY_RATING_READS,
    _collect_activity_ratings,
)
from backend.providers.garmin_activity_mapping import (
    garmin_feel,
    map_garmin_activities,
    merge_training_load_rows,
)

TODAY = date(2026, 11, 6)
BERLIN = ZoneInfo("Europe/Berlin")
STARTED = datetime(2026, 11, 3, 10, 47, tzinfo=UTC)
LABELS = {ProviderId.GARMIN: "Garmin Connect", ProviderId.INTERVALS: "Intervals.icu"}


def _call(_service: str, _operation: str, call: Any, _details: Any) -> Any:
    return call()


class FakeClient:
    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.read: list[str] = []
        self.failing = failing

    def get_activity(self, activity_id: str) -> Any:
        self.read.append(activity_id)
        if activity_id in self.failing:
            raise RuntimeError("synthetic failure")
        return {"summaryDTO": {"directWorkoutRpe": 70, "directWorkoutFeel": 50}}


def _row(activity_id: int, day: date, **extra: Any) -> dict[str, Any]:
    return {"activityId": activity_id, "startTimeLocal": f"{day} 07:00:00", **extra}


def _collect(
    rows: list[dict[str, Any]], known: frozenset[str] | None, client: FakeClient
) -> dict[str, Any]:
    payload: dict[str, Any] = {"activities": rows, "errors": []}
    _collect_activity_ratings(client, payload, TODAY, known, _call, str, None)
    return payload


class CollectionTests(unittest.TestCase):
    def test_new_and_recent_activities_are_read_older_known_ones_are_not(self) -> None:
        client = FakeClient()
        rows = [
            _row(1, TODAY - timedelta(days=10)),  # known, old
            _row(2, TODAY - timedelta(days=10)),  # new, old
            _row(3, TODAY - timedelta(days=3)),  # known, recent
            _row(4, TODAY, manualActivity=True),  # manual entry
        ]

        payload = _collect(rows, frozenset({"1", "3", "4"}), client)

        self.assertEqual(["3", "2"], client.read)
        self.assertEqual(
            [
                {"activityId": "3", "directWorkoutRpe": 70, "directWorkoutFeel": 50},
                {"activityId": "2", "directWorkoutRpe": 70, "directWorkoutFeel": 50},
            ],
            payload["activity_ratings"],
        )

    def test_reads_are_capped_newest_first(self) -> None:
        client = FakeClient()
        rows = [_row(index, TODAY) for index in range(MAX_ACTIVITY_RATING_READS + 5)]

        _collect(rows, None, client)

        self.assertEqual(MAX_ACTIVITY_RATING_READS, len(client.read))

    def test_a_failed_read_keeps_the_others_and_is_recorded_once(self) -> None:
        client = FakeClient(failing=frozenset({"1"}))

        payload = _collect([_row(1, TODAY), _row(2, TODAY)], None, client)

        self.assertEqual(
            ["2"], [row["activityId"] for row in payload["activity_ratings"]]
        )
        self.assertEqual(["activity_ratings"], [e["source"] for e in payload["errors"]])

    def test_a_client_without_the_read_collects_nothing(self) -> None:
        payload: dict[str, Any] = {"activities": [_row(1, TODAY)], "errors": []}

        _collect_activity_ratings(object(), payload, TODAY, None, _call, str, None)

        self.assertNotIn("activity_ratings", payload)


def _activity(**extra: Any) -> dict[str, Any]:
    return {
        "activityId": 910009,
        "activityType": {"typeKey": "running"},
        "startTimeGMT": "2026-11-03 10:47:00",
        "duration": 3000.0,
        **extra,
    }


class MappingTests(unittest.TestCase):
    def test_rating_rows_bring_rpe_feel_and_minimum_heart_rate(self) -> None:
        rows = merge_training_load_rows(
            [_activity()],
            [
                {
                    "activityId": "910009",
                    "directWorkoutRpe": 60,
                    "directWorkoutFeel": 100,
                    "minHR": 97,
                }
            ],
        )

        record = map_garmin_activities(rows, zone=BERLIN, retrieved_at=STARTED).records[
            0
        ]

        self.assertEqual((6.0, 1.0, 97.0), (record.rpe, record.feel, record.min_hr))

    def test_feel_follows_the_intervals_import(self) -> None:
        self.assertEqual(
            [5.0, 4.0, 3.0, 2.0, 1.0], [garmin_feel(v) for v in (0, 25, 50, 75, 100)]
        )

    def test_out_of_range_rating_is_dropped_with_an_issue(self) -> None:
        result = map_garmin_activities(
            [_activity(directWorkoutRpe=110)], zone=BERLIN, retrieved_at=STARTED
        )

        self.assertIsNone(result.records[0].rpe)
        self.assertEqual(["directWorkoutRpe"], [issue.field for issue in result.issues])

    def test_stored_and_payload_rows_combine_per_activity(self) -> None:
        # A stored rating survives a later payload that brings only training load.
        plan = garmin_ingest_plan(
            {
                "synced_at": "2026-11-06T08:00:00+00:00",
                "activities": [_activity()],
                "training_load_activities": [
                    {"activityId": 910009, "activityTrainingLoad": 80.0}
                ],
            },
            zone=BERLIN,
            training_loads=lambda _id: {"activityId": "910009", "directWorkoutRpe": 60},
        )

        record = plan.activities[0].record
        self.assertEqual((6.0, 80.0), (record.rpe, record.load))


def _record(provider: ProviderId, activity_id: str, **fields: Any) -> ActivityRecord:
    values: dict[str, Any] = {
        "duration_s": 3000.0,
        "elapsed_duration_s": 3000.0,
        "distance_m": None,
        "load": None,
        "load_model": LoadModel.UNKNOWN,
        "avg_hr": None,
        "avg_power": None,
        "name": "Synthetic run",
    }
    values.update(fields)
    return ActivityRecord(
        activity_id=activity_id,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=activity_id,
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=STARTED,
            label=LABELS[provider],
        ),
        sport=Sport.RUN,
        environment=Environment.OUTDOOR,
        started_at=STARTED,
        **values,
    )


class PrecedenceTests(unittest.TestCase):
    def test_garmin_rating_wins_over_its_intervals_copy_without_conflict(self) -> None:
        summary = activity_summary(
            "act_1",
            [
                _record(ProviderId.INTERVALS, "i1", rpe=7.0, feel=2.0),
                _record(ProviderId.GARMIN, "g1", rpe=6.0, feel=1.0),
            ],
            BERLIN,
        )

        self.assertEqual((6.0, 1.0), (summary["rpe"], summary["feel"]))
        self.assertEqual("Garmin Connect", summary["sources"]["rpe"])
        self.assertNotIn("rpe_conflict", summary)

    def test_the_intervals_copy_fills_in_without_a_garmin_rating(self) -> None:
        summary = activity_summary(
            "act_1",
            [
                _record(ProviderId.INTERVALS, "i1", rpe=7.0),
                _record(ProviderId.GARMIN, "g1"),
            ],
            BERLIN,
        )

        self.assertEqual(7.0, summary["rpe"])
        self.assertEqual("Intervals.icu", summary["sources"]["rpe"])

    def test_copies_of_one_provider_that_disagree_still_conflict(self) -> None:
        summary = activity_summary(
            "act_1",
            [
                _record(ProviderId.GARMIN, "g1", rpe=6.0),
                _record(ProviderId.GARMIN, "g2", rpe=8.0),
            ],
            BERLIN,
        )

        self.assertTrue(summary["rpe_conflict"])

    def test_m1_labels_the_garmin_rating_and_local_feedback_still_wins(self) -> None:
        summary = activity_summary(
            "act_1", [_record(ProviderId.GARMIN, "g1", rpe=6.0)], BERLIN
        )

        garmin, garmin_value = session_load(summary, None)
        local, _ = session_load(summary, {"session_rpe": 4})

        self.assertEqual(
            ("Garmin Connect", "garmin_rpe_1_10", 300.0),
            (garmin["rpe_source_label"], garmin["rpe_scale"], garmin_value),
        )
        self.assertEqual(("athlete_feedback", 4.0), (local["rpe_source"], local["rpe"]))

    def test_detail_document_names_the_garmin_scale(self) -> None:
        doc = activity_detail_contract(
            "act_1",
            [
                _record(ProviderId.INTERVALS, "i1", rpe=6.0),
                _record(ProviderId.GARMIN, "g1", rpe=6.0, feel=1.0),
            ],
            merge_details(()),
            [],
            analysis=None,
            refreshable=frozenset(),
        )

        rpe, feel = doc["metrics"]["rpe"], doc["metrics"]["feel"]
        self.assertEqual("garmin", rpe["source"]["provider"])
        self.assertEqual("athlete_entered", rpe["source"]["kind"])
        self.assertEqual(
            ["intervals"], [a["source"]["provider"] for a in rpe["alternatives"]]
        )
        self.assertEqual("sehr stark", feel["rating_label"])
        self.assertEqual(0.0, feel["normalized_0_1"])


if __name__ == "__main__":
    unittest.main()
