"""Registry-derived sync HTTP routes keep the previous literal contract.

The literal tables below are the pre-registry values. Derived sets must equal
them exactly, and a test-only provider registered in an injected registry must
flow through the same HTTP command path as the built-in providers.
"""

from __future__ import annotations

import dataclasses
import unittest
from unittest.mock import Mock

from backend.errors import AppError, public_error_contract
from backend.http_api.sync_commands import (
    GARMIN_FULL_RESYNC_PATH,
    GARMIN_SYNC_PATH,
    INTERVALS_FULL_RESYNC_PATH,
    PROVIDER_NOT_CONFIGURED_MESSAGES,
    SYNC_BODY_PATHS,
    SYNC_PATH,
    SYNC_POST_PATHS,
    SyncCommandEndpoint,
)
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.providers.descriptors import (
    WAHOO_NOT_CONFIGURED_MESSAGE,
    ManualSyncRoute,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry

try:
    from .provider_runtime_fakes import ACME_ID, acme_descriptor
except ImportError:
    from provider_runtime_fakes import ACME_ID, acme_descriptor

ACME_PATH = "/api/acme-mock/sync"
INTERVALS_MESSAGE = (
    "Intervals.icu ist nicht konfiguriert. Bitte INTERVALS_API_KEY in der "
    "Serverkonfiguration hinterlegen."
)
GARMIN_MESSAGE = (
    "Garmin ist nicht konfiguriert. Bitte GARMIN_EMAIL oder einen vorhandenen "
    "Garmin-Tokenstore einrichten."
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
        "/api/sync",
        "/api/intervals/full-resync",
        "/api/performance/refresh",
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
        "/api/sync",
        "/api/garmin/sync",
        "/api/intervals/full-resync",
        "/api/garmin/full-resync",
        "/api/wahoo/full-resync",
    }
)
PREVIOUS_NOT_CONFIGURED_MESSAGES = {
    "intervals": INTERVALS_MESSAGE,
    "garmin": GARMIN_MESSAGE,
    "wahoo": WAHOO_NOT_CONFIGURED_MESSAGE,
}


def _build(
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
) -> tuple[SyncCommandEndpoint, Mock, Mock, Mock, Mock]:
    queue = Mock()
    queue.enqueue.return_value = {"id": "job-1"}
    state = Mock()
    state.sync_period.return_value = 90
    state.set_sync_period.return_value = 7
    performance = Mock()
    performance.refresh.return_value = {"status": "refreshed"}
    full_resync = Mock()
    full_resync.provider_configured.return_value = True
    endpoint = SyncCommandEndpoint(
        queue,
        state,
        performance,
        full_resync,
        lambda: "operation-1",
        {"intervals": 90, "garmin": 30},
        -1,
        registry=registry,
    )
    return endpoint, queue, state, performance, full_resync


def _acme_registry(
    *,
    uses_sync_period: bool,
    payload: tuple[tuple[str, object], ...],
    message: str | None,
) -> ProviderRegistry:
    descriptor = dataclasses.replace(
        acme_descriptor(),
        manual_sync=ManualSyncRoute(
            path=ACME_PATH, uses_sync_period=uses_sync_period, payload=payload
        ),
        not_configured_message=message,
    )
    return ProviderRegistry((*DEFAULT_PROVIDER_REGISTRY.all(), descriptor))


class DerivedSyncTableTests(unittest.TestCase):
    def test_post_and_body_paths_equal_previous_literal_tables(self) -> None:
        self.assertEqual(PREVIOUS_POST_PATHS, SYNC_POST_PATHS)
        self.assertEqual(PREVIOUS_BODY_PATHS, SYNC_BODY_PATHS)

    def test_module_path_exports_equal_previous_literals(self) -> None:
        self.assertEqual("/api/sync", SYNC_PATH)
        self.assertEqual("/api/garmin/sync", GARMIN_SYNC_PATH)
        self.assertEqual("/api/intervals/full-resync", INTERVALS_FULL_RESYNC_PATH)
        self.assertEqual("/api/garmin/full-resync", GARMIN_FULL_RESYNC_PATH)

    def test_not_configured_messages_are_byte_identical(self) -> None:
        self.assertEqual(
            PREVIOUS_NOT_CONFIGURED_MESSAGES, PROVIDER_NOT_CONFIGURED_MESSAGES
        )

    def test_default_endpoint_accepts_exactly_the_previous_routes(self) -> None:
        endpoint, _, _, _, _ = _build()
        for path in PREVIOUS_POST_PATHS:
            with self.subTest(path=path):
                self.assertTrue(endpoint.accepts(path))
                self.assertEqual(
                    path in PREVIOUS_BODY_PATHS, endpoint.requires_body(path)
                )
        self.assertFalse(endpoint.accepts("/api/other"))
        self.assertFalse(endpoint.accepts("/api/acme-mock/sync"))


