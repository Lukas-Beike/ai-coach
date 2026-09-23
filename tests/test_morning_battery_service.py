"""Focused tests for stateful morning Body Battery orchestration."""

from __future__ import annotations

import copy
import json
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

from backend.performance.morning_battery_service import (
    MORNING_BATTERY_HISTORY_KEY,
    MorningBatteryClock,
    MorningBatteryEvents,
    MorningBatteryExecutionGate,
    MorningBatteryRetryPolicy,
    MorningBatterySource,
    MorningBatteryStore,
    MorningBodyBatteryService,
)

CHECKIN_DATE = date(2026, 9, 4)
NOW = datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc)


class FakeLock:
    def __init__(self, trace: list[str], acquire_result: bool = True) -> None:
        self.trace = trace
        self.acquire_result = acquire_result
        self.acquire_calls = 0
        self.release_calls = 0

    def acquire(self, *, timeout: int) -> bool:
        self.trace.append(f"lock:acquire:{timeout}")
        self.acquire_calls += 1
        return self.acquire_result

    def release(self) -> None:
        self.trace.append("lock:release")
        self.release_calls += 1


class FakeLogger:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, object], object]] = []

    def warning(
        self, message: str, *, extra: dict[str, object], exc_info: object
    ) -> None:
        self.warnings.append((message, extra, exc_info))


class FakeGate:
    def __init__(self, trace: list[str], name: str) -> None:
        self.trace = trace
        self.name = name

    @contextmanager
    def operation(self):
        self.trace.append(f"{self.name}:enter")
        try:
            yield
        finally:
            self.trace.append(f"{self.name}:exit")


class Harness:
    def __init__(
        self,
        *,
        snapshot: dict[str, object] | None = None,
        history: dict[str, object] | None = None,
        errors: list[dict[str, object]] | None = None,
    ) -> None:
        self.trace: list[str] = []
        self.values = {
            "garmin_snapshot": json.dumps(snapshot or {}),
            MORNING_BATTERY_HISTORY_KEY: json.dumps(history or {}),
            "last_garmin_error": json.dumps(errors or []),
        }
        self.fail_commit_number: int | None = None
        self.transaction_count = 0
        self.lock = FakeLock(self.trace)
        self.logger = FakeLogger()
        self.events: list[tuple[str, dict[str, object]]] = []
        self.safe_errors: list[Exception] = []
        self.fixture_calls: list[int] = []
        self.remote_calls: list[date] = []
        self.fixture_payload: object = {}
        self.remote_payload: tuple[object, object] = ({}, [])
        self.fixture_is_available = False
        self.is_remote_configured = False

    def get(self, _db: object, key: str) -> str | None:
        return self.values.get(key)

    def set(self, _db: object, key: str, value: str) -> None:
        self.trace.append(f"write:{key}")
        self.values[key] = value

    def unit_of_work(self):
        @contextmanager
        def transaction():
            self.transaction_count += 1
            transaction_number = self.transaction_count
            before = copy.deepcopy(self.values)
            self.trace.append("transaction:begin")
            try:
                yield self
                if self.fail_commit_number == transaction_number:
                    raise RuntimeError("fake commit failure")
            except Exception:
                self.values = before
                self.trace.append("transaction:rollback")
                raise
            self.trace.append("transaction:commit")

        return transaction()

    def path(self) -> object | None:
        return object() if self.fixture_is_available else None

    def load(self, days: int) -> object:
        self.fixture_calls.append(days)
        return self.fixture_payload

    def fetch_remote(self, requested_date: date) -> tuple[object, object]:
        self.remote_calls.append(requested_date)
        if isinstance(self.remote_payload, Exception):
            raise self.remote_payload
        return self.remote_payload

    def safe_error(self, exc: Exception) -> str:
        self.safe_errors.append(exc)
        return "sanitized fake error"

    def publish_event(self, topic: str, payload: dict[str, object]) -> None:
        self.trace.append("event:publish")
        self.events.append((topic, payload))

    def make_service(self, **overrides: object) -> MorningBodyBatteryService:
        fixture_loader = overrides.get("fixture_loader", self)
        return MorningBodyBatteryService(
            MorningBatteryStore(self, self),
            MorningBatterySource(
                fixture_loader,
                lambda: self.is_remote_configured,
                self.fetch_remote,
                self.safe_error,
            ),
            MorningBatteryExecutionGate(
                self.lock,
                FakeGate(self.trace, "maintenance"),
                FakeGate(self.trace, "provider"),
                120,
            ),
            MorningBatteryClock(
                lambda: NOW,
                overrides.get("local_now", lambda: NOW),  # type: ignore[arg-type]
            ),
            MorningBatteryEvents(self.publish_event, self.logger),
            MorningBatteryRetryPolicy(),
        )


