"""Wahoo sync owner: one transaction, rollback, skips, windows and idempotence."""

from __future__ import annotations

import threading
import unittest
from typing import Any
from unittest.mock import Mock, patch

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.errors import AppError
from backend.providers.descriptors import WAHOO_ID
from backend.providers.wahoo_client import WahooWorkoutFetch
from backend.sync.canonical_coverage_store import coverage_key
from backend.sync.gates import ProviderResyncGate
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.schedule_policies import WahooSchedulePolicy
from backend.sync.wahoo_sync import (
    LAST_ERROR_KEY,
    LAST_SYNC_KEY,
    SYNC_FAILED_MESSAGE,
    WahooSyncClock,
    WahooSyncService,
    WahooSyncStorage,
)
from tests.wahoo_sync_fixture import (
    EARLIER_UTC,
    LATE_EVENING_UTC,
    ZONE,
    FakeConnection,
    WahooSyncCase,
    workout,
)

ALL_SCOPES = "workouts_read power_zones_read user_read"
CYCLING_ZONE_SET = {
    "id": 1,
    "workout_type_family_id": 0,  # biking family
    "ftp": 250,
    "updated_at": "2026-10-01T10:00:00Z",
}


def upstream_status(status: int) -> AppError:
    return AppError(
        502, "Upstream failed", reason="upstream_rejected", upstream_status=status
    )


class ThresholdSyncTests(WahooSyncCase):
    """Power zones and profile are read only when their scopes were granted."""

    def grant(self, scope: str = ALL_SCOPES) -> None:
        self.connection = FakeConnection(scope=scope)
        self.source.fetch = WahooWorkoutFetch((workout(1, LATE_EVENING_UTC),))
        self.source.power_zone_rows = (dict(CYCLING_ZONE_SET),)
        self.source.profile = {"weight": 78.5}

    def stored_kinds(self) -> list[str]:
        # The workout's own record is kind "activity"; only threshold kinds count here.
        rows = self.rows(
            "SELECT record_kind FROM provider_records WHERE provider = 'wahoo' "
            "AND record_kind <> 'activity' ORDER BY record_kind"
        )
        return [row["record_kind"] for row in rows]

    def test_granted_scopes_read_and_store_the_threshold_rows(self) -> None:
        self.grant()

        result = self.service.sync()

        self.assertEqual("ok", result["status"])
        self.assertNotIn("skipped_sources", result)
        self.assertEqual(["power_zones", "user"], self.source.threshold_reads)
        self.assertEqual(["power_zones", "user"], self.stored_kinds())
        metrics = self.rows(
            "SELECT metric, value FROM observations WHERE provider = 'wahoo' "
            "ORDER BY metric"
        )
        self.assertEqual(
            [
                (MetricKind.FTP.value, 250.0),
                (MetricKind.WEIGHT.value, 78.5),
            ],
            [(row["metric"], row["value"]) for row in metrics],
        )
        self.assertEqual(1, len(self._activity_rows()))

    def test_ungranted_scopes_are_skipped_and_the_workouts_are_still_stored(
        self,
    ) -> None:
        self.grant(scope="workouts_read")

        result = self.service.sync()

        self.assertEqual("ok", result["status"])
        self.assertEqual([], self.source.threshold_reads)
        self.assertEqual(
            {"power_zones": "scope", "user": "scope"}, result["skipped_sources"]
        )
        self.assertEqual([], self.stored_kinds())
        self.assertEqual(1, len(self._activity_rows()))

    def test_a_forbidden_power_zones_read_is_non_fatal_and_keeps_the_workouts(
        self,
    ) -> None:
        self.grant()
        self.source.power_zones_error = upstream_status(403)

        result = self.service.sync()

        self.assertEqual("ok", result["status"])
        self.assertEqual({"power_zones": "rejected"}, result["skipped_sources"])
        self.assertEqual(["user"], self.stored_kinds())
        self.assertEqual(1, len(self._activity_rows()))
        self.assertFalse(self._value(LAST_ERROR_KEY))
        self.assertEqual(["success"], self._refresh_statuses())

    def test_a_missing_user_read_is_non_fatal_and_keeps_the_zone_sets(self) -> None:
        self.grant()
        self.source.user_error = upstream_status(404)

        result = self.service.sync()

        self.assertEqual({"user": "rejected"}, result["skipped_sources"])
        self.assertEqual(["power_zones"], self.stored_kinds())
        self.assertEqual(1, len(self._activity_rows()))

    def test_other_threshold_failures_stop_the_run_before_anything_is_written(
        self,
    ) -> None:
        self.grant()
        self.source.power_zones_error = upstream_status(500)

        with self.assertRaises(AppError):
            self.service.sync()

        self.assertEqual([], self._activity_rows())
        self.assertEqual([], self.stored_kinds())
        self.assertIsNone(self._marker())


