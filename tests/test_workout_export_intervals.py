"""Intervals.icu adapter for the planned-event export port.

These tests run the adapter over the real IntervalsClient with only the HTTP
request function mocked, pinning method, path, query, and payload.
"""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.planning import workouts as planning_workouts
from backend.planning.workout_export import build_planned_workout_export
from backend.providers.intervals_client import IntervalsClient
from backend.sync.intervals_workout_export import IntervalsWorkoutExport
from backend.sync.workout_export import WorkoutExportCapabilities, WorkoutExportPort

TODAY = date(2026, 9, 20)
LOCAL_ID = "12345678-1234-5678-1234-567812345678"


def workout(**changes):
    return {
        "date": TODAY.isoformat(),
        "sport": "WeightTraining",
        "name": "Strength",
        "description": "Oberkoerperkraft: 3x8 Wiederholungen",
        "duration_minutes": 35,
        "target": "AUTO",
        **changes,
    }


def config_stub():
    return type(
        "ConfigStub",
        (),
        {"intervals_api_key": "test-key", "intervals_athlete_id": "athlete/1"},
    )()


class IntervalsWorkoutExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = Mock(return_value=None)
        self.client = IntervalsClient(config_stub(), request=self.request)
        self.export = IntervalsWorkoutExport(lambda: self.client)

    def test_declares_planned_events_capability_only(self):
        self.assertIsInstance(self.export, WorkoutExportPort)
        self.assertEqual(
            self.export.capabilities, WorkoutExportCapabilities(planned_events=True)
        )

    def test_serialize_matches_planning_payload_and_never_resolves_client(self):
        factory = Mock()
        export = IntervalsWorkoutExport(factory)
        payload = export.serialize(
            LOCAL_ID, build_planned_workout_export(workout(), today=TODAY)
        )
        self.assertEqual(
            payload,
            planning_workouts.workout_event_payload(LOCAL_ID, workout(), today=TODAY),
        )
        factory.assert_not_called()

    def test_upsert_posts_bulk_events_with_upsert_flag(self):
        payload = self.export.serialize(
            LOCAL_ID, build_planned_workout_export(workout(), today=TODAY)
        )
        self.request.return_value = [{"id": "event-1", "type": "WeightTraining"}]

        saved = self.export.upsert([payload])

        self.assertEqual(saved, [{"id": "event-1", "type": "WeightTraining"}])
        method, url = self.request.call_args.args[:2]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/athlete/athlete%2F1/events/bulk?upsert=true"))
        self.assertEqual(self.request.call_args.args[2], [payload])

    def test_upsert_with_no_payloads_makes_no_request(self):
        self.assertEqual(self.export.upsert([]), [])
        self.request.assert_not_called()

    def test_delete_targets_quoted_event_path(self):
        self.export.delete("event/1")
        method, url = self.request.call_args.args[:2]
        self.assertEqual(method, "DELETE")
        self.assertTrue(url.endswith("/athlete/athlete%2F1/events/event%2F1"))

    def test_read_event_gets_quoted_event_path(self):
        self.request.return_value = {"id": "event-1"}
        self.assertEqual(self.export.read_event("event-1"), {"id": "event-1"})
        method, url = self.request.call_args.args[:2]
        self.assertEqual(method, "GET")
        self.assertTrue(url.endswith("/athlete/athlete%2F1/events/event-1"))

    def test_list_window_requests_athlete_events_with_workout_category(self):
        self.request.return_value = [{"id": "event-1"}]

        events = self.export.list_window(oldest="2026-09-20", newest="2026-09-26")

        self.assertEqual(events, [{"id": "event-1"}])
        method, url = self.request.call_args.args[:2]
        self.assertEqual(method, "GET")
        self.assertIn("/athlete/athlete%2F1/events?", url)
        self.assertIn("oldest=2026-09-20", url)
        self.assertIn("newest=2026-09-26", url)
        self.assertIn("category=WORKOUT", url)

    def test_list_window_passes_repair_collection_label_to_pagination(self):
        with patch.object(
            self.client, "get_paged_collection", return_value=[{"id": "event-1"}]
        ) as paged:
            events = self.export.list_window(oldest="2026-09-20", newest="2026-09-26")

        self.assertEqual(events, [{"id": "event-1"}])
        paged.assert_called_once_with(
            "/athlete/athlete%2F1/events",
            {"oldest": "2026-09-20", "newest": "2026-09-26", "category": "WORKOUT"},
            "repair_workouts",
        )

    def test_readback_accepts_saved_event_and_rejects_sport_mismatch(self):
        payload = self.export.serialize(
            LOCAL_ID, build_planned_workout_export(workout(), today=TODAY)
        )
        saved = {**payload, "id": "event-1", "type": "WeightTraining"}
        self.export.verify_readback(workout(), saved)

        with self.assertRaises(AppError) as caught:
            self.export.verify_readback(workout(), {**saved, "type": "Ride"})
        self.assertEqual(caught.exception.reason, "intervals_workout_sport_mismatch")

    def test_readback_and_delete_do_not_resolve_client_until_called(self):
        factory = Mock()
        export = IntervalsWorkoutExport(factory)
        payload = export.serialize(
            LOCAL_ID, build_planned_workout_export(workout(), today=TODAY)
        )
        export.verify_readback(
            workout(), {**payload, "id": "event-1", "type": "WeightTraining"}
        )
        factory.assert_not_called()
        export.delete("event-1")
        factory.assert_called_once_with()

    def test_event_identity_and_external_id_read_intervals_keys(self):
        self.assertEqual(self.export.event_identity({"id": "event-1"}), "event-1")
        self.assertEqual(self.export.event_identity({}), "")
        self.assertEqual(
            self.export.event_external_id({"external_id": "ext-1"}), "ext-1"
        )
        self.assertEqual(self.export.event_external_id({}), "")

    def test_external_id_for_matches_serialized_payload_identity(self):
        payload = self.export.serialize(
            LOCAL_ID, build_planned_workout_export(workout(), today=TODAY)
        )
        self.assertEqual(self.export.external_id_for(LOCAL_ID), payload["external_id"])
        self.assertEqual(
            self.export.external_id_for(LOCAL_ID), f"intervals-coach-{LOCAL_ID}"
        )

    def test_unpaired_future_planned_needs_workout_category_no_pairing_and_not_past(
        self,
    ):
        planned = {"category": "WORKOUT", "start_date_local": "2026-09-20T06:00:00"}
        self.assertTrue(self.export.is_unpaired_future_planned(planned, today=TODAY))
        self.assertFalse(
            self.export.is_unpaired_future_planned(
                {**planned, "start_date_local": "2026-09-19T06:00:00"}, today=TODAY
            )
        )
        self.assertFalse(
            self.export.is_unpaired_future_planned(
                {**planned, "category": "RACE_A"}, today=TODAY
            )
        )
        self.assertFalse(
            self.export.is_unpaired_future_planned(
                {**planned, "paired_activity_id": "activity-1"}, today=TODAY
            )
        )
        self.assertFalse(
            self.export.is_unpaired_future_planned(
                {**planned, "paired_event_id": "event-2"}, today=TODAY
            )
        )

    def test_namesake_matches_same_day_planned_name_ignoring_case_and_edges(self):
        event = {
            "category": "WORKOUT",
            "start_date_local": "2026-09-20T06:00:00",
            "name": "  strength ",
        }
        self.assertTrue(
            self.export.is_namesake_on_day(event, day="2026-09-20", name="Strength")
        )
        self.assertFalse(
            self.export.is_namesake_on_day(event, day="2026-09-21", name="Strength")
        )
        self.assertFalse(
            self.export.is_namesake_on_day(event, day="2026-09-20", name="Other")
        )
        self.assertFalse(
            self.export.is_namesake_on_day(
                {**event, "category": "RACE_A"}, day="2026-09-20", name="Strength"
            )
        )

    def test_confirms_planned_event_needs_day_prefix_and_exact_name(self):
        event = {"start_date_local": "2026-09-20T06:00:00", "name": "Strength"}
        self.assertTrue(
            self.export.confirms_planned_event(event, day="2026-09-20", name="Strength")
        )
        self.assertFalse(
            self.export.confirms_planned_event(event, day="2026-09-20", name="strength")
        )
        self.assertFalse(
            self.export.confirms_planned_event(event, day="2026-09-21", name="Strength")
        )


if __name__ == "__main__":
    unittest.main()
