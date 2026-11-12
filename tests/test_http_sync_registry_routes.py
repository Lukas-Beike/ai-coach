"""Table-derived sync HTTP routes keep the previous literal contract.

The literal tables below are the pre-table values. Derived sets must equal them
exactly, and every provider route reaches the same HTTP command path.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from support import dispatch_route

from backend.errors import AppError, public_error_contract
from backend.http_api.sync_commands import (
    GARMIN_FULL_RESYNC_PATH,
    GARMIN_SYNC_PATH,
    PROVIDER_NOT_CONFIGURED_MESSAGES,
    SYNC_BODY_PATHS,
    SYNC_POST_PATHS,
    SyncCommandEndpoint,
)
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.sync.provider_table import WAHOO_NOT_CONFIGURED_MESSAGE

INTERVALS_MESSAGE = (
    "Intervals.icu ist nicht eingerichtet. Zugangsdaten unter Mehr → Anbindungen "
    "hinterlegen."
)
GARMIN_MESSAGE = (
    "Garmin ist nicht konfiguriert. Unter Mehr → Anbindungen bei Garmin anmelden "
    "oder einen Schlüssel der Garmin Personal API hinterlegen."
)
INTERVALS_PERIOD_MESSAGE = (
    "Der Zeitraum für intervals muss -1 oder zwischen 1 und 365 Tagen liegen."
)
GARMIN_PERIOD_MESSAGE = (
    "Der Zeitraum für garmin muss -1 oder zwischen 1 und 90 Tagen liegen."
)
NON_INTEGER_PERIOD_MESSAGE = "Der Synchronisationszeitraum muss eine ganze Zahl sein."
PREVIOUS_POST_PATHS = frozenset(
    {
        "/api/sync/jobs",
        "/api/garmin/sync",
        "/api/external-calendar/sync",
        "/api/weather/sync",
        "/api/garmin/full-resync",
        "/api/wahoo/sync",
        "/api/wahoo/full-resync",
    }
)
PREVIOUS_BODY_PATHS = frozenset(
    {
        "/api/sync/jobs",
        "/api/garmin/sync",
        "/api/garmin/full-resync",
        "/api/wahoo/full-resync",
    }
)
PREVIOUS_NOT_CONFIGURED_MESSAGES = {
    "intervals": INTERVALS_MESSAGE,
    "garmin": GARMIN_MESSAGE,
    "wahoo": WAHOO_NOT_CONFIGURED_MESSAGE,
}


def _build() -> tuple[SyncCommandEndpoint, Mock, Mock]:
    """Return the endpoint with its queue and sync-state mocks."""
    queue = Mock()
    queue.enqueue.return_value = {"id": "job-1"}
    state = Mock()
    state.sync_period.return_value = 90
    state.set_sync_period.return_value = 7
    endpoint = SyncCommandEndpoint(
        queue,
        state,
        Mock(),
        lambda: "operation-1",
        {"intervals": 90, "garmin": 30},
        -1,
        provider_configured=Mock(return_value=True),
    )
    return endpoint, queue, state


class DerivedSyncTableTests(unittest.TestCase):
    def test_post_and_body_paths_equal_previous_literal_tables(self) -> None:
        self.assertEqual(PREVIOUS_POST_PATHS, SYNC_POST_PATHS)
        self.assertEqual(PREVIOUS_BODY_PATHS, SYNC_BODY_PATHS)

    def test_module_path_exports_equal_previous_literals(self) -> None:
        self.assertEqual("/api/garmin/sync", GARMIN_SYNC_PATH)
        self.assertEqual("/api/garmin/full-resync", GARMIN_FULL_RESYNC_PATH)

    def test_not_configured_messages_are_byte_identical(self) -> None:
        self.assertEqual(
            PREVIOUS_NOT_CONFIGURED_MESSAGES, PROVIDER_NOT_CONFIGURED_MESSAGES
        )

    def test_endpoint_accepts_exactly_the_previous_routes(self) -> None:
        for path in PREVIOUS_POST_PATHS:
            with self.subTest(path=path):
                self.assertTrue(SyncCommandEndpoint.handles(path))
                self.assertEqual(
                    path in PREVIOUS_BODY_PATHS, SyncCommandEndpoint.needs_body(path)
                )
        self.assertFalse(SyncCommandEndpoint.handles("/api/other"))


class SyncRouteDispatchTests(unittest.TestCase):
    def test_period_error_messages_are_byte_identical(self) -> None:
        cases = (
            ("/api/garmin/sync", 91, GARMIN_PERIOD_MESSAGE),
            ("/api/garmin/sync", "abc", NON_INTEGER_PERIOD_MESSAGE),
            ("/api/garmin/sync", None, NON_INTEGER_PERIOD_MESSAGE),
        )
        for path, days, expected in cases:
            with self.subTest(path=path, days=days):
                endpoint, queue, state = _build()
                state.set_sync_period.side_effect = ValueError("invalid")
                with self.assertRaises(AppError) as raised:
                    endpoint.execute(path, {"days": days})
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(expected, raised.exception.message)
                queue.enqueue.assert_not_called()

    def test_fixed_payload_routes_enqueue_without_sync_period(self) -> None:
        endpoint, queue, state = _build()
        self.assertEqual(
            (202, {"id": "job-1"}), endpoint.execute("/api/external-calendar/sync")
        )
        queue.enqueue.assert_called_with(
            "calendar", "refresh", {"reason": "manuell"}, requested_by="user"
        )
        self.assertEqual(
            (202, {"id": "job-1"}), endpoint.execute("/api/weather/sync", None)
        )
        queue.enqueue.assert_called_with(
            "weather",
            "refresh",
            {"reason": "manuell", "force": True},
            requested_by="user",
        )
        self.assertEqual(
            (202, {"id": "job-1"}), endpoint.execute("/api/wahoo/sync", None)
        )
        queue.enqueue.assert_called_with(
            "wahoo", "refresh", {"reason": "manual"}, requested_by="user"
        )
        state.set_sync_period.assert_not_called()

    def test_period_route_stores_the_period_and_enqueues_with_the_fixed_payload(
        self,
    ) -> None:
        endpoint, queue, state = _build()

        self.assertEqual(
            (202, {"id": "job-1"}), endpoint.execute("/api/garmin/sync", {"days": 7})
        )

        state.set_sync_period.assert_called_once_with("garmin", 7, -1)
        queue.enqueue.assert_called_once_with(
            "garmin", "refresh", {"days": 7, "reason": "manual"}, requested_by="user"
        )

    def test_job_route_validates_payload_shape_and_accepts_non_string_provider(
        self,
    ) -> None:
        endpoint, queue, _ = _build()
        with self.assertRaises(AppError) as raised:
            endpoint.execute("/api/sync/jobs", ["not", "an", "object"])
        self.assertEqual(
            public_error_contract(raised.exception), (400, "invalid_job_request")
        )
        queue.enqueue.assert_not_called()
        self.assertEqual(
            (202, {"id": "job-1"}),
            endpoint.execute(
                "/api/sync/jobs",
                {"provider": 5, "type": "refresh", "payload": {"reason": "manual"}},
            ),
        )
        queue.enqueue.assert_called_once_with(
            5,
            "refresh",
            {"reason": "manual"},
            requested_by="user",
            item_operations=None,
        )

    def test_unknown_path_is_rejected_by_execute(self) -> None:
        endpoint, _, _ = _build()
        with self.assertRaises(ValueError):
            endpoint.execute("/api/other")


class PostRouteTableTests(unittest.TestCase):
    """The POST route handles every provider path and reads a body only where due."""

    def test_every_path_is_handled_and_reads_a_body_only_when_required(self) -> None:
        for path in sorted(PREVIOUS_POST_PATHS):
            with self.subTest(path=path):
                endpoint = Mock()
                endpoint.execute.return_value = (202, {"id": "job-9"})
                handler = Mock()
                handler.read_json.return_value = {"days": 7}
                expects_body = path in PREVIOUS_BODY_PATHS

                handled = dispatch_route(
                    SyncCommandPostRoute(Mock(return_value=endpoint)),
                    handler,
                    path,
                    method="POST",
                )

                self.assertTrue(handled)
                self.assertEqual(expects_body, handler.read_json.called)
                endpoint.execute.assert_called_once_with(
                    path, {"days": 7} if expects_body else None
                )
                handler.send_json.assert_called_once_with(202, {"id": "job-9"})

    def test_a_path_no_provider_declares_is_not_handled(self) -> None:
        factory = Mock()
        handler = Mock()

        handled = dispatch_route(
            SyncCommandPostRoute(factory), handler, "/api/wahoo/other", method="POST"
        )

        self.assertFalse(handled)
        factory.assert_not_called()
        handler.read_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
