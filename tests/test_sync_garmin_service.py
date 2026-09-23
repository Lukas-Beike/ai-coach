"""Isolated Garmin synchronization lifecycle tests."""

from __future__ import annotations

import threading
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from backend.config import Config
from backend.errors import AppError
from backend.sync.garmin_service import (
    GarminRemoteReader,
    GarminSyncCoordination,
    GarminSyncLifecycleState,
    GarminSyncService,
    GarminSyncSource,
)


class _Database:
    @contextmanager
    def unit_of_work(self):
        yield object()


class _KeyValues:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, _db, key: str) -> str | None:
        return self.values.get(key)

    def set(self, _db, key: str, value: str) -> None:
        self.values[key] = value


class _Scope:
    operation_id = "observed-operation"
    result = None


class _Observer:
    @contextmanager
    def observe(self, provider, area, reason, operation_id):
        self.arguments = (provider, area, reason, operation_id)
        scope = _Scope()
        yield scope
        self.result = scope.result


class _Gate:
    @contextmanager
    def operation(self):
        self.entered = True
        yield


class _FixtureLoader:
    def __init__(self, path: Path | None, payload: dict | None = None) -> None:
        self._path = path
        self.payload = payload or {}

    def path(self) -> Path | None:
        return self._path

    def load(self, days: int) -> dict:
        self.days = days
        return self.payload


class _PayloadService:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {}

    def snapshot(self) -> dict:
        return self.payload

    def prepare_fixture(self, payload: dict) -> dict:
        self.prepared = ("fixture", payload)
        return payload

    def prepare_remote(self, payload: dict) -> dict:
        self.prepared = ("remote", payload)
        return payload


class _StateService:
    def __init__(self) -> None:
        self.errors = []

    def persist_payload(self, payload, end_date, fallback_end, **kwargs):
        self.persisted = (payload, end_date, fallback_end, kwargs)
        return {"status": "ok", "synced_at": payload["synced_at"]}

    def persist_error(self, error, source="sync") -> None:
        self.errors.append((error, source))


class _Writer:
    def __init__(self) -> None:
        self.calls = []

    def write(self, *args) -> None:
        self.calls.append(args)


class _RemoteReader:
    def __init__(self, *, available=True, configured=True) -> None:
        self._available = available
        self._configured = configured

    def available(self) -> bool:
        return self._available

    def configured(self) -> bool:
        return self._configured

    def fetch(self, days, end_date, *, status, cancel_event=None):
        self.arguments = (days, end_date, cancel_event)
        status("Garmin: Zeitraum 1/1 wird synchronisiert…")
        return (
            {"synced_at": "2026-09-20T10:00:00+00:00", "activities": []},
            [(date(2026, 9, 1), date(2026, 9, 20))],
        )


def _config(**changes) -> Config:
    return replace(
        Config(
            port=8080,
            openai_api_key="",
            openai_base_url="",
            openai_model="",
            gemini_api_key="",
            gemini_model="",
            ai_provider="openai",
            intervals_api_key="",
            intervals_athlete_id="",
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
            garmin_fixture_path="",
            calendar_ical_url="",
            app_password="",
            secure_cookies=False,
            data_retention_days=30,
        ),
        garmin_email="athlete@example.invalid",
        garmin_password="secret",
        garmin_tokenstore="missing-tokenstore",
        **changes,
    )


