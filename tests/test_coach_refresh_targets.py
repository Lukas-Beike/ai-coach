"""Coach refresh targets derive from the provider registry, not literals."""

from __future__ import annotations

import threading
import unittest
from typing import Any
from unittest.mock import MagicMock, Mock

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.coach.authorization import (
    REQUEST_SCHEMA,
    dialogue_tools,
    request_target_enum,
    validate_request,
)
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.errors import AppError
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID

USER_MESSAGE_ID = 7
DEFAULT_TARGETS = [
    "local",
    INTERVALS_ID,
    GARMIN_ID,
    CALENDAR_ID,
    WEATHER_ID,
    WAHOO_ID,
]


def refresh_request(target: str = WAHOO_ID) -> dict[str, Any]:
    return {
        "summary": "Refresh the Wahoo source.",
        "source_message_ids": [USER_MESSAGE_ID],
        "target": target,
        "scope": [f"{target}_refresh"],
        "period": None,
        "constraints": [],
        "remote_write": False,
        "sync_scope": None,
    }


class CoachRefreshTargetEnumTests(unittest.TestCase):
    def test_default_enum_is_local_then_ranked_provider_targets(self) -> None:
        self.assertEqual(DEFAULT_TARGETS, request_target_enum())
        self.assertEqual(
            DEFAULT_TARGETS, REQUEST_SCHEMA["properties"]["target"]["enum"]
        )

    def test_request_target_is_accepted_only_when_the_table_lists_it(self) -> None:
        user_ids = {USER_MESSAGE_ID}

        for target in DEFAULT_TARGETS[1:]:
            with self.subTest(target=target):
                accepted = validate_request(
                    refresh_request(target), user_ids, USER_MESSAGE_ID
                )
                self.assertEqual(target, accepted["target"])

        with self.assertRaises(ValueError) as raised:
            validate_request(refresh_request("unlisted"), user_ids, USER_MESSAGE_ID)
        self.assertEqual("request_target", str(raised.exception))

    def test_dialogue_tools_expose_the_targets_in_the_request_schema(self) -> None:
        tools = [
            {
                "name": "start_provider_refresh",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

        result = dialogue_tools(tools, set())

        enum = result[0]["parameters"]["properties"]["_request"]["properties"][
            "target"
        ]["enum"]
        self.assertEqual(DEFAULT_TARGETS, enum)


class CoachRefreshClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CoachDialogueActionService(
            MagicMock(), MagicMock(), Mock(), Mock(), Mock()
        )
        self.context = {
            "messages": [{"id": USER_MESSAGE_ID, "role": "user"}],
            "current_user_message_id": USER_MESSAGE_ID,
        }

    def test_wahoo_refresh_is_classified_as_remote_sync_with_its_scope(self) -> None:
        action = self.service.classify(
            "start_provider_refresh",
            {"_request": refresh_request(), "days": 14},
            self.context,
            allow_mutations=True,
        )

        self.assertEqual("remote_sync", action["intent"])
        self.assertEqual(WAHOO_ID, action["target_system"])
        self.assertEqual([f"{WAHOO_ID}_refresh"], action["authorization_scope"])

    def test_refresh_of_an_unlisted_target_is_rejected(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.classify(
                "start_provider_refresh",
                {"_request": refresh_request("unlisted"), "days": 14},
                self.context,
                allow_mutations=True,
            )
        self.assertEqual("request_invalid", raised.exception.reason)
        self.assertEqual(
            "request_target", getattr(raised.exception, "validation_reason", None)
        )


class CoachRefreshPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dialogue_action = Mock(spec=CoachDialogueActionService)
        self.service = CoachStructuredToolPreparationService(
            self.dialogue_action, Mock(), frozenset()
        )

    def prepare(self, target: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.dialogue_action.classify.return_value = {
            "target_system": target,
            "authorization_scope": [f"{target}_refresh"],
            "request": {"remote_write": False},
        }
        return self.service.prepare(
            {
                "name": "start_provider_refresh",
                "arguments": arguments,
                "action": {},
            },
            [],
            question="",
            cancelled=False,
            context={},
            allow_mutations=True,
        )

    def test_waiting_refresh_gets_wait_flag_and_keeps_default_window(self) -> None:
        for target in (GARMIN_ID, WAHOO_ID):
            with self.subTest(target=target):
                arguments: dict[str, Any] = {}

                self.prepare(target, arguments)

                self.assertIs(True, arguments["_wait_for_completion"])
                self.assertNotIn("days", arguments)

    def test_non_waiting_refresh_is_not_marked_to_wait(self) -> None:
        for target in (CALENDAR_ID, WEATHER_ID):
            with self.subTest(target=target):
                arguments: dict[str, Any] = {}

                self.prepare(target, arguments)

                self.assertNotIn("_wait_for_completion", arguments)


class CoachRefreshDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = Mock()
        self.queue.enqueue.return_value = {"id": "job-wahoo"}

    def test_non_waiting_refresh_enqueues_a_coach_job(self) -> None:
        service = ProviderRefreshCommandService(self.queue, {})

        result = service.start(WAHOO_ID, {"days": 14, "_wait_for_completion": False})

        self.assertEqual(
            {"ok": True, "status": "queued", "sync_job_id": "job-wahoo"}, result
        )
        self.queue.enqueue.assert_called_once_with(
            WAHOO_ID, "refresh", {"days": 14}, requested_by="coach"
        )

    def test_waiting_refresh_calls_its_synchronous_adapter(self) -> None:
        adapter = Mock()
        adapter.refresh.return_value = {
            "ok": True,
            "status": "completed",
            "provider": WAHOO_ID,
            "activity_days": 14,
            "synchronous_refresh": True,
        }
        service = ProviderRefreshCommandService(
            self.queue,
            synchronous_refreshes={WAHOO_ID: adapter},
        )
        cancel_event = threading.Event()
        arguments = {"days": 14, "_wait_for_completion": True}

        result = service.start(WAHOO_ID, arguments, cancel_event=cancel_event)

        self.assertIs(adapter.refresh.return_value, result)
        adapter.refresh.assert_called_once_with(WAHOO_ID, arguments, cancel_event)
        self.queue.enqueue.assert_not_called()

    def test_waiting_refresh_without_adapter_is_rejected(self) -> None:
        service = ProviderRefreshCommandService(self.queue, {})

        with self.assertRaises(AppError) as raised:
            service.start(WAHOO_ID, {"days": 14, "_wait_for_completion": True})

        self.assertEqual(400, raised.exception.status)
        self.assertEqual("invalid_refresh_request", raised.exception.reason)
        self.queue.enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
