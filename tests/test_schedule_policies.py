"""Unit tests for the concrete daily and startup schedule policies."""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import Mock

from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID
from backend.sync.schedule_policies import (
    CalendarSchedulePolicy,
    GarminSchedulePolicy,
    WeatherSchedulePolicy,
    build_schedule_policies,
)
from backend.sync.scheduler import (
    DailySyncScheduler,
    DailySyncSchedulerConfig,
    StartupSyncScheduler,
    StartupSyncSchedulerConfig,
)
from backend.sync.scheduler_wiring import build_sync_schedulers
from backend.sync.wiring import SyncWindow


class _FakePolicy:
    """Answers scheduling questions from fixed flags and records refreshes."""

    def __init__(self, *, configured: bool = True, blocked: bool = False) -> None:
        self._configured = configured
        self._blocked = blocked
        self.refresh_calls: list[tuple[str, str]] = []

    def configured(self) -> bool:
        return self._configured

    def blocked(self) -> bool:
        return self._blocked

    def refresh_payload(
        self, trigger: Literal["daily", "startup"], reason: str
    ) -> dict[str, Any]:
        self.refresh_calls.append((trigger, reason))
        return {"days": 14, "reason": reason, "trigger": trigger}


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

    def adopt_intervals_export_time(self) -> None:
        pass


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
    def test_blocked_follows_the_garmin_resync_gate_like_wahoo(self) -> None:
        gate = ProviderResyncGate("Garmin")
        policy = GarminSchedulePolicy(cast(Any, _Garmin()), 7, gate)

        self.assertFalse(policy.blocked())
        gate.begin_reset()
        self.assertTrue(policy.blocked())
        gate.end_reset()
        self.assertFalse(policy.blocked())

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


class BuildSchedulePoliciesTests(unittest.TestCase):
    def test_builds_one_policy_per_built_in_provider(self) -> None:
        policies = build_schedule_policies(
            profile=cast(Any, _Profile()),
            garmin=cast(Any, _Garmin()),
            calendar_enabled=True,
            garmin_automatic_sync_days=7,
        )
        self.assertEqual(set(policies), {WEATHER_ID, CALENDAR_ID, GARMIN_ID})
        self.assertTrue(policies[WEATHER_ID].configured())
        self.assertTrue(policies[CALENDAR_ID].configured())
        self.assertTrue(policies[GARMIN_ID].configured())

    def test_production_options_reach_their_policies(self) -> None:
        # Moved from the runtime bindings (#2070): weather waits on its cache,
        # Wahoo is included when given, Garmin carries its resync gate.
        due = [False]
        gate = ProviderResyncGate("Garmin")
        wahoo = cast(Any, _FakePolicy())
        policies = build_schedule_policies(
            profile=cast(Any, _Profile()),
            garmin=cast(Any, _Garmin()),
            calendar_enabled=True,
            garmin_automatic_sync_days=7,
            garmin_resync_gate=gate,
            weather_refresh_due=lambda: due[0],
            wahoo=wahoo,
        )

        self.assertEqual(set(policies), {WEATHER_ID, CALENDAR_ID, GARMIN_ID, WAHOO_ID})
        self.assertIs(wahoo, policies[WAHOO_ID])
        self.assertTrue(policies[WEATHER_ID].blocked())
        due[0] = True
        self.assertFalse(policies[WEATHER_ID].blocked())
        self.assertFalse(policies[GARMIN_ID].blocked())
        gate.begin_reset()
        self.addCleanup(gate.end_reset)
        self.assertTrue(policies[GARMIN_ID].blocked())


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


def _policies(wahoo: _FakePolicy) -> dict[str, Any]:
    built = build_schedule_policies(
        profile=cast(Any, _Profile()),
        garmin=cast(Any, _Garmin()),
        calendar_enabled=True,
        garmin_automatic_sync_days=7,
    )
    return {**built, WAHOO_ID: wahoo}


def _daily(
    policies: dict[str, Any], queue: _ScheduleQueue, markers: _ScheduleMarkers
) -> DailySyncScheduler:
    return DailySyncScheduler(
        cast(Any, queue),
        cast(Any, markers),
        cast(Any, _ScheduleGate()),
        config=DailySyncSchedulerConfig(
            auto_update_label="auto-label",
        ),
        schedule_policies=policies,
    )


def _startup(policies: dict[str, Any], queue: _ScheduleQueue) -> StartupSyncScheduler:
    return StartupSyncScheduler(
        cast(Any, queue),
        cast(Any, _SyncState()),
        config=StartupSyncSchedulerConfig(
            sync_chunk_days=30,
            sync_earliest_date=date(2020, 1, 1),
        ),
        schedule_policies=policies,
    )