class DefaultRegistryDispatchTests(unittest.TestCase):
    def test_period_error_messages_are_byte_identical(self) -> None:
        cases = (
            ("/api/sync", 366, INTERVALS_PERIOD_MESSAGE),
            ("/api/garmin/sync", 91, GARMIN_PERIOD_MESSAGE),
            ("/api/sync", "abc", NON_INTEGER_PERIOD_MESSAGE),
            ("/api/garmin/sync", None, NON_INTEGER_PERIOD_MESSAGE),
        )
        for path, days, expected in cases:
            with self.subTest(path=path, days=days):
                endpoint, queue, state, _, _ = _build()
                state.set_sync_period.side_effect = ValueError("invalid")
                with self.assertRaises(AppError) as raised:
                    endpoint.execute(path, {"days": days})
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(expected, raised.exception.message)
                queue.enqueue.assert_not_called()

    def test_fixed_payload_routes_enqueue_without_sync_period(self) -> None:
        endpoint, queue, state, _, _ = _build()
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
        state.set_sync_period.assert_not_called()

    def test_performance_refresh_and_full_resync_keep_status_codes(self) -> None:
        endpoint, _, _, performance, full_resync = _build()
        self.assertEqual(
            (200, {"status": "refreshed"}), endpoint.execute("/api/performance/refresh")
        )
        performance.refresh.assert_called_once_with()
        full_resync.resync.return_value = {"status": "ok"}
        self.assertEqual(
            (200, {"status": "ok"}),
            endpoint.execute("/api/garmin/full-resync", {"confirm": "FULL_RESYNC"}),
        )
        full_resync.resync.assert_called_once_with("garmin", operation_id="operation-1")

    def test_job_route_validates_payload_shape_and_accepts_non_string_provider(
        self,
    ) -> None:
        endpoint, queue, _, _, _ = _build()
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
            5, "refresh", {"reason": "manual"}, requested_by="user"
        )

    def test_unknown_path_is_rejected_by_execute(self) -> None:
        endpoint, _, _, _, _ = _build()
        with self.assertRaises(ValueError):
            endpoint.execute("/api/other")


class InjectedRegistryMockProviderTests(unittest.TestCase):
    def test_fixed_payload_route_is_accepted_and_enqueues_fixed_payload(self) -> None:
        registry = _acme_registry(
            uses_sync_period=False,
            payload=(("reason", "manual"), ("force", True)),
            message=None,
        )
        endpoint, queue, _, _, _ = _build(registry)
        self.assertTrue(endpoint.accepts(ACME_PATH))
        self.assertFalse(endpoint.requires_body(ACME_PATH))
        self.assertFalse(SyncCommandEndpoint.handles(ACME_PATH))
        self.assertEqual((202, {"id": "job-1"}), endpoint.execute(ACME_PATH))
        queue.enqueue.assert_called_once_with(
            ACME_ID, "refresh", {"reason": "manual", "force": True}, requested_by="user"
        )

    def test_period_route_validates_days_and_enqueues_with_fixed_payload(self) -> None:
        registry = _acme_registry(
            uses_sync_period=True, payload=(("reason", "manual"),), message=None
        )
        endpoint, queue, state, _, _ = _build(registry)
        self.assertTrue(endpoint.requires_body(ACME_PATH))
        self.assertEqual(
            (202, {"id": "job-1"}), endpoint.execute(ACME_PATH, {"days": 7})
        )
        state.set_sync_period.assert_called_once_with(ACME_ID, 7, -1)
        queue.enqueue.assert_called_once_with(
            ACME_ID, "refresh", {"days": 7, "reason": "manual"}, requested_by="user"
        )

    def test_period_error_uses_descriptor_max_days(self) -> None:
        registry = _acme_registry(
            uses_sync_period=True, payload=(("reason", "manual"),), message=None
        )
        endpoint, queue, state, _, _ = _build(registry)
        state.set_sync_period.side_effect = ValueError("invalid")
        with self.assertRaises(AppError) as raised:
            endpoint.execute(ACME_PATH, {"days": 61})
        self.assertEqual(
            "Der Zeitraum für acme-mock muss -1 oder zwischen 1 und 60 Tagen liegen.",
            raised.exception.message,
        )
        queue.enqueue.assert_not_called()

    def test_not_configured_message_rejects_manual_and_job_routes(self) -> None:
        message = "Acme-Mock ist nicht konfiguriert."
        registry = _acme_registry(
            uses_sync_period=True, payload=(("reason", "manual"),), message=message
        )
        endpoint, queue, state, _, full_resync = _build(registry)
        full_resync.provider_configured.return_value = False
        with self.assertRaises(AppError) as raised:
            endpoint.execute(ACME_PATH, {"days": 7})
        self.assertEqual(
            public_error_contract(raised.exception), (409, "not_configured")
        )
        self.assertEqual(message, raised.exception.message)
        full_resync.provider_configured.assert_called_once_with(ACME_ID)
        state.set_sync_period.assert_not_called()
        queue.enqueue.assert_not_called()
        with self.assertRaises(AppError) as job_error:
            endpoint.execute(
                "/api/sync/jobs",
                {"provider": ACME_ID, "type": "refresh", "payload": {}},
            )
        self.assertEqual(message, job_error.exception.message)
        queue.enqueue.assert_not_called()

    def test_not_configured_lookup_matches_normalized_descriptor_id(self) -> None:
        message = "Acme-Mock ist nicht konfiguriert."
        descriptor = dataclasses.replace(
            acme_descriptor(),
            provider_id="Acme-Mock",
            manual_sync=ManualSyncRoute(
                path=ACME_PATH, uses_sync_period=False, payload=(("reason", "manual"),)
            ),
            not_configured_message=message,
        )
        registry = ProviderRegistry((*DEFAULT_PROVIDER_REGISTRY.all(), descriptor))
        endpoint, queue, _, _, full_resync = _build(registry)
        full_resync.provider_configured.return_value = False
        with self.assertRaises(AppError) as raised:
            endpoint.execute(ACME_PATH)
        self.assertEqual(message, raised.exception.message)
        full_resync.provider_configured.assert_called_once_with(ACME_ID)
        queue.enqueue.assert_not_called()

    def test_route_without_not_configured_message_skips_configuration_check(
        self,
    ) -> None:
        registry = _acme_registry(
            uses_sync_period=False, payload=(("reason", "manual"),), message=None
        )
        endpoint, queue, _, _, full_resync = _build(registry)
        full_resync.provider_configured.return_value = False
        self.assertEqual((202, {"id": "job-1"}), endpoint.execute(ACME_PATH))
        full_resync.provider_configured.assert_not_called()
        queue.enqueue.assert_called_once()


