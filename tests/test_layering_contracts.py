from __future__ import annotations

import unittest
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from backend.errors import AppError
from backend.planning import workouts
from backend.providers.intervals_client import IntervalsClient
from backend.sync.library import WorkoutLibrarySyncService


class WorkoutExportLayeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.client.local_today.return_value = date(2026, 9, 20)
        self.service = WorkoutLibrarySyncService(Mock(), lambda: self.client, Mock())
        self.workout = {
            "sport": "Ride",
            "type": "Ride",
            "name": "Synthetic tempo",
            "description": "- 30m 85%",
            "duration_minutes": 30,
        }

    def test_invalid_description_and_dates_fail_before_remote_writes(self) -> None:
        cases = (
            ({**self.workout, "description": "Train hard"}, "2026-09-21"),
            (self.workout, "not-a-date"),
            (self.workout, "2026-02-30"),
            (self.workout, "2026-09-18"),
        )
        for workout, plan_date in cases:
            with self.subTest(plan_date=plan_date), self.assertRaises(AppError):
                self.service.plan_remote("library-1", workout, plan_date)
        self.client.plan_library_workout.assert_not_called()
        self.client.post.assert_not_called()
        self.client.put.assert_not_called()

    def test_response_mismatch_is_rejected_after_prepared_payload(self) -> None:
        self.client.plan_library_workout.return_value = {
            "id": "remote-event",
            "type": "Ride",
            "moving_time": 1800,
            "icu_training_load": 20,
            "workout_doc": {
                "duration": 1800,
                "steps": [
                    {
                        "duration": 1800,
                        "power": {"units": "%ftp", "value": 65},
                    }
                ],
            },
        }

        with self.assertRaises(AppError) as raised:
            self.service.plan_remote("library-1", self.workout, "2026-09-21")

        self.assertEqual(
            raised.exception.reason, "intervals_workout_verification_failed"
        )
        self.client.plan_library_workout.assert_called_once_with(
            workouts.library_workout_event_payload(
                "library-1", self.workout, "2026-09-21", today=date(2026, 9, 20)
            )
        )


class IntervalsPreparedPayloadTests(unittest.TestCase):
    def client(self, *, operation: Any = None) -> IntervalsClient:
        config = SimpleNamespace(
            intervals_api_key="test-key", intervals_athlete_id="synthetic"
        )
        return IntervalsClient(config, request=Mock(), operation=operation)

    def test_library_exports_only_normalized_fields(self) -> None:
        client = self.client()
        mock_client = cast(Any, client)
        mock_client.get_or_create_workout_folder = Mock(return_value=7)
        mock_client.post = Mock(return_value={"id": "created"})
        mock_client.put = Mock(return_value={"id": "updated"})
        workout = {
            "sport": "Cycling",
            "name": "Synthetic",
            "description": "- 30m Z2",
            "target": "POWER",
            "local_id": "local-only",
            "rationale": "local-only",
            "sync_state": "local-only",
            "folder_id": 9,
        }
        prepared = workouts.library_workout_payload(workout)
        self.assertEqual(
            set(prepared), {"name", "description", "type", "target", "folder_id"}
        )
        self.assertEqual(prepared["type"], "Ride")
        prepared["unexpected_local_field"] = "local-only"

        client.create_library_workouts([prepared])
        client.update_library_workout("remote-1", prepared)

        self.assertEqual(
            set(mock_client.post.call_args.args[1]),
            {"name", "description", "type", "target", "folder_id"},
        )
        self.assertEqual(mock_client.post.call_args.args[1]["folder_id"], 7)
        self.assertEqual(mock_client.put.call_args.args[1]["folder_id"], 9)
        self.assertNotIn("unexpected_local_field", mock_client.put.call_args.args[1])
        self.assertEqual(workout["sync_state"], "local-only")

    def test_injected_operation_guards_every_transport_mutation(self) -> None:
        operation = Mock(side_effect=lambda: nullcontext())
        client = self.client(operation=operation)
        client._api = Mock()
        client.post("/synthetic", {})
        client.put("/synthetic", {})
        client.delete("/synthetic")
        self.assertEqual(operation.call_count, 3)

    def test_rejected_operation_prevents_transport_write(self) -> None:
        operation = Mock(side_effect=AppError(409, "Synthetic active reset"))
        client = self.client(operation=operation)
        client._api = Mock()

        with self.assertRaises(AppError):
            client.post("/synthetic", {})

        client._api.post.assert_not_called()

    def test_legacy_plan_signature_fails_before_transport(self) -> None:
        client = self.client()
        mock_client = cast(Any, client)
        mock_client.post = Mock()

        with self.assertRaises(TypeError):
            cast(Any, client).plan_library_workout("library-1", {}, "2026-09-21")

        mock_client.post.assert_not_called()