class WahooScheduleTests(unittest.TestCase):
    """Wahoo, ranked last, is ordered and gated by its own policy alone."""

    def test_daily_run_schedules_wahoo_last_with_its_payload_and_marker(self) -> None:
        wahoo = _FakePolicy()
        queue = _ScheduleQueue()
        markers = _ScheduleMarkers()
        _daily(_policies(wahoo), queue, markers).schedule()

        providers = queue.refresh_providers()
        self.assertEqual(providers[-1], WAHOO_ID)
        self.assertEqual(providers.count(WAHOO_ID), 1)
        self.assertIn(WAHOO_ID, markers.checked)
        self.assertEqual(wahoo.refresh_calls, [("daily", "auto-label")])
        self.assertEqual(
            queue.refresh_payload(WAHOO_ID),
            {"days": 14, "reason": "auto-label", "trigger": "daily"},
        )
        self.assertEqual(queue.enqueued[-1]["requested_by"], "scheduler")

    def test_startup_run_schedules_wahoo_last_with_its_payload(self) -> None:
        wahoo = _FakePolicy()
        queue = _ScheduleQueue()
        _startup(_policies(wahoo), queue).schedule()

        self.assertEqual(queue.refresh_providers()[-1], WAHOO_ID)
        self.assertEqual(queue.enqueued[-1]["provider"], WAHOO_ID)
        self.assertEqual(wahoo.refresh_calls, [("startup", "startup")])
        self.assertEqual(
            queue.refresh_payload(WAHOO_ID),
            {"days": 14, "reason": "startup", "trigger": "startup"},
        )
        self.assertEqual(queue.enqueued[-1]["requested_by"], "startup")

    def test_daily_run_skips_blocked_wahoo(self) -> None:
        wahoo = _FakePolicy(blocked=True)
        queue = _ScheduleQueue()
        _daily(_policies(wahoo), queue, _ScheduleMarkers()).schedule()

        self.assertNotIn(WAHOO_ID, queue.refresh_providers())
        self.assertEqual(wahoo.refresh_calls, [])
        self.assertTrue(queue.refresh_providers())

    def test_unconfigured_wahoo_is_skipped_by_both_runs(self) -> None:
        daily_wahoo = _FakePolicy(configured=False)
        daily_queue = _ScheduleQueue()
        daily_markers = _ScheduleMarkers()
        _daily(_policies(daily_wahoo), daily_queue, daily_markers).schedule()
        self.assertNotIn(WAHOO_ID, daily_queue.refresh_providers())
        self.assertNotIn(WAHOO_ID, daily_markers.checked)
        self.assertEqual(daily_wahoo.refresh_calls, [])

        startup_wahoo = _FakePolicy(configured=False)
        startup_queue = _ScheduleQueue()
        _startup(_policies(startup_wahoo), startup_queue).schedule()
        self.assertFalse(
            [job for job in startup_queue.enqueued if job["provider"] == WAHOO_ID]
        )
        self.assertEqual(startup_wahoo.refresh_calls, [])

    def test_startup_never_enqueues_historical_backfill_for_wahoo(self) -> None:
        queue = _ScheduleQueue()
        _startup(_policies(_FakePolicy()), queue).schedule()

        jobs = {(str(job["provider"]), str(job["job_type"])) for job in queue.enqueued}
        self.assertIn((GARMIN_ID, "historical_backfill"), jobs)
        self.assertNotIn((WAHOO_ID, "historical_backfill"), jobs)


class SchedulerBuilderPolicyTests(unittest.TestCase):
    """The production builder hands its provider options to the policies."""

    def _schedulers(self, due: list[bool], gate: ProviderResyncGate) -> Any:
        config = Mock(calendar_ical_url="https://calendar.invalid/feed.ics")
        wahoo_sync = Mock()
        wahoo_sync.configured.return_value = True
        ctx = SimpleNamespace(
            config=lambda: config,
            athlete=SimpleNamespace(profile=lambda: _Profile()),
            garmin=SimpleNamespace(
                sync_service=lambda: _Garmin(),
                change_check=lambda: Mock(active=Mock(return_value=False)),
            ),
            wahoo=SimpleNamespace(sync_service=lambda: wahoo_sync),
            sync_job_queue=SimpleNamespace(service=Mock),
            sync_persistence=SimpleNamespace(daily_markers=Mock, state_repository=Mock),
            maintenance=MaintenanceGate(),
        )
        return build_sync_schedulers(
            cast(Any, ctx),
            window=SyncWindow({WAHOO_ID: 84}, -1, 30, date(2020, 1, 1)),
            weather_sync=lambda: Mock(refresh_due=lambda: due[0]),
            garmin_resync_gate=gate,
            wahoo_resync_gate=ProviderResyncGate("Wahoo"),
            retry_held=lambda _provider: False,
            sleep=lambda _s: None,
        )

    def test_daily_and_startup_policies_carry_the_provider_options(self) -> None:
        due = [False]
        gate = ProviderResyncGate("Garmin")
        schedulers = self._schedulers(due, gate)
        scheduled = {WEATHER_ID, CALENDAR_ID, GARMIN_ID, WAHOO_ID}

        startup = schedulers.startup_scheduler()._policies
        daily = schedulers.daily_scheduler()._policies

        self.assertEqual(scheduled, set(startup))
        self.assertEqual(scheduled, set(daily))
        self.assertTrue(daily[WAHOO_ID].configured())
        self.assertTrue(daily[WEATHER_ID].blocked())
        due[0] = True
        self.assertFalse(daily[WEATHER_ID].blocked())
        self.assertFalse(daily[GARMIN_ID].blocked())
        gate.begin_reset()
        self.addCleanup(gate.end_reset)
        self.assertTrue(daily[GARMIN_ID].blocked())


if __name__ == "__main__":
    unittest.main()
