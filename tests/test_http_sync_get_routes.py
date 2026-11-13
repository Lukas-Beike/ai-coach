"""Direct contract tests for authenticated sync and activity GET routes."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from activity_row_support import ServedActivityReads
from canonical_detail_support import add_session_record, open_manager
from support import dispatch_route

from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.http_api.sync_get import SyncGetRoutes
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS
from backend.performance.wiring import build_activity_reads
from backend.sync.canonical_table_reader import CanonicalTableReader


class FakeHandler:
    def __init__(self, path: str = "") -> None:
        self.path = path
        self.responses: list[tuple[int, object]] = []

    def send_json(self, status: int, payload: object) -> None:
        self.responses.append((status, payload))


class SyncGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = Mock()
        self.sync_state = Mock()
        self.activities = Mock()
        self.queue_factory = Mock(return_value=self.queue)
        self.sync_state_factory = Mock(return_value=self.sync_state)
        self.activity_factory = Mock(return_value=self.activities)
        self.today = Mock(return_value=date(2026, 9, 24))
        self.routes = SyncGetRoutes(
            self.queue_factory,
            self.sync_state_factory,
            self.activity_factory,
            self.today,
            -1,
        )
        self.handler = FakeHandler()

    def test_sync_job_payload_and_exact_path_pattern(self) -> None:
        self.queue.state.return_value = {"id": "a1-b2", "state": "running"}
        self.assertTrue(
            dispatch_route(self.routes, self.handler, "/api/sync/jobs/a1-b2")
        )
        self.assertEqual(self.handler.responses, [(200, self.queue.state.return_value)])
        self.queue.state.assert_called_once_with("a1-b2")

        for path in (
            "/api/sync/jobs/",
            "/api/sync/jobs/G123",
            "/api/sync/jobs/g123",
            "/api/sync/jobs/123/extra",
        ):
            with self.subTest(path=path):
                handler = FakeHandler()
                factories = (Mock(), Mock(), Mock())
                route = SyncGetRoutes(*factories, lambda: date(2026, 9, 24), -1)
                self.assertFalse(dispatch_route(route, handler, path))
                for factory in factories:
                    factory.assert_not_called()
                self.assertEqual(handler.responses, [])

    def test_full_resync_progress_is_read_for_the_registered_provider_only(
        self,
    ) -> None:
        resync = Mock()
        resync.progress.return_value = {"running": True, "outcome": None}
        routes = SyncGetRoutes(
            self.queue_factory,
            self.sync_state_factory,
            self.activity_factory,
            self.today,
            -1,
            full_resync=lambda: resync,
            full_resync_providers={"/api/garmin/full-resync": "garmin"},
        )
        self.assertTrue(dispatch_route(routes, self.handler, "/api/garmin/full-resync"))
        self.assertEqual(
            self.handler.responses, [(200, {"running": True, "outcome": None})]
        )
        resync.progress.assert_called_once_with("garmin")

        self.assertFalse(
            dispatch_route(routes, FakeHandler(), "/api/wahoo/full-resync")
        )
        self.assertFalse(
            dispatch_route(self.routes, FakeHandler(), "/api/garmin/full-resync")
        )

    def test_sync_status_payload_is_forwarded_unchanged(self) -> None:
        payload = {"status": "idle", "jobs": [{"id": "fake"}]}
        self.sync_state.state.return_value = payload
        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/sync/status"))
        self.assertEqual(self.handler.responses, [(200, payload)])
        self.sync_state.state.assert_called_once_with()

    def test_activity_query_uses_first_value_and_local_today_per_request(self) -> None:
        self.activities.page.return_value = {"activities": []}
        self.handler.path = (
            "/api/activities?cursor=first&cursor=second&limit=12&limit=24"
            "&days=7&days=30"
        )
        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/activities"))
        self.activities.page.assert_called_once_with(
            "first", "12", "7", today=date(2026, 9, 24)
        )
        self.assertEqual(self.handler.responses, [(200, {"activities": []})])

        self.activities.page.reset_mock()
        self.today.return_value = date(2026, 9, 25)
        self.handler.path = "/api/activities"
        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/activities"))
        self.activities.page.assert_called_once_with(
            None, None, -1, today=date(2026, 9, 25)
        )
        self.assertEqual(self.today.call_count, 2)

    def test_unknown_path_resolves_no_factories(self) -> None:
        self.assertFalse(dispatch_route(self.routes, self.handler, "/api/sync/other"))
        self.queue_factory.assert_not_called()
        self.sync_state_factory.assert_not_called()
        self.activity_factory.assert_not_called()

    def test_activity_detail_is_local_only_and_preserves_case(
        self,
    ) -> None:
        self.activities.detail.return_value = {
            "activity_id": "CaseSensitive-1",
            "activity_validation": {},
        }
        self.assertTrue(
            dispatch_route(self.routes, self.handler, "/api/activities/CaseSensitive-1")
        )
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

    def test_activity_page_and_detail_are_passed_through(
        self,
    ) -> None:
        self.activities.page.return_value = {
            "activities": [
                {
                    "id": "act_a1",
                    "started_at_local": "2026-10-11T07:00:00",
                    "moving_duration_s": 3600,
                    "training_load": 40,
                    "rpe": 4,
                }
            ]
        }
        self.handler.path = "/api/activities"
        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/activities"))
        # The v1 document already names its metrics provider-neutrally.
        document = {
            "contract": "activity_detail.v1",
            "metrics": {"intensity": {"value": 0.75}},
            "laps": {"laps": [{"metrics": {"load": 12}}]},
        }
        self.activities.detail.return_value = dict(document)
        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/activities/a1"))

        self.assertEqual(
            [
                (
                    200,
                    {
                        "activities": [
                            {
                                "id": "act_a1",
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

    def for_activity_ids(self, _activity_ids: object, **_options: object) -> tuple[()]:
        return ()


class ActivityDetailRouteTests(unittest.TestCase):
    """Serve canonical detail documents through the production read assembly."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        add_session_record(
            self.manager, ProviderId.WAHOO, "w1", "act_w", recorded_by="wahoo"
        )
        add_session_record(
            self.manager, ProviderId.GARMIN, "g1", "act_g", duration_s=3600.0
        )
        snapshots = _Snapshots()
        ctx = SimpleNamespace(
            database=lambda: self.manager,
            athlete=SimpleNamespace(
                activity_feedback=_Feedback,
                profile=lambda: SimpleNamespace(get_from_db=lambda _db: {}),
                equipment=lambda: SimpleNamespace(
                    read=lambda *, activity_id: {"items": [], "assignments": []}
                ),
            ),
            canonical_read=ServedActivityReads(snapshots),
        )
        self.assembly = build_activity_reads(
            cast(Any, ctx),
            session_activities=CanonicalTableReader().session_activities,
            refreshable_providers=lambda: ("intervals", "garmin"),
        )
        self.reads = Mock(side_effect=self.assembly.activity_read)
        self.routes = SyncGetRoutes(
            Mock(),
            Mock(),
            self.reads,
            lambda: date(2026, 9, 20),
            -1,
        )

    def get(self, activity_id: str) -> dict:
        handler = FakeHandler()
        self.assertTrue(
            dispatch_route(self.routes, handler, f"/api/activities/{activity_id}")
        )
        ((status, payload),) = handler.responses
        self.assertEqual(200, status)
        assert isinstance(payload, dict)
        return payload

    def test_detail_body_is_the_v1_document_without_validation(self) -> None:
        for requested in ("act_w", "w1"):
            with self.subTest(requested):
                body = self.get(requested)
                self.assertEqual("activity_detail.v1", body["contract"])
                self.assertEqual("act_w", body["session"]["activity_id"])
                # No Intervals.icu summary-row metric is served (#1685).
                self.assertNotIn("avg_speed_mps", body["metrics"])
                self.assertEqual(
                    {"activity_feedback", "equipment"},
                    {"activity_feedback", "equipment", "activity_validation"}
                    & set(body),
                )
                self.assertTrue(body["ok"])
                self.assertIn("providers: Wahoo", body["data_scope"])
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
                dispatch_route(
                    self.routes, FakeHandler(), f"/api/activities/{activity_id}"
                )
            self.assertEqual(404, missing.exception.status)
            self.assertEqual("activity_details_not_found", missing.exception.reason)


if __name__ == "__main__":
    unittest.main()