class InjectedRegistryPostRouteTests(unittest.TestCase):
    """The POST route decides acceptance and body reads from its injected registry."""

    def test_injected_fixed_payload_route_is_accepted_without_body(self) -> None:
        registry = _acme_registry(
            uses_sync_period=False,
            payload=(("reason", "manual"),),
            message=None,
        )
        endpoint = Mock()
        endpoint.execute.return_value = (202, {"id": "job-9"})
        handler = Mock()

        handled = SyncCommandPostRoute(lambda: endpoint, registry=registry).handle(
            handler, ACME_PATH
        )

        self.assertTrue(handled)
        handler.read_json.assert_not_called()
        endpoint.execute.assert_called_once_with(ACME_PATH, None)
        handler.send_json.assert_called_once_with(202, {"id": "job-9"})

    def test_injected_period_route_reads_the_body(self) -> None:
        registry = _acme_registry(
            uses_sync_period=True,
            payload=(("reason", "manual"),),
            message=None,
        )
        endpoint = Mock()
        endpoint.execute.return_value = (202, {"id": "job-10"})
        handler = Mock()
        handler.read_json.return_value = {"days": 7}

        handled = SyncCommandPostRoute(lambda: endpoint, registry=registry).handle(
            handler, ACME_PATH
        )

        self.assertTrue(handled)
        handler.read_json.assert_called_once_with()
        endpoint.execute.assert_called_once_with(ACME_PATH, {"days": 7})

    def test_default_route_rejects_injected_path_without_building_endpoint(
        self,
    ) -> None:
        factory = Mock()
        handler = Mock()

        handled = SyncCommandPostRoute(factory).handle(handler, ACME_PATH)

        self.assertFalse(handled)
        factory.assert_not_called()
        handler.read_json.assert_not_called()
        handler.send_json.assert_not_called()

    def test_injected_route_rejects_a_path_no_registry_provider_declares(self) -> None:
        registry = _acme_registry(
            uses_sync_period=False,
            payload=(("reason", "manual"),),
            message=None,
        )
        factory = Mock()
        handler = Mock()

        handled = SyncCommandPostRoute(factory, registry=registry).handle(
            handler, "/api/acme-mock/other"
        )

        self.assertFalse(handled)
        factory.assert_not_called()
        handler.read_json.assert_not_called()

    def test_injected_registry_keeps_builtin_sync_paths(self) -> None:
        registry = _acme_registry(
            uses_sync_period=False,
            payload=(("reason", "manual"),),
            message=None,
        )
        endpoint = Mock()
        endpoint.execute.return_value = (202, {"id": "job-11"})
        handler = Mock()
        handler.read_json.return_value = {"days": 3}

        self.assertTrue(
            SyncCommandPostRoute(lambda: endpoint, registry=registry).handle(
                handler, "/api/sync"
            )
        )
        handler.read_json.assert_called_once_with()
        endpoint.execute.assert_called_once_with("/api/sync", {"days": 3})


if __name__ == "__main__":
    unittest.main()