class IngestTests(WahooSyncCase):
    def test_ingests_activities_with_local_dates_and_marks_success(self) -> None:
        self.source.fetch = WahooWorkoutFetch(
            (workout(1, LATE_EVENING_UTC), workout(2, EARLIER_UTC))
        )

        result = self.service.sync(reason="manual")

        self.assertEqual("ok", result["status"])
        rows = self._activity_rows()
        self.assertEqual(["wahoo", "wahoo"], [row["provider"] for row in rows])
        self.assertEqual(
            ["2026-10-12", "2026-10-10"], [row["local_date"] for row in rows]
        )
        self.assertEqual(self.now.isoformat(), self._value(LAST_SYNC_KEY))
        self.assertFalse(self._value(LAST_ERROR_KEY))
        self.assertIsNotNone(self._marker())
        self.assertIsNotNone(self._value(coverage_key(ProviderId.WAHOO)))
        self.assertEqual(["success"], self._refresh_statuses())

    def test_resync_is_idempotent(self) -> None:
        self.source.fetch = WahooWorkoutFetch((workout(1, EARLIER_UTC),))
        self.service.sync()
        first = self._canonical_row_count()

        self.advance(hours=1)
        self.service.sync()

        self.assertEqual(first, self._canonical_row_count())
        self.assertEqual(1, len(self._activity_rows()))

    def test_truncated_fetch_reports_partial(self) -> None:
        self.source.fetch = WahooWorkoutFetch(
            (workout(1, EARLIER_UTC),), truncated=True
        )

        self.assertEqual("partial", self.service.sync()["status"])

    def test_window_is_clamped_and_defaulted(self) -> None:
        self.assertEqual(84, self.service.sync()["window_days"])
        self.assertEqual(84, self.service.sync(days=True)["window_days"])
        self.assertEqual(7, self.service.sync(days=7)["window_days"])
        self.assertLessEqual(self.service.sync(days=10**6)["window_days"], 3650)

    def test_the_fetch_ends_at_the_synchronization_time(self) -> None:
        self.service.sync()

        self.assertEqual([self.now], self.source.upper_bounds)


