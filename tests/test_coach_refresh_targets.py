"""Coach refresh targets derive from the provider registry, not literals."""

from __future__ import annotations

import dataclasses
import threading
import unittest
from typing import Any
from unittest.mock import MagicMock, Mock

from provider_runtime_fakes import ACME_ID, acme_descriptor

from backend.coach.authorization import (
    REQUEST_SCHEMA,
    dialogue_tools,
    request_target_enum,
    validate_request,
)
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.errors import AppError
from backend.providers.descriptors import (
    CALENDAR_ID,
    DEFAULT_PROVIDER_DESCRIPTORS,
    GARMIN_ID,
    INTERVALS_ID,
    WAHOO_ID,
    WEATHER_ID,
)
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry

USER_MESSAGE_ID = 7
DEFAULT_TARGETS = [
    "local",
    INTERVALS_ID,
    GARMIN_ID,
    CALENDAR_ID,
    WEATHER_ID,
    WAHOO_ID,
]


def acme_registry(*, waits: bool = False) -> ProviderRegistry:
    descriptor = dataclasses.replace(
        acme_descriptor(), coach_waits_for_completion=waits
    )
    return ProviderRegistry((*DEFAULT_PROVIDER_DESCRIPTORS, descriptor))


def acme_request(target: str = ACME_ID) -> dict[str, Any]:
    return {
        "summary": "Refresh the acme mock source.",
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

    def test_mock_provider_extends_enum_at_its_rank(self) -> None:
        registry = acme_registry()

        self.assertEqual(
            [*DEFAULT_TARGETS, ACME_ID],
            request_target_enum(registry),
        )

    def test_mock_target_is_accepted_only_by_registry_that_declares_it(self) -> None:
        user_ids = {USER_MESSAGE_ID}

        accepted = validate_request(
            acme_request(),
            user_ids,
            USER_MESSAGE_ID,
            registry=acme_registry(),
        )
        self.assertEqual(ACME_ID, accepted["target"])

        with self.assertRaises(ValueError) as raised:
            validate_request(
                acme_request(),
                user_ids,
                USER_MESSAGE_ID,
                registry=DEFAULT_PROVIDER_REGISTRY,
            )
        self.assertEqual("request_target", str(raised.exception))

    def test_dialogue_tools_expose_mock_target_in_request_schema(self) -> None:
        tools = [
            {
                "name": "start_provider_refresh",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

        result = dialogue_tools(tools, set(), registry=acme_registry())

        enum = result[0]["parameters"]["properties"]["_request"]["properties"][
            "target"
        ]["enum"]
        self.assertEqual([*DEFAULT_TARGETS, ACME_ID], enum)


class CoachRefreshClassificationTests(unittest.TestCase):
    def make_service(self, registry: ProviderRegistry) -> CoachDialogueActionService:
        return CoachDialogueActionService(
            MagicMock(),
            MagicMock(),
            Mock(),
            Mock(),
            Mock(),
            registry=registry,
        )

    def test_mock_refresh_is_classified_as_remote_sync_with_its_scope(self) -> None:
        service = self.make_service(acme_registry())
        context = {
            "messages": [{"id": USER_MESSAGE_ID, "role": "user"}],
            "current_user_message_id": USER_MESSAGE_ID,
        }

        action = service.classify(
            "start_provider_refresh",
            {"_request": acme_request(), "days": 14},
            context,
            allow_mutations=True,
        )

        self.assertEqual("remote_sync", action["intent"])
        self.assertEqual(ACME_ID, action["target_system"])
        self.assertEqual([f"{ACME_ID}_refresh"], action["authorization_scope"])

    def test_mock_refresh_is_rejected_when_registry_does_not_declare_it(self) -> None:
        service = self.make_service(DEFAULT_PROVIDER_REGISTRY)
        context = {
            "messages": [{"id": USER_MESSAGE_ID, "role": "user"}],
            "current_user_message_id": USER_MESSAGE_ID,
        }

        with self.assertRaises(AppError) as raised:
            service.classify(
                "start_provider_refresh",
                {"_request": acme_request(), "days": 14},
                context,
                allow_mutations=True,
            )
        self.assertEqual("request_invalid", raised.exception.reason)
        self.assertEqual(
            "request_target", getattr(raised.exception, "validation_reason", None)
        )


class CoachRefreshPreparationTests(unittest.TestCase):
    def make_service(
        self, registry: ProviderRegistry
    ) -> tuple[CoachStructuredToolPreparationService, Mock]:
        dialogue_action = Mock(spec=CoachDialogueActionService)
        service = CoachStructuredToolPreparationService(
            dialogue_action,
            Mock(),
            frozenset(),
            registry=registry,
        )
        return service, dialogue_action

    @staticmethod
    def classified_action() -> dict[str, Any]:
        return {
            "target_system": ACME_ID,
            "authorization_scope": [f"{ACME_ID}_refresh"],
            "request": {"remote_write": False},
        }

    def prepare(
        self, service: CoachStructuredToolPreparationService, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return service.prepare(
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

    def test_waiting_mock_refresh_gets_wait_flag_and_keeps_default_window(
        self,
    ) -> None:
        service, dialogue_action = self.make_service(acme_registry(waits=True))
        dialogue_action.classify.return_value = self.classified_action()
        arguments: dict[str, Any] = {}

        self.prepare(service, arguments)

        self.assertIs(True, arguments["_wait_for_completion"])
        self.assertNotIn("days", arguments)

    def test_non_waiting_mock_refresh_is_not_marked_to_wait(self) -> None:
        service, dialogue_action = self.make_service(acme_registry(waits=False))
        dialogue_action.classify.return_value = self.classified_action()
        arguments: dict[str, Any] = {}

        self.prepare(service, arguments)

        self.assertNotIn("_wait_for_completion", arguments)


class CoachRefreshDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = Mock()
        self.queue.enqueue.return_value = {"id": "job-acme"}
        self.intervals = Mock()

    def test_non_waiting_mock_refresh_enqueues_a_coach_job(self) -> None:
        service = ProviderRefreshCommandService(self.queue, self.intervals, -1)

        result = service.start(ACME_ID, {"days": 14, "_wait_for_completion": False})

        self.assertEqual(
            {"ok": True, "status": "queued", "sync_job_id": "job-acme"}, result
        )
        self.queue.enqueue.assert_called_once_with(
            ACME_ID, "refresh", {"days": 14}, requested_by="coach"
        )
        self.intervals.sync.assert_not_called()

    def test_waiting_mock_refresh_calls_its_synchronous_adapter(self) -> None:
        adapter = Mock()
        adapter.refresh.return_value = {
            "ok": True,
            "status": "completed",
            "provider": ACME_ID,
            "activity_days": 14,
            "synchronous_refresh": True,
        }
        service = ProviderRefreshCommandService(
            self.queue,
            self.intervals,
            -1,
            synchronous_refreshes={ACME_ID: adapter},
        )
        cancel_event = threading.Event()
        arguments = {"days": 14, "_wait_for_completion": True}

        result = service.start(ACME_ID, arguments, cancel_event=cancel_event)

        self.assertIs(adapter.refresh.return_value, result)
        adapter.refresh.assert_called_once_with(ACME_ID, arguments, cancel_event)
        self.queue.enqueue.assert_not_called()

    def test_waiting_refresh_without_adapter_is_rejected(self) -> None:
        service = ProviderRefreshCommandService(self.queue, self.intervals, -1)

        with self.assertRaises(AppError) as raised:
            service.start(ACME_ID, {"days": 14, "_wait_for_completion": True})

        self.assertEqual(400, raised.exception.status)
        self.assertEqual("invalid_refresh_request", raised.exception.reason)
        self.queue.enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