def sleep_payload() -> dict[str, object]:
    return {
        "dailySleepDTO": {
            "sleepStartTimestampGMT": "2026-09-03T21:30:00Z",
            "sleepEndTimestampGMT": "2026-09-04T05:45:00Z",
        }
    }


def body_battery_records() -> list[dict[str, object]]:
    return [
        {
            "bodyBatteryValuesArray": [
                ["2026-09-03T21:25:00Z", 30],
                ["2026-09-04T05:45:00Z", 75],
            ]
        }
    ]


class MorningBodyBatteryServiceTests(unittest.TestCase):
    def test_current_reads_persisted_or_explicit_snapshot(self) -> None:
        persisted = {"sleep_date": "2026-09-04", "status": "ready"}
        harness = Harness(snapshot={"morning_body_battery": persisted})
        service = harness.make_service()

        self.assertEqual(service.current(), persisted)
        self.assertEqual(
            service.current({"morning_body_battery": {"status": "explicit"}}),
            {"status": "explicit"},
        )
        self.assertIsNone(service.current({"morning_body_battery": "invalid"}))

    def test_sync_is_bounded_by_maintenance_and_provider_gates(self) -> None:
        harness = Harness()
        service = harness.make_service()

        service.sync(CHECKIN_DATE)

        self.assertEqual(
            [entry for entry in harness.trace if entry.endswith(("enter", "exit"))],
            [
                "maintenance:enter",
                "provider:enter",
                "provider:exit",
                "maintenance:exit",
            ],
        )

    def test_cache_decisions_short_circuit_without_lock_or_remote(self) -> None:
        cases = (
            ({"status": "ready"}, "already_loaded"),
            (
                {
                    "status": "not_available_today",
                    "attempted_at": (NOW - timedelta(minutes=5)).isoformat(),
                },
                "retry_wait",
            ),
            (
                {"status": "not_available_today", "attempts": 3},
                "attempts_exhausted",
            ),
        )
        for fields, expected_status in cases:
            with self.subTest(status=expected_status):
                record = {"sleep_date": CHECKIN_DATE.isoformat(), **fields}
                harness = Harness(snapshot={"morning_body_battery": record})
                service = harness.make_service()

                result = service.sync(CHECKIN_DATE)

                self.assertEqual(result["status"], expected_status)
                self.assertEqual(harness.lock.acquire_calls, 0)
                self.assertEqual(harness.remote_calls, [])

    def test_fixture_uses_two_days_latest_sleep_record_and_commits_before_cleanup_event(
        self,
    ) -> None:
        previous = {
            "sleep_date": "2026-09-03",
            "status": "ready",
            "morning": {"value": 42},
        }
        old_records = [{"id": "saved"}]
        harness = Harness(
            snapshot={
                "morning_body_battery": previous,
                "body_battery": old_records,
            },
            history={"2026-09-02": 21},
            errors=[
                {"source": "body_battery", "message": "optional read failed"},
                {"source": "sleep", "message": "keep this error"},
            ],
        )
        harness.fixture_is_available = True
        harness.is_remote_configured = True
        harness.fixture_payload = {
            "sleep": [
                {
                    "calendarDate": "2026-09-03",
                    "sleepStartTimestampGMT": "2026-09-02T21:30:00Z",
                    "sleepEndTimestampGMT": "2026-09-03T05:45:00Z",
                },
                {
                    "calendarDate": "2026-09-04",
                    "sleepStartTimestampGMT": "2026-09-03T21:30:00Z",
                    "sleepEndTimestampGMT": "2026-09-04T05:45:00Z",
                },
            ],
            "body_battery": body_battery_records(),
        }
        service = harness.make_service()

        result = service.sync(CHECKIN_DATE)

        snapshot = json.loads(harness.values["garmin_snapshot"])
        history = json.loads(harness.values[MORNING_BATTERY_HISTORY_KEY])
        errors = json.loads(harness.values["last_garmin_error"])
        saved_record = snapshot["morning_body_battery"]
        self.assertEqual(
            result, {"status": "ready", "sleep_date": "2026-09-04", "records": 1}
        )
        self.assertEqual(harness.fixture_calls, [2])
        self.assertEqual(harness.remote_calls, [])
        self.assertEqual(saved_record["attempts"], 1)
        self.assertEqual(saved_record["morning"]["value"], 75)
        self.assertEqual(snapshot["body_battery"], body_battery_records() + old_records)
        self.assertEqual(
            history, {"2026-09-02": 21, "2026-09-03": 42, "2026-09-04": 75}
        )
        self.assertEqual(errors, [{"source": "sleep", "message": "keep this error"}])
        self.assertEqual(harness.events[0][1]["status"], "ready")
        commit_index = harness.trace.index("transaction:commit")
        cleanup_index = harness.trace.index("write:last_garmin_error")
        event_index = harness.trace.index("event:publish")
        self.assertLess(commit_index, cleanup_index)
        self.assertLess(cleanup_index, event_index)
        self.assertEqual(harness.lock.release_calls, 1)

    def test_commit_failure_rolls_back_without_error_cleanup_or_event(self) -> None:
        harness = Harness(errors=[{"source": "body_battery"}])
        harness.fixture_is_available = True
        harness.fixture_payload = {"sleep": [], "body_battery": []}
        before = copy.deepcopy(harness.values)
        harness.fail_commit_number = 3
        service = harness.make_service()

        with self.assertRaisesRegex(RuntimeError, "fake commit failure"):
            service.sync(CHECKIN_DATE)

        self.assertEqual(harness.values, before)
        self.assertFalse(harness.events)
        self.assertNotIn("write:last_garmin_error", harness.trace)
        self.assertEqual(harness.lock.release_calls, 1)
        self.assertIn("transaction:rollback", harness.trace)

    def test_remote_success_uses_injected_transport_and_persists_ready_values(
        self,
    ) -> None:
        harness = Harness()
        harness.is_remote_configured = True
        harness.remote_payload = (sleep_payload(), body_battery_records())
        service = harness.make_service()

        result = service.sync(CHECKIN_DATE)

        snapshot = json.loads(harness.values["garmin_snapshot"])
        history = json.loads(harness.values[MORNING_BATTERY_HISTORY_KEY])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(harness.remote_calls, [CHECKIN_DATE])
        self.assertEqual(harness.fixture_calls, [])
        self.assertEqual(snapshot["morning_body_battery"]["morning"]["value"], 75)
        self.assertEqual(snapshot["body_battery"], body_battery_records())
        self.assertEqual(history, {CHECKIN_DATE.isoformat(): 75})
        self.assertEqual(harness.events[0][1]["status"], "ready")

    def test_remote_exception_is_projected_persisted_and_keeps_attempt_count(
        self,
    ) -> None:
        existing = {
            "sleep_date": CHECKIN_DATE.isoformat(),
            "status": "not_available_today",
            "attempted_at": (NOW - timedelta(minutes=20)).isoformat(),
            "attempts": 2,
        }
        harness = Harness(
            snapshot={
                "morning_body_battery": existing,
                "body_battery": [{"id": "saved"}],
            },
            errors=[{"source": "body_battery"}, {"source": "sleep"}],
        )
        harness.is_remote_configured = True
        harness.remote_payload = ValueError("fake transport failure")
        service = harness.make_service()

        result = service.sync(CHECKIN_DATE)

        saved_snapshot = json.loads(harness.values["garmin_snapshot"])
        saved_record = saved_snapshot["morning_body_battery"]
        self.assertEqual(result["status"], "not_available_today")
        self.assertEqual(saved_record["attempts"], 3)
        self.assertEqual(saved_record["error"], "sanitized fake error")
        self.assertEqual(saved_snapshot["body_battery"], [{"id": "saved"}])
        self.assertEqual(harness.remote_calls, [CHECKIN_DATE])
        self.assertEqual(harness.safe_errors, [harness.remote_payload])
        self.assertEqual(
            json.loads(harness.values["last_garmin_error"]), [{"source": "sleep"}]
        )
        self.assertEqual(harness.events[0][1]["status"], "degraded")
        self.assertEqual(harness.lock.release_calls, 1)
        self.assertEqual(service.sync(CHECKIN_DATE)["status"], "attempts_exhausted")
        self.assertEqual(harness.lock.acquire_calls, 1)

    def test_non_list_body_battery_is_never_merged(self) -> None:
        harness = Harness(snapshot={"body_battery": [{"id": "saved"}]})
        harness.is_remote_configured = True
        harness.remote_payload = (sleep_payload(), {"unexpected": "object"})
        service = harness.make_service()

        result = service.sync(CHECKIN_DATE)

        saved_snapshot = json.loads(harness.values["garmin_snapshot"])
        self.assertEqual(result["records"], 0)
        self.assertEqual(saved_snapshot["body_battery"], [{"id": "saved"}])

    def test_not_configured_and_lock_contention_keep_status_and_lock_semantics(
        self,
    ) -> None:
        unconfigured = Harness()
        result = unconfigured.make_service().sync(CHECKIN_DATE)
        self.assertEqual(
            result, {"status": "not_configured", "sleep_date": "2026-09-04"}
        )
        self.assertEqual(unconfigured.lock.acquire_calls, 1)
        self.assertEqual(unconfigured.lock.release_calls, 1)
        self.assertFalse(unconfigured.events)

        contended = Harness()
        contended.lock.acquire_result = False
        contended.is_remote_configured = True
        result = contended.make_service().sync(CHECKIN_DATE)
        self.assertEqual(
            result, {"status": "already_running", "sleep_date": "2026-09-04"}
        )
        self.assertEqual(contended.lock.acquire_calls, 1)
        self.assertEqual(contended.lock.release_calls, 0)
        self.assertEqual(contended.remote_calls, [])

    def test_refresh_before_five_is_noop_and_logs_failure_after_five(self) -> None:
        early = Harness()
        early.fixture_is_available = True
        early_service = early.make_service(
            local_now=lambda: datetime(2026, 9, 4, 4, 59, tzinfo=timezone.utc)
        )
        early_service.refresh()
        self.assertEqual(early.lock.acquire_calls, 0)
        self.assertEqual(early.fixture_calls, [])

        later = Harness()
        later.fixture_is_available = True

        def broken_fixture(_days: int) -> object:
            raise RuntimeError("fake fixture failure")

        fixture_loader = Mock(path=lambda: object(), load=broken_fixture)
        later_service = later.make_service(fixture_loader=fixture_loader)
        later_service.refresh(CHECKIN_DATE)
        self.assertEqual(later.lock.release_calls, 1)
        self.assertEqual(len(later.logger.warnings), 1)
        self.assertEqual(
            later.logger.warnings[0][1],
            {
                "event": "morning_body_battery_sync_failed",
                "context": "sanitized fake error",
            },
        )
        self.assertEqual(later.logger.warnings[0][2][0], RuntimeError)  # type: ignore[index]
        self.assertEqual(later.safe_errors[0].args, ("fake fixture failure",))


if __name__ == "__main__":
    unittest.main()