class FailureTests(WahooSyncCase):
    def assertNothingPersisted(self) -> None:
        self.assertEqual(0, self._canonical_row_count())
        self.assertIsNone(self._value(LAST_SYNC_KEY))
        self.assertIsNone(self._marker())

    def test_marker_failure_rolls_the_whole_ingest_back(self) -> None:
        self.source.fetch = WahooWorkoutFetch((workout(1, EARLIER_UTC),))

        with (
            patch.object(
                self.markers, "mark_in_transaction", side_effect=RuntimeError("boom")
            ),
            self.assertRaises(AppError) as raised,
        ):
            self.service.sync()

        self.assertEqual(502, raised.exception.status)
        self.assertEqual("wahoo_sync_failed", raised.exception.reason)
        self.assertNothingPersisted()
        self.assertEqual(SYNC_FAILED_MESSAGE, self._value(LAST_ERROR_KEY))
        self.assertEqual(["error"], self._refresh_statuses())

    def test_coverage_failure_rolls_the_whole_ingest_back(self) -> None:
        self.source.fetch = WahooWorkoutFetch((workout(1, EARLIER_UTC),))

        with (
            patch(
                "backend.sync.wahoo_sync.CanonicalCoverageStore.persist",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(AppError),
        ):
            self.service.sync()

        self.assertNothingPersisted()
        self.assertIsNone(self._value(coverage_key(ProviderId.WAHOO)))

    def test_fetch_error_is_stored_and_reraised(self) -> None:
        self.source.error = AppError(
            409, "Reconnect Wahoo.", reason="wahoo_reconnect_required"
        )

        with self.assertRaises(AppError) as raised:
            self.service.sync()

        self.assertEqual("wahoo_reconnect_required", raised.exception.reason)
        self.assertEqual("Reconnect Wahoo.", self._value(LAST_ERROR_KEY))
        self.assertNothingPersisted()

    def test_success_clears_a_previous_error(self) -> None:
        self.source.error = RuntimeError("boom")
        with self.assertRaises(AppError):
            self.service.sync()
        self.assertEqual(SYNC_FAILED_MESSAGE, self._value(LAST_ERROR_KEY))

        self.source.error = None
        self.service.sync()

        self.assertFalse(self._value(LAST_ERROR_KEY))


class SkipTests(WahooSyncCase):
    def test_unconfigured_skips_without_touching_the_source(self) -> None:
        from backend.providers.descriptors import WAHOO_NOT_CONFIGURED_MESSAGE
        from tests.wahoo_sync_fixture import make_config

        self.config = make_config(wahoo=False)

        result = self.service.sync()

        self.assertEqual("not_configured", result["status"])
        self.assertEqual(WAHOO_NOT_CONFIGURED_MESSAGE, result["message"])
        self.assertEqual([], self.source.windows)
        self.assertEqual(0, self._canonical_row_count())

    def test_disconnected_skips_without_touching_the_source(self) -> None:
        from backend.providers.descriptors import WAHOO_NOT_CONFIGURED_MESSAGE

        self.connection.connected = False

        result = self.service.sync()

        self.assertEqual("not_configured", result["status"])
        self.assertEqual(WAHOO_NOT_CONFIGURED_MESSAGE, result["message"])
        self.assertEqual([], self.source.windows)

    def test_a_concurrent_run_reports_already_running(self) -> None:
        self.assertIsInstance(self.service, WahooSyncService)
        with self.lock:
            result = self.service.sync()

        self.assertEqual({"status": "already_running"}, result)
        self.assertEqual([], self.source.windows)


class WindowAndResetGateTests(WahooSyncCase):
    def _gated_service(self, gate: ProviderResyncGate) -> WahooSyncService:
        return WahooSyncService(
            config=lambda: self.config,
            connection=lambda: self.connection,
            source=lambda: self.source,
            storage=WahooSyncStorage(
                database_manager=lambda: self.database,
                database_lock=threading.RLock(),
                key_values=self.key_values,
            ),
            daily_markers=lambda: self.markers,
            observer=lambda: self.observer,
            registry=DEFAULT_PROVIDER_REGISTRY,
            clock=WahooSyncClock(lambda: self.now, lambda: ZONE),
            logger=self.logger,
            lock=self.lock,
            gate=gate,
        )

    def test_all_sentinel_and_zero_mean_the_descriptor_maximum(self) -> None:
        maximum = DEFAULT_PROVIDER_REGISTRY.max_sync_days(WAHOO_ID)

        self.assertEqual(maximum, self.service.sync(days=-1)["window_days"])
        self.assertEqual(maximum, self.service.sync(days=0)["window_days"])

    def test_reset_in_progress_blocks_a_concurrent_sync_before_the_source(
        self,
    ) -> None:
        gate = ProviderResyncGate("Wahoo")
        service = self._gated_service(gate)
        self.assertTrue(gate.begin_reset())
        rejections: list[AppError] = []

        def run_sync() -> None:
            try:
                service.sync(reason="manual")
            except AppError as error:
                rejections.append(error)

        try:
            worker = threading.Thread(target=run_sync)
            worker.start()
            worker.join(timeout=5)
        finally:
            gate.end_reset()

        self.assertEqual(1, len(rejections))
        self.assertEqual(409, rejections[0].status)
        self.assertEqual([], self.source.windows)

    def test_schedule_policy_is_blocked_only_while_resetting(self) -> None:
        gate = ProviderResyncGate("Wahoo")
        policy = WahooSchedulePolicy(
            configured=lambda: True,
            sync_state=Mock(),
            sync_period_defaults={WAHOO_ID: 84},
            all_sync_days=-1,
            resync_gate=gate,
        )

        self.assertFalse(policy.blocked())
        self.assertTrue(gate.begin_reset())
        self.assertTrue(policy.blocked())
        gate.end_reset()
        self.assertFalse(policy.blocked())


class DetailHookTests(WahooSyncCase):
    """The optional detail hook runs after the commit and never changes its outcome."""

    def hook_service(self, details: Any) -> WahooSyncService:
        return WahooSyncService(
            config=lambda: self.config,
            connection=lambda: self.connection,
            source=lambda: self.source,
            storage=WahooSyncStorage(
                database_manager=lambda: self.database,
                database_lock=threading.RLock(),
                key_values=self.key_values,
            ),
            daily_markers=lambda: self.markers,
            observer=lambda: self.observer,
            registry=DEFAULT_PROVIDER_REGISTRY,
            clock=WahooSyncClock(lambda: self.now, lambda: ZONE),
            logger=self.logger,
            lock=self.lock,
            details=details,
        )

    def test_details_result_is_attached_to_the_sync_result(self) -> None:
        detail = Mock()
        detail.import_details.return_value = {"status": "ok", "stored": 1}
        self.source.fetch = WahooWorkoutFetch((workout(1, LATE_EVENING_UTC),))

        result = self.hook_service(lambda: detail).sync()

        self.assertEqual("ok", result["status"])
        self.assertEqual({"status": "ok", "stored": 1}, result["details"])
        detail.import_details.assert_called_once()
        self.assertEqual(
            self.now, detail.import_details.call_args.kwargs["retrieved_at"]
        )

    def test_a_failing_detail_import_keeps_the_sync_ok(self) -> None:
        detail = Mock()
        detail.import_details.side_effect = RuntimeError("detail-failure-probe")
        self.source.fetch = WahooWorkoutFetch((workout(1, LATE_EVENING_UTC),))

        result = self.hook_service(lambda: detail).sync()

        self.assertEqual("ok", result["status"])
        self.assertEqual({"status": "failed"}, result["details"])
        self.assertEqual("", self._value(LAST_ERROR_KEY))
        self.assertIsNotNone(self._value(LAST_SYNC_KEY))
        warning = self.logger.warning.call_args
        self.assertEqual(
            "wahoo_activity_detail_failed", warning.kwargs["extra"]["event"]
        )
        self.assertNotIn("detail-failure-probe", repr(self.logger.mock_calls))


if __name__ == "__main__":
    unittest.main()
