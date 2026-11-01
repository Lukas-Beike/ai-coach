"""Direct contract tests for authenticated sync and activity GET routes."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from unittest.mock import Mock

from activity_row_support import NoObservations, SnapshotActivityRows, StoredCoverage
from canonical_detail_support import add_session_record, open_manager

from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.http_api.activity_assembly import ActivityReadAssembly, ActivityReadSources
from backend.http_api.sync_get import SyncGetRoutes
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS


class FakeHandler:
    def __init__(self, path: str = "") -> None:
        self.path = path
        self.responses: list[tuple[int, object]] = []

    def send_json(self, status: int, payload: object) -> None:
        self.responses.append((status, payload))


class SyncGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = Mock()
        self.queue = Mock()
        self.sync_state = Mock()
        self.activities = Mock()
        self.auth_factory = Mock(return_value=self.auth)
        self.queue_factory = Mock(return_value=self.queue)
        self.sync_state_factory = Mock(return_value=self.sync_state)
        self.activity_factory = Mock(return_value=self.activities)
        self.today = Mock(return_value=date(2026, 9, 24))
        self.routes = SyncGetRoutes(
            self.auth_factory,
            self.queue_factory,
            self.sync_state_factory,
            self.activity_factory,
            self.today,
            -1,
        )
        self.handler = FakeHandler()

    def test_sync_job_payload_and_exact_path_pattern(self) -> None:
        self.queue.state.return_value = {"id": "a1-b2", "state": "running"}
        self.assertTrue(self.routes.handle(self.handler, "/api/sync/jobs/a1-b2"))
        self.assertEqual(self.handler.responses, [(200, self.queue.state.return_value)])
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.queue.state.assert_called_once_with("a1-b2")

        for path in (
            "/api/sync/jobs/",
            "/api/sync/jobs/G123",
            "/api/sync/jobs/g123",
            "/api/sync/jobs/123/extra",
        ):
            with self.subTest(path=path):
                handler = FakeHandler()
                factories = (
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                )
                route = SyncGetRoutes(*factories, lambda: date(2026, 9, 24), -1)
                self.assertFalse(route.handle(handler, path))
                for factory in factories:
                    factory.assert_not_called()
                self.assertEqual(handler.responses, [])

    def test_sync_status_payload_is_forwarded_unchanged(self) -> None:
        payload = {"status": "idle", "jobs": [{"id": "fake"}]}
        self.sync_state.state.return_value = payload
        self.assertTrue(self.routes.handle(self.handler, "/api/sync/status"))
        self.assertEqual(self.handler.responses, [(200, payload)])
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.sync_state.state.assert_called_once_with()

    def test_activity_query_uses_first_value_and_local_today_per_request(self) -> None:
        self.activities.page.return_value = {"activities": []}
        self.handler.path = (
            "/api/activities?cursor=first&cursor=second&limit=12&limit=24"
            "&days=7&days=30"
        )
        self.assertTrue(self.routes.handle(self.handler, "/api/activities"))
        self.activities.page.assert_called_once_with(
            "first", "12", "7", today=date(2026, 9, 24)
        )
        self.assertEqual(self.handler.responses, [(200, {"activities": []})])

        self.activities.page.reset_mock()
        self.today.return_value = date(2026, 9, 25)
        self.handler.path = "/api/activities"
        self.assertTrue(self.routes.handle(self.handler, "/api/activities"))
        self.activities.page.assert_called_once_with(
            None, None, -1, today=date(2026, 9, 25)
        )
        self.assertEqual(self.today.call_count, 2)

    def test_authentication_failure_precedes_data_factory_and_clock(self) -> None:
        denied = RuntimeError("denied")
        self.auth.require_auth.side_effect = denied
        with self.assertRaisesRegex(RuntimeError, "denied"):
            self.routes.handle(self.handler, "/api/activities")
        self.queue_factory.assert_not_called()
        self.sync_state_factory.assert_not_called()
        self.activity_factory.assert_not_called()
        self.today.assert_not_called()

    def test_auth_factory_is_resolved_for_each_keep_alive_request(self) -> None:
        second_auth = Mock()
        self.auth_factory.side_effect = [self.auth, second_auth]
        self.sync_state.state.return_value = {"status": "idle"}
        self.routes.handle(self.handler, "/api/sync/status")
        self.routes.handle(self.handler, "/api/sync/status")
        self.assertEqual(self.auth_factory.call_count, 2)
        self.auth.require_auth.assert_called_once_with(self.handler)
        second_auth.require_auth.assert_called_once_with(self.handler)

    def test_unknown_path_resolves_no_factories(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/sync/other"))
        self.auth_factory.assert_not_called()
        self.queue_factory.assert_not_called()
        self.sync_state_factory.assert_not_called()
        self.activity_factory.assert_not_called()

    def test_activity_detail_is_authenticated_local_only_and_preserves_case(
        self,
    ) -> None:
        self.activities.detail.return_value = {
            "activity_id": "CaseSensitive-1",
            "activity_validation": {},
        }
        self.assertTrue(
            self.routes.handle(self.handler, "/api/activities/CaseSensitive-1")
        )
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.activities.detail.assert_called_once_with(
            "CaseSensitive-1",
            garmin_status=NO_GARMIN_SYNC_STATUS,
            profile={},
            today=date(2026, 9, 24),
        )
        self.queue_factory.assert_not_called()
        self.assertEqual(
            [(200, {"activity_id": "CaseSensitive-1"})], self.handler.responses
        )

    def test_activity_page_uses_neutral_names_and_detail_is_passed_through(
        self,
    ) -> None:
        self.activities.page.return_value = {
            "activities": [
                {
                    "id": "a1",
                    "start_date_local": "2026-10-11T07:00:00",
                    "moving_time": 3600,
                    "icu_training_load": 40,
                    "icu_rpe": 4,
                }
            ]
        }
        self.handler.path = "/api/activities"
        self.assertTrue(self.routes.handle(self.handler, "/api/activities"))
        # The v1 document already names its metrics provider-neutrally.
        document = {
            "contract": "activity_detail.v1",
            "metrics": {"intensity": {"value": 0.75}},
            "laps": {"laps": [{"metrics": {"load": 12}}]},
        }
        self.activities.detail.return_value = dict(document)
        self.assertTrue(self.routes.handle(self.handler, "/api/activities/a1"))

        self.assertEqual(
            [
                (
                    200,
                    {
                        "activities": [
                            {
                                "id": "a1",
                                "started_at_local": "2026-10-11T07:00:00",
                                "moving_duration_s": 3600,
                                "training_load": 40,
                                "rpe": 4,
                            }
                        ]
                    },
                ),
                (200, document),
            ],
            self.handler.responses,
        )


class _Snapshots:
    def latest_snapshot(self, _db: object) -> dict:
        return {
            "synced_at": "2026-09-20T08:00:00+00:00",
            "athlete": {},
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "i1",
                        "type": "Ride",
                        "start_date_local": "2026-09-10T07:00:00",
                        "average_speed": 8.5,
                    }
                ]
            },
        }


class _Feedback:
    def list(self, _limit: int = 100) -> list:
        return []

    def for_activity_ids(self, _activity_ids: object) -> tuple[()]:
        return ()


class ActivityDetailRouteTests(unittest.TestCase):
    """Serve canonical detail documents through the production read assembly."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        add_session_record(self.manager, ProviderId.INTERVALS, "i1", "act_i")
        add_session_record(
            self.manager, ProviderId.GARMIN, "g1", "act_g", duration_s=3600.0
        )
        snapshots = _Snapshots()
        self.assembly = ActivityReadAssembly(
            lambda: self.manager,
            ActivityReadSources(
                lambda: SnapshotActivityRows(snapshots),
                observation_reader=NoObservations,
                coverage=lambda: StoredCoverage(None),
            ),
            _Feedback,
            lambda _activity_id: {"items": [], "assignments": []},
            refreshable_providers=lambda: ("intervals", "garmin"),
        )
        self.auth = Mock()
        self.reads = Mock(side_effect=self.assembly.activity_read)
        self.routes = SyncGetRoutes(
            Mock(return_value=self.auth),
            Mock(),
            Mock(),
            self.reads,
            lambda: date(2026, 9, 20),
            -1,
        )

    def get(self, activity_id: str) -> dict:
        handler = FakeHandler()
        self.assertTrue(self.routes.handle(handler, f"/api/activities/{activity_id}"))
        ((status, payload),) = handler.responses
        self.assertEqual(200, status)
        assert isinstance(payload, dict)
        return payload

    def test_authentication_precedes_every_detail_read(self) -> None:
        self.auth.require_auth.side_effect = AppError(401, "Anmeldung erforderlich.")
        handler = FakeHandler()
        with self.assertRaises(AppError) as denied:
            self.routes.handle(handler, "/api/activities/act_i")
        self.assertEqual(401, denied.exception.status)
        self.reads.assert_not_called()
        self.assertEqual([], handler.responses)

    def test_detail_body_is_the_v1_document_without_validation(self) -> None:
        for requested in ("act_i", "i1"):
            with self.subTest(requested):
                body = self.get(requested)
                self.assertEqual("activity_detail.v1", body["contract"])
                self.assertEqual("act_i", body["session"]["activity_id"])
                self.assertEqual(8.5, body["metrics"]["avg_speed_mps"]["value"])
                self.assertEqual(
                    {"activity_feedback", "equipment"},
                    {"activity_feedback", "equipment", "activity_validation"}
                    & set(body),
                )
                self.assertTrue(body["ok"])
                self.assertIn("providers: Intervals.icu", body["data_scope"])
                self.assertNotIn("activity", body)

    def test_garmin_only_session_is_served(self) -> None:
        body = self.get("act_g")
        self.assertEqual("act_g", body["session"]["activity_id"])
        self.assertEqual(3600.0, body["metrics"]["duration_s"]["value"])
        self.assertEqual(
            [("garmin", "Garmin Connect", True)],
            [
                (entry["provider"], entry["label"], entry["refreshable"])
                for entry in body["detail_data"]["providers"]
            ],
        )

    def test_unknown_session_is_not_found(self) -> None:
        for activity_id in ("act_missing", "missing"):
            with self.subTest(activity_id), self.assertRaises(AppError) as missing:
                self.routes.handle(FakeHandler(), f"/api/activities/{activity_id}")
            self.assertEqual(404, missing.exception.status)
            self.assertEqual("activity_details_not_found", missing.exception.reason)


if __name__ == "__main__":
    unittest.main()
