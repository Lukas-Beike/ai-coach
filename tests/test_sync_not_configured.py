"""Provider-not-configured failures are non-retryable and rejected before enqueue."""

from __future__ import annotations

import ast
import threading
import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock

from support import dispatch_route

from backend.errors import AppError, public_error_contract
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.providers.descriptors import GARMIN_NOT_CONFIGURED_MESSAGE
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.full_resync import FullProviderResyncService
from backend.sync.garmin_service import GarminSyncService
from backend.sync.provider_resync_assembly import full_resync_handlers
from backend.sync.refresh import ProviderRefreshTracker, retry_at

try:
    from .architecture_registry import BACKEND_ROOT
except ImportError:
    from architecture_registry import BACKEND_ROOT

NOT_CONFIGURED_CONSTANTS = frozenset(
    {"INTERVALS_API_KEY_ERROR", "OPENAI_API_KEY_ERROR", "GARMIN_NOT_CONFIGURED_MESSAGE"}
)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _resync_service(
    config: Mock, *, garmin_configured: bool = False
) -> FullProviderResyncService:
    garmin_service = Mock()
    garmin_service.configured.return_value = garmin_configured
    handlers = full_resync_handlers(
        garmin_service=garmin_service,
        all_sync_days=-1,
    )
    return FullProviderResyncService(handlers, Mock(), Mock())


def _full_resync_garmin_not_configured() -> None:
    _resync_service(Mock(intervals_api_key="")).resync("garmin")


def _external_calendar_not_configured() -> None:
    service = ExternalCalendarSyncService(
        config=Mock(calendar_ical_url=""),
        database_manager=Mock(),
        key_value_repository=Mock(),
        daily_sync_marker_service=Mock(),
        observer=MagicMock(),
        adaptive_replan_preview_service=Mock(),
        state_event_buffer=Mock(),
        logger=Mock(),
        redactor=str,
        local_now=Mock(),
        utc_now=Mock(),
        app_version="test",
        lock=threading.Lock(),
    )
    service.sync(reason="test")


def _garmin_not_configured() -> None:
    # The helper is called unbound so the test needs no full Garmin sync graph.
    GarminSyncService._configuration_error(
        Mock(),
        "not_configured",
        GARMIN_NOT_CONFIGURED_MESSAGE,
        GARMIN_NOT_CONFIGURED_MESSAGE,
        reason="not_configured",
    )


def _is_app_error_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "AppError") or (
        isinstance(func, ast.Attribute) and func.attr == "AppError"
    )


def _is_not_configured_message(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "nicht konfiguriert" in node.value
    if isinstance(node, ast.Name):
        return node.id in NOT_CONFIGURED_CONSTANTS
    return False


def _declares_not_configured_reason(node: ast.Call) -> bool:
    return any(
        keyword.arg == "reason"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value == "not_configured"
        for keyword in node.keywords
    )


class NotConfiguredClassificationTests(unittest.TestCase):
    def test_english_fallback_and_transient_failures_keep_classification(self):
        fallback = AppError(503, "Provider is not configured.")
        self.assertEqual(
            ProviderRefreshTracker.error_code(fallback), "invalid_configuration"
        )
        transient = AppError(503, "Der Anbieter ist nicht erreichbar.")
        code = ProviderRefreshTracker.error_code(transient)
        self.assertEqual(code, "provider_error")
        self.assertIsNotNone(
            retry_at(
                [], current_error_code=code, now=NOW, base_seconds=60, max_seconds=3600
            )
        )

    def test_not_configured_public_contract_keeps_reason(self):
        error = AppError(
            503, "Intervals.icu ist nicht konfiguriert.", reason="not_configured"
        )
        self.assertEqual(public_error_contract(error), (503, "not_configured"))


class NotConfiguredReasonContractTests(unittest.TestCase):
    def test_every_provider_not_configured_app_error_declares_reason(self):
        sites: list[str] = []
        violations: list[str] = []
        for source in sorted(BACKEND_ROOT.rglob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if not _is_app_error_call(node) or len(node.args) < 2:
                    continue
                if not _is_not_configured_message(node.args[1]):
                    continue
                location = f"{source.relative_to(BACKEND_ROOT.parent)}:{node.lineno}"
                sites.append(location)
                if not _declares_not_configured_reason(node):
                    violations.append(location)
        self.assertGreaterEqual(len(sites), 15)
        self.assertEqual(violations, [])


class NotConfiguredSyncRouteTests(unittest.TestCase):
    def setUp(self):
        self.queue = Mock()
        self.state = Mock()
        self.state.sync_period.return_value = 90
        self.state.set_sync_period.return_value = 7
        self.config = Mock(intervals_api_key="")
        full_resync = _resync_service(self.config)
        self.endpoint = SyncCommandEndpoint(
            self.queue,
            self.state,
            full_resync,
            lambda: "operation-1",
            {"intervals": 90, "garmin": 30},
            -1,
            provider_configured=lambda provider: (
                provider == "intervals" and bool(self.config.intervals_api_key)
            ),
        )
        self.route = SyncCommandPostRoute(lambda: self.endpoint)

    def assert_rejected_before_mutation(self, path, body, message_fragment):
        handler = Mock()
        handler.read_json.return_value = body
        with self.assertRaises(AppError) as raised:
            dispatch_route(self.route, handler, path, method="POST")
        self.assertEqual(
            public_error_contract(raised.exception), (409, "not_configured")
        )
        self.assertIn(message_fragment, raised.exception.message)
        self.queue.enqueue.assert_not_called()
        self.state.set_sync_period.assert_not_called()
        handler.send_json.assert_not_called()

    def test_manual_garmin_refresh_is_rejected_before_period_or_job(self):
        self.assert_rejected_before_mutation(
            "/api/garmin/sync", {"days": 7}, "Garmin ist nicht konfiguriert"
        )

    def test_garmin_job_is_rejected_before_enqueue(self):
        self.assert_rejected_before_mutation(
            "/api/sync/jobs",
            {"provider": "garmin", "type": "refresh", "payload": {"days": 7}},
            "Garmin ist nicht konfiguriert",
        )


if __name__ == "__main__":
    unittest.main()
