"""Unit tests for the concrete daily and startup schedule policies."""

from __future__ import annotations

import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, cast

from provider_runtime_fakes import ACME_ID, FakeSchedulePolicy, acme_descriptor

from backend.providers.descriptors import (
    CALENDAR_ID,
    DEFAULT_PROVIDER_DESCRIPTORS,
    GARMIN_ID,
    INTERVALS_ID,
    WEATHER_ID,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_registry import ProviderRegistry
from backend.sync.schedule_policies import (
    CalendarSchedulePolicy,
    GarminSchedulePolicy,
    IntervalsSchedulePolicy,
    WeatherSchedulePolicy,
    build_schedule_policies,
    intervals_busy,
)
from backend.sync.scheduler import (
    DailySyncScheduler,
    DailySyncSchedulerConfig,
    StartupSyncScheduler,
    StartupSyncSchedulerConfig,
)


class _Profile:
    def __init__(self, location: str = "Synthetic city") -> None:
        self.location = location

    def get(self) -> dict[str, str]:
        return {"weather_location": self.location}


class _Garmin:
    def __init__(self, configured: bool = True, end_date: date | None = None) -> None:
        self.is_configured = configured
        self.end_date = end_date
        self.window_requests: list[int] = []

    def configured(self) -> bool:
        return self.is_configured

    def automatic_sync_window(self, minimum_days: int) -> tuple[int, date | None]:
        self.window_requests.append(minimum_days)
        return 9, self.end_date


class _SyncState:
    def __init__(self) -> None:
        self.period_reads: list[tuple[str, Any, int]] = []

    def sync_period(self, provider: str, defaults: Any, all_days: int) -> int:
        self.period_reads.append((provider, defaults, all_days))
        return 21

    def cursor(self, provider: str, kind: str) -> dict[str, Any]:
        return {}


class _Database:
    def __init__(self) -> None:
        self.opened = 0

    @contextmanager
    def unit_of_work(self) -> Iterator[object]:
        self.opened += 1
        yield object()


class _KeyValues:
    def __init__(self, sync_running: str | None = None) -> None:
        self.sync_running = sync_running

    def get(self, _db: object, key: str) -> str | None:
        return self.sync_running if key == "sync_running" else None


class _Gate:
    def __init__(self, resetting: bool) -> None:
        self.resetting = resetting
        self.checks = 0

    def is_resetting(self) -> bool:
        self.checks += 1
        return self.resetting


class WeatherSchedulePolicyTests(unittest.TestCase):
    def make_policy(self, location: str = "Synthetic city") -> WeatherSchedulePolicy:
        return WeatherSchedulePolicy(cast(Any, _Profile(location)))

    def test_configured_only_with_non_blank_location(self) -> None:
        self.assertTrue(self.make_policy().configured())
        self.assertFalse(self.make_policy("   ").configured())
        self.assertFalse(self.make_policy("").configured())

    def test_never_blocked_without_freshness_check(self) -> None:
        self.assertFalse(self.make_policy().blocked())

    def test_blocked_while_no_unforced_refresh_is_due(self) -> None:
        due = [False]
        policy = WeatherSchedulePolicy(
            cast(Any, _Profile("Synthetic city")), refresh_due=lambda: due[0]
        )
        self.assertTrue(policy.blocked())
        due[0] = True
        self.assertFalse(policy.blocked())

    def test_payload_forces_only_on_startup(self) -> None:
        policy = self.make_policy()
        self.assertEqual(
            policy.refresh_payload("daily", "automatic"),
            {"force": False, "reason": "automatic"},
        )
        self.assertEqual(
            policy.refresh_payload("startup", "startup"),
            {"force": True, "reason": "startup"},
        )


class CalendarSchedulePolicyTests(unittest.TestCase):
    def test_configured_follows_build_time_snapshot(self) -> None:
        self.assertTrue(CalendarSchedulePolicy(enabled=True).configured())
        self.assertFalse(CalendarSchedulePolicy(enabled=False).configured())

    def test_never_blocked_and_reason_only_payload(self) -> None:
        policy = CalendarSchedulePolicy(enabled=True)
        self.assertFalse(policy.blocked())
        self.assertEqual(policy.refresh_payload("daily", "auto"), {"reason": "auto"})
        self.assertEqual(
            policy.refresh_payload("startup", "startup"), {"reason": "startup"}
        )


class GarminSchedulePolicyTests(unittest.TestCase):
    def test_configured_reads_live_service_and_is_never_blocked(self) -> None:
        garmin = _Garmin(configured=False)
        policy = GarminSchedulePolicy(cast(Any, garmin), 7)
        self.assertFalse(policy.configured())
        garmin.is_configured = True
        self.assertTrue(policy.configured())
        self.assertFalse(policy.blocked())

    def test_payload_without_end_date(self) -> None:
        garmin = _Garmin()
        policy = GarminSchedulePolicy(cast(Any, garmin), 7)
        self.assertEqual(
            policy.refresh_payload("daily", "auto"), {"days": 9, "reason": "auto"}
        )
        self.assertEqual(garmin.window_requests, [7])

    def test_payload_with_end_date_in_iso_format(self) -> None:
        garmin = _Garmin(end_date=date(2025, 5, 29))
        policy = GarminSchedulePolicy(cast(Any, garmin), 7)
        self.assertEqual(
            policy.refresh_payload("startup", "startup"),
            {"days": 9, "reason": "startup", "end_date": "2025-05-29"},
        )


class IntervalsSchedulePolicyTests(unittest.TestCase):
    def make_policy(
        self, *, enabled: bool = True, blocked: bool = False
    ) -> tuple[IntervalsSchedulePolicy, _SyncState]:
        sync_state = _SyncState()
        policy = IntervalsSchedulePolicy(
            enabled=enabled,
            sync_state=cast(Any, sync_state),
            sync_period_defaults={INTERVALS_ID: 84},
            all_sync_days=-1,
            blocked_by=lambda: blocked,
        )
        return policy, sync_state

    def test_configured_follows_build_time_snapshot(self) -> None:
        self.assertTrue(self.make_policy(enabled=True)[0].configured())
        self.assertFalse(self.make_policy(enabled=False)[0].configured())

    def test_blocked_delegates_to_probe(self) -> None:
        self.assertFalse(self.make_policy(blocked=False)[0].blocked())
        self.assertTrue(self.make_policy(blocked=True)[0].blocked())

    def test_payload_uses_sync_period_for_both_triggers(self) -> None:
        policy, sync_state = self.make_policy()
        self.assertEqual(
            policy.refresh_payload("daily", "auto"),
            {"days": 21, "reason": "auto", "automatic": True},
        )
        self.assertEqual(
            policy.refresh_payload("startup", "startup"),
            {"days": 21, "reason": "startup", "automatic": True},
        )
        self.assertEqual(
            sync_state.period_reads,
            [
                (INTERVALS_ID, {INTERVALS_ID: 84}, -1),
                (INTERVALS_ID, {INTERVALS_ID: 84}, -1),
            ],
        )


class IntervalsBusyTests(unittest.TestCase):
    def test_running_sync_blocks_without_consulting_gate(self) -> None:
        gate = _Gate(resetting=False)
        database = _Database()
        busy = intervals_busy(
            cast(Any, database),
            cast(Any, _KeyValues("1")),
            threading.Lock(),
            cast(Any, gate),
        )
        self.assertTrue(busy)
        self.assertEqual(gate.checks, 0)
        self.assertEqual(database.opened, 1)

    def test_idle_sync_defers_to_resync_gate(self) -> None:
        for resetting in (False, True):
            with self.subTest(resetting=resetting):
                gate = _Gate(resetting=resetting)
                busy = intervals_busy(
                    cast(Any, _Database()),
                    cast(Any, _KeyValues("0")),
                    threading.Lock(),
                    cast(Any, gate),
                )
                self.assertEqual(busy, resetting)
                self.assertEqual(gate.checks, 1)

    def test_real_resync_gate_reports_reset_in_progress(self) -> None:
        gate = ProviderResyncGate("Intervals.icu")
        self.assertTrue(gate.begin_reset())
        self.addCleanup(gate.end_reset)
        busy = intervals_busy(
            cast(Any, _Database()),
            cast(Any, _KeyValues(None)),
            threading.Lock(),
            gate,
        )
        self.assertTrue(busy)


class BuildSchedulePoliciesTests(unittest.TestCase):
    def test_builds_one_policy_per_built_in_provider(self) -> None:
        policies = build_schedule_policies(
            profile=cast(Any, _Profile()),
            garmin=cast(Any, _Garmin()),
            sync_state=cast(Any, _SyncState()),
            calendar_enabled=True,
            intervals_enabled=False,
            garmin_automatic_sync_days=7,
            sync_period_defaults={},
            all_sync_days=-1,
            intervals_blocked=lambda: False,
        )
        self.assertEqual(
            set(policies), {WEATHER_ID, CALENDAR_ID, GARMIN_ID, INTERVALS_ID}
        )
        self.assertTrue(policies[WEATHER_ID].configured())
        self.assertTrue(policies[CALENDAR_ID].configured())
        self.assertTrue(policies[GARMIN_ID].configured())
        self.assertFalse(policies[INTERVALS_ID].configured())


class _ScheduleQueue:
    """Records enqueued jobs; no provider is active."""

    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def active(self, provider: str, job_type: str = "refresh") -> bool:
        return False

    def enqueue(
        self,
        provider: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        requested_by: str,
    ) -> None:
        self.enqueued.append(
            {
                "provider": provider,
                "job_type": job_type,
                "payload": dict(payload),
                "requested_by": requested_by,
            }
        )

    def refresh_providers(self) -> list[str]:
        return [
            str(job["provider"])
            for job in self.enqueued
            if job["job_type"] == "refresh"
        ]

    def refresh_payload(self, provider: str) -> dict[str, Any]:
        return next(
            job["payload"]
            for job in self.enqueued
            if job["provider"] == provider and job["job_type"] == "refresh"
        )


class _ScheduleMarkers:
    def __init__(self) -> None:
        self.checked: list[str] = []

    def is_due(self, provider: str) -> bool:
        self.checked.append(provider)
        return True


class _ScheduleGate:
    @contextmanager
    def operation(self) -> Iterator[None]:
        yield


def _policies(acme: FakeSchedulePolicy) -> dict[str, Any]:
    built = build_schedule_policies(
        profile=cast(Any, _Profile()),
        garmin=cast(Any, _Garmin()),
        sync_state=cast(Any, _SyncState()),
        calendar_enabled=True,
        intervals_enabled=True,
        garmin_automatic_sync_days=7,
        sync_period_defaults={},
        all_sync_days=-1,
        intervals_blocked=lambda: False,
    )
    return {**built, ACME_ID: acme}


def _registry() -> ProviderRegistry:
    return ProviderRegistry((*DEFAULT_PROVIDER_DESCRIPTORS, acme_descriptor()))


def _daily(
    policies: dict[str, Any], queue: _ScheduleQueue, markers: _ScheduleMarkers
) -> DailySyncScheduler:
    return DailySyncScheduler(
        cast(Any, _Profile()),
        cast(Any, queue),
        cast(Any, markers),
        cast(Any, _Garmin()),
        cast(Any, None),
        cast(Any, None),
        threading.Lock(),
        cast(Any, _SyncState()),
        ProviderResyncGate(INTERVALS_ID),
        cast(Any, _ScheduleGate()),
        config=DailySyncSchedulerConfig(
            calendar_url_enabled=True,
            intervals_key_enabled=True,
            garmin_automatic_sync_days=7,
            auto_update_label="auto-label",
            sync_period_defaults={},
            all_sync_days=-1,
        ),
        schedule_policies=policies,
        registry=_registry(),
    )


def _startup(policies: dict[str, Any], queue: _ScheduleQueue) -> StartupSyncScheduler:
    return StartupSyncScheduler(
        cast(Any, _Profile()),
        cast(Any, queue),
        cast(Any, _Garmin()),
        cast(Any, _SyncState()),
        config=StartupSyncSchedulerConfig(
            calendar_enabled=True,
            intervals_enabled=True,
            garmin_automatic_sync_days=7,
            sync_period_defaults={},
            all_sync_days=-1,
            sync_chunk_days=30,
            sync_earliest_date=date(2020, 1, 1),
        ),
        schedule_policies=policies,
        registry=_registry(),
    )


class AcmeMockScheduleTests(unittest.TestCase):
    """The test-only rank-99 provider is ordered and gated by its policy alone."""

    def test_daily_run_schedules_mock_last_with_its_payload_and_marker(self) -> None:
        acme = FakeSchedulePolicy()
        queue = _ScheduleQueue()
        markers = _ScheduleMarkers()
        _daily(_policies(acme), queue, markers).schedule()

        providers = queue.refresh_providers()
        self.assertEqual(providers[-1], ACME_ID)
        self.assertEqual(providers.count(ACME_ID), 1)
        self.assertIn(ACME_ID, markers.checked)
        self.assertEqual(acme.refresh_calls, [("daily", "auto-label")])
        self.assertEqual(
            queue.refresh_payload(ACME_ID),
            {"days": 14, "reason": "auto-label", "trigger": "daily"},
        )
        self.assertEqual(queue.enqueued[-1]["requested_by"], "scheduler")

    def test_startup_run_schedules_mock_last_with_its_payload(self) -> None:
        acme = FakeSchedulePolicy()
        queue = _ScheduleQueue()
        _startup(_policies(acme), queue).schedule()

        self.assertEqual(queue.refresh_providers()[-1], ACME_ID)
        self.assertEqual(queue.enqueued[-1]["provider"], ACME_ID)
        self.assertEqual(acme.refresh_calls, [("startup", "startup")])
        self.assertEqual(
            queue.refresh_payload(ACME_ID),
            {"days": 14, "reason": "startup", "trigger": "startup"},
        )
        self.assertEqual(queue.enqueued[-1]["requested_by"], "startup")

    def test_daily_run_skips_blocked_mock(self) -> None:
        acme = FakeSchedulePolicy(blocked=True)
        queue = _ScheduleQueue()
        _daily(_policies(acme), queue, _ScheduleMarkers()).schedule()

        self.assertNotIn(ACME_ID, queue.refresh_providers())
        self.assertEqual(acme.refresh_calls, [])
        self.assertTrue(queue.refresh_providers())

    def test_unconfigured_mock_is_skipped_by_both_runs(self) -> None:
        daily_acme = FakeSchedulePolicy(configured=False)
        daily_queue = _ScheduleQueue()
        daily_markers = _ScheduleMarkers()
        _daily(_policies(daily_acme), daily_queue, daily_markers).schedule()
        self.assertNotIn(ACME_ID, daily_queue.refresh_providers())
        self.assertNotIn(ACME_ID, daily_markers.checked)
        self.assertEqual(daily_acme.refresh_calls, [])

        startup_acme = FakeSchedulePolicy(configured=False)
        startup_queue = _ScheduleQueue()
        _startup(_policies(startup_acme), startup_queue).schedule()
        self.assertFalse(
            [job for job in startup_queue.enqueued if job["provider"] == ACME_ID]
        )
        self.assertEqual(startup_acme.refresh_calls, [])

    def test_startup_never_enqueues_historical_backfill_for_mock(self) -> None:
        queue = _ScheduleQueue()
        _startup(_policies(FakeSchedulePolicy()), queue).schedule()

        jobs = {(str(job["provider"]), str(job["job_type"])) for job in queue.enqueued}
        self.assertIn((GARMIN_ID, "historical_backfill"), jobs)
        self.assertNotIn((ACME_ID, "historical_backfill"), jobs)


if __name__ == "__main__":
    unittest.main()
