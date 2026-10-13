"""Wahoo plan export is reachable only through the explicit, validated job."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import Mock

import backend.errors
from backend.errors import AppError
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.providers.descriptors import WAHOO_NOT_CONFIGURED_MESSAGE, Capability
from backend.sync.executor import WahooJobAdapter
from backend.sync.jobs import JobValidationError, normalize_sync_job_request
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY

WORKOUT_ID = "11111111-1111-4111-8111-111111111111"
ENTRY = {"library_workout_id": WORKOUT_ID, "expected_payload_hash": "a" * 64}
# The container image installs backend/ apart from the tests, so resolve it by import.
BACKEND = Path(backend.errors.__file__).resolve().parent


def normalize(provider, payload=None):
    return normalize_sync_job_request(provider, "plan_push", payload, all_sync_days=90)


class JobValidationTests(unittest.TestCase):
    def test_wahoo_plan_push_normalizes_like_the_intervals_job(self) -> None:
        result = normalize("wahoo", {"entries": [ENTRY]})

        self.assertEqual("wahoo", result["provider"])
        self.assertEqual("plan_push", result["type"])
        self.assertEqual([ENTRY], result["payload"]["entries"])

    def test_the_registry_names_the_export_targets(self) -> None:
        self.assertEqual(
            ("intervals", "wahoo"),
            DEFAULT_PROVIDER_REGISTRY.ids_with(Capability.WORKOUT_EXPORT),
        )

    def test_other_providers_and_unknown_targets_are_rejected(self) -> None:
        for provider in ("garmin", "weather", "calendar", "unknown", ""):
            with (
                self.subTest(provider=provider),
                self.assertRaises(JobValidationError),
            ):
                normalize(provider, {"entries": [ENTRY]})

    def test_wahoo_plan_push_still_requires_hashed_entries(self) -> None:
        with self.assertRaises(JobValidationError):
            normalize("wahoo", {"entries": []})
        with self.assertRaises(JobValidationError):
            normalize("wahoo", {"entries": [{"library_workout_id": WORKOUT_ID}]})


class HttpTargetTests(unittest.TestCase):
    def endpoint(self, *, connected: bool):
        self.queue = Mock()
        self.queue.enqueue.return_value = {"id": "job-1"}
        full_resync = Mock()
        full_resync.provider_configured.side_effect = lambda provider: (
            connected if provider == "wahoo" else True
        )
        return SyncCommandEndpoint(
            self.queue,
            Mock(),
            Mock(),
            full_resync,
            lambda: "operation-1",
            {"intervals": 90},
            -1,
        )

    def body(self, provider):
        return {
            "provider": provider,
            "type": "plan_push",
            "payload": {"entries": [ENTRY]},
        }

    def test_unconnected_wahoo_is_rejected_before_any_job_is_stored(self) -> None:
        with self.assertRaises(AppError) as caught:
            self.endpoint(connected=False).execute("/api/sync/jobs", self.body("wahoo"))

        self.assertEqual(409, caught.exception.status)
        self.assertEqual("not_configured", caught.exception.reason)
        self.assertEqual(WAHOO_NOT_CONFIGURED_MESSAGE, caught.exception.message)
        self.queue.enqueue.assert_not_called()

    def test_connected_wahoo_enqueues_the_explicit_user_job(self) -> None:
        status, _ = self.endpoint(connected=True).execute(
            "/api/sync/jobs", self.body("wahoo")
        )

        self.assertEqual(202, status)
        self.queue.enqueue.assert_called_once_with(
            "wahoo", "plan_push", {"entries": [ENTRY]}, requested_by="user"
        )


class AdapterTests(unittest.TestCase):
    def test_plan_push_runs_the_plan_service_not_the_read_sync(self) -> None:
        sync, plan_push = Mock(), Mock()
        plan_push.sync.return_value = {"ok": True}

        result = WahooJobAdapter(sync=sync, plan_push=plan_push).execute(
            {"id": "job-1"},
            {"entries": [ENTRY], "reason": "job"},
            "manual",
            job_type="plan_push",
        )

        self.assertEqual({"ok": True}, result)
        plan_push.sync.assert_called_once_with({"entries": [ENTRY]})
        sync.sync.assert_not_called()

    def test_plan_push_without_an_owner_is_refused(self) -> None:
        sync = Mock()

        with self.assertRaises(AppError):
            WahooJobAdapter(sync=sync).execute(
                {"id": "job-1"}, {"entries": [ENTRY]}, "manual", job_type="plan_push"
            )

        sync.sync.assert_not_called()

    def test_refresh_stays_the_read_only_sync(self) -> None:
        sync, plan_push = Mock(), Mock()
        sync.sync.return_value = {"ok": True}

        WahooJobAdapter(sync=sync, plan_push=plan_push).execute(
            {"id": "job-1"}, {"days": 7}, "manual", job_type="refresh"
        )

        sync.sync.assert_called_once_with(7, "manual", operation_id="job-1")
        plan_push.sync.assert_not_called()


class NoImplicitExportTests(unittest.TestCase):
    def test_coach_and_replanning_never_reference_the_wahoo_export(self) -> None:
        pattern = re.compile(
            r"wahoo_plan_push|WahooPlanPush|WahooWorkoutExport|wahoo_workout_export"
            r"|plan_push_service|ProviderId\.WAHOO",
            re.IGNORECASE,
        )
        offenders = [
            str(path.relative_to(BACKEND))
            for directory in ("coach", "planning")
            for path in (BACKEND / directory).rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual([], offenders)

    def test_the_authorized_plan_push_command_enqueues_intervals_only(self) -> None:
        source = (BACKEND / "sync" / "plan_commands.py").read_text(encoding="utf-8")

        self.assertIn('"intervals"', source)
        self.assertNotIn("wahoo", source.lower())


if __name__ == "__main__":
    unittest.main()