class GarminSyncServiceTests(unittest.TestCase):
    def make_service(
        self,
        *,
        fixture: _FixtureLoader | None = None,
        remote: _RemoteReader | None = None,
        payload: _PayloadService | None = None,
        state: _StateService | None = None,
        lock: threading.Lock | None = None,
        wait_seconds: float = 0.1,
    ):
        self.database = _Database()
        self.key_values = _KeyValues()
        self.fixture = fixture or _FixtureLoader(None)
        self.remote = remote or _RemoteReader()
        self.payload = payload or _PayloadService()
        self.state = state or _StateService()
        self.writer = _Writer()
        self.observer = _Observer()
        self.gate = _Gate()
        self.lock = lock or threading.Lock()
        self.lifecycle_state = GarminSyncLifecycleState(
            self.database,
            self.key_values,
            lambda: "2026-09-20T12:00:00+00:00",
            Mock(),
        )
        return GarminSyncService(
            GarminSyncSource(self.fixture, self.remote, date(2000, 1, 1)),
            self.payload,
            self.state,
            self.writer,
            self.observer,
            GarminSyncCoordination(
                self.lock,
                self.gate,
                wait_seconds=wait_seconds,
            ),
            self.lifecycle_state,
        )

    def test_fixture_flow_owns_status_persistence_and_cleanup(self):
        fixture_payload = {
            "synced_at": "2026-09-20T10:00:00+00:00",
            "activities": [],
        }
        service = self.make_service(
            fixture=_FixtureLoader(Path("fixture.json"), fixture_payload)
        )

        result = service.sync(days=14, operation_id="explicit", reason="manual")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.fixture.days, 14)
        self.assertEqual(self.payload.prepared, ("fixture", fixture_payload))
        self.assertEqual(
            self.state.persisted[1:],
            (
                None,
                date(2026, 9, 20),
                {"source": "fixture", "historical_cursor": "2000-01-01"},
            ),
        )
        self.assertEqual(self.writer.calls[-1][1:4], ("completed", "complete", 100))
        self.assertEqual(self.key_values.values["garmin_sync_status"], "")
        self.assertFalse(self.lock.locked())
        self.assertEqual(self.observer.result, result)

    def test_remote_flow_preserves_window_and_status_contract(self):
        service = self.make_service()
        end_date = date(2026, 9, 20)

        result = service.sync(days=20, end_date=end_date)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.remote.arguments, (20, end_date, None))
        self.assertEqual(self.payload.prepared[0], "remote")
        self.assertEqual(
            self.state.persisted[1:],
            (
                end_date,
                date(2026, 9, 20),
                {"source": None, "historical_cursor": "2026-09-01"},
            ),
        )
        self.assertEqual(self.key_values.values["garmin_sync_status"], "")

    def test_unavailable_and_unconfigured_remote_persist_configuration_error(self):
        for remote, expected in (
            (_RemoteReader(available=False), "Bibliothek"),
            (_RemoteReader(available=True, configured=False), "GARMIN_EMAIL"),
        ):
            with self.subTest(expected=expected):
                service = self.make_service(remote=remote)
                with self.assertRaises(AppError) as raised:
                    service.sync()
                self.assertEqual(raised.exception.status, 503)
                self.assertIn(expected, raised.exception.message)
                self.assertEqual(self.state.errors[0][1], "configuration")
                self.assertFalse(self.lock.locked())

    def test_lock_contention_and_cancellation_do_not_mutate_payload(self):
        held_lock = threading.Lock()
        held_lock.acquire()
        service = self.make_service(lock=held_lock)
        try:
            self.assertEqual(service.sync(), {"status": "already_running"})
        finally:
            held_lock.release()

        cancelled = threading.Event()
        cancelled.set()
        service = self.make_service()
        with self.assertRaises(AppError) as raised:
            service.sync(cancel_event=cancelled)
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertFalse(hasattr(self.payload, "prepared"))

    def test_wait_for_existing_returns_the_completed_sync_without_refetching(self):
        lock = Mock()
        lock.acquire.side_effect = [False, True]
        service = self.make_service(lock=lock, wait_seconds=1)
        original_get = self.key_values.get
        sync_values = iter(("old", "new"))

        def get_value(db, key):
            return (
                next(sync_values)
                if key == "last_garmin_sync_at"
                else original_get(db, key)
            )

        with patch.object(self.key_values, "get", side_effect=get_value):
            result = service.sync(wait_for_existing=True)

        self.assertEqual(
            result,
            {"status": "ok", "waited_for_existing": True, "synced_at": "new"},
        )
        self.assertFalse(hasattr(self.remote, "arguments"))
        lock.release.assert_called_once_with()

    def test_failure_records_safe_state_and_releases_lock(self):
        class FailingPayload(_PayloadService):
            def prepare_remote(self, payload):
                raise RuntimeError("synthetic failure")

        service = self.make_service(payload=FailingPayload())

        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            service.sync(reason="test")

        self.assertEqual(len(self.state.errors), 1)
        self.assertEqual(self.writer.calls[-1][1:4], ("error", "error", 100))
        self.assertEqual(self.key_values.values["garmin_sync_status"], "")
        self.assertFalse(self.lock.locked())


class GarminRemoteReaderTests(unittest.TestCase):
    def make_reader(self, client_factory, state=None):
        self.state = state or Mock()
        return GarminRemoteReader(
            _config(),
            client_factory,
            self.state,
            Mock(),
            lambda value: value,
            Mock(),
            lambda: "2026-09-20T10:00:00+00:00",
            lambda: date(2026, 9, 20),
            date(2000, 1, 1),
            90,
            -1,
        )

    def test_reader_logs_in_and_collects_with_historical_options(self):
        client = Mock()
        client.login.return_value = (False, None)
        factory = Mock()
        factory.available.return_value = True
        factory.create.return_value = client
        reader = self.make_reader(factory)
        collected = {
            "synced_at": "2026-09-20T10:00:00+00:00",
            "provider_sync": {"pagination": {}},
        }

        with (
            patch(
                "backend.sync.garmin_service.provider_http.external_call",
                side_effect=lambda _service, _operation, call, _details, **_kwargs: (
                    call()
                ),
            ),
            patch(
                "backend.sync.garmin_service.collect_garmin_data",
                return_value=collected,
            ) as collect,
        ):
            payload, windows = reader.fetch(30, date(2026, 9, 20), status=Mock())

        self.assertIs(payload, collected)
        self.assertEqual(windows, [(date(2026, 8, 22), date(2026, 9, 20))])
        client.login.assert_called_once_with("missing-tokenstore")
        options = collect.call_args.kwargs["options"]
        self.assertFalse(options.include_recovery)
        self.assertFalse(options.include_current_metrics)

    def test_reader_mfa_and_cancellation_keep_collection_from_running(self):
        client = Mock()
        client.login.return_value = (True, None)
        factory = Mock()
        factory.available.return_value = True
        factory.create.return_value = client
        reader = self.make_reader(factory)
        with (
            patch(
                "backend.sync.garmin_service.provider_http.external_call",
                side_effect=lambda _service, _operation, call, _details, **_kwargs: (
                    call()
                ),
            ),
            patch("backend.sync.garmin_service.collect_garmin_data") as collect,
            self.assertRaises(AppError) as raised,
        ):
            reader.fetch(1, None, status=Mock())
        self.assertEqual(raised.exception.status, 401)
        collect.assert_not_called()

        cancelled = threading.Event()
        cancelled.set()
        client.login.return_value = (False, None)
        with (
            patch("backend.sync.garmin_service.provider_http.external_call") as call,
            self.assertRaises(AppError) as raised,
        ):
            reader.fetch(1, None, status=Mock(), cancel_event=cancelled)
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
