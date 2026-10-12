"""Local canonical and provider activity references resolve once at each boundary.

Each test uses a temporary SQLite file through the real DatabaseManager and the
canonical schema. Provider services are replaced by small mocks. No provider
account, network, real data directory or encryption key is involved.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from backend.activities.activity_reference import (
    ActivityReferences,
    NoActivityReferences,
)
from backend.activities.detail_store import ActivityDetailStore
from backend.activities.duplicate_service import DuplicateActivityService
from backend.activities.feedback import ActivityFeedbackService
from backend.activities.read_service import ActivityReadService
from backend.athlete.equipment import EquipmentService
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.http_api.feedback_post import FeedbackPostRoutes
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.sync.activity_details import ActivityDetailRefreshService
from backend.sync.queue import SyncJobQueueService

TODAY = date(2026, 5, 4)
STAMP = "2026-10-11T08:00:00+00:00"
RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
START = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = DatabaseManager(
            Path(directory.name) / "references.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)

    def seed(
        self, provider_activity_id: str, provider: ProviderId = ProviderId.INTERVALS
    ) -> str:
        """Create the canonical session and record for one provider activity."""
        record = ActivityRecord(
            activity_id="unused",
            provenance=Provenance(
                provider=provider,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=provider_activity_id,
                recorded_by=RecordingOrigin.UNKNOWN,
                retrieved_at=RETRIEVED_AT,
                label=None,
            ),
            sport=Sport.RIDE,
            environment=Environment.OUTDOOR,
            started_at=START,
            duration_s=3600.0,
            distance_m=30000.0,
            load=50.0,
            load_model=LoadModel.INTERVALS_TRAINING_LOAD,
            avg_hr=140.0,
            avg_power=210.0,
            name="Synthetic ride",
        )
        with self.manager.unit_of_work() as db:
            canonical_store.upsert_activity_record(
                db,
                record,
                local_date=date(2026, 6, 1),
                mapper_version=1,
                fetched_at=STAMP,
                now=STAMP,
            )
            row = db.execute(
                "SELECT activity_id FROM activity_records "
                "WHERE provider_activity_id = ?",
                (provider_activity_id,),
            ).fetchone()
        return str(row["activity_id"])

    def merge(self, duplicate_local_id: str, primary_local_id: str) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state = 'duplicate', merged_into = ? "
                "WHERE activity_id = ?",
                (primary_local_id, duplicate_local_id),
            )

    def set_state(self, local_activity_id: str, state: str) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state = ? WHERE activity_id = ?",
                (state, local_activity_id),
            )


class ActivityReferenceResolverTests(_Fixture):
    def test_local_id_resolves_to_its_provider_id(self) -> None:
        local = self.seed("ride-1")
        self.assertTrue(local.startswith(canonical_store.ACTIVITY_ID_PREFIX))
        self.assertEqual("ride-1", ActivityReferences(self.manager).resolve(local))

    def test_duplicate_session_resolves_to_its_own_provider_id(self) -> None:
        duplicate = self.seed("ride-a")
        primary = self.seed("ride-b")
        self.merge(duplicate, primary)
        self.assertEqual("ride-a", ActivityReferences(self.manager).resolve(duplicate))

    def test_garmin_primary_session_passes_through_unchanged(self) -> None:
        local = self.seed("garmin-1", provider=ProviderId.GARMIN)
        self.assertEqual(local, ActivityReferences(self.manager).resolve(local))

    def test_deleted_session_passes_through_unchanged(self) -> None:
        local = self.seed("ride-deleted")
        self.set_state(local, "deleted")
        self.assertEqual(local, ActivityReferences(self.manager).resolve(local))

    def test_unknown_local_id_passes_through_unchanged(self) -> None:
        self.assertEqual(
            "act_missing", ActivityReferences(self.manager).resolve("act_missing")
        )

    def test_provider_ids_and_non_text_values_pass_through_unchanged(self) -> None:
        references = ActivityReferences(self.manager)
        self.assertEqual("ride-1", references.resolve("ride-1"))
        self.assertEqual(42, references.resolve(42))
        self.assertIsNone(references.resolve(None))

    def test_local_ids_map_provider_ids_that_have_canonical_records(self) -> None:
        local = self.seed("ride-1")
        references = ActivityReferences(self.manager)
        self.assertEqual({"ride-1": local}, references.local_ids(["ride-1", "ride-2"]))

    def test_local_ids_are_empty_for_empty_or_blank_input(self) -> None:
        references = ActivityReferences(self.manager)
        self.assertEqual({}, references.local_ids([]))
        self.assertEqual({}, references.local_ids([""]))

    def test_null_object_is_identity_and_has_no_local_ids(self) -> None:
        references = NoActivityReferences()
        self.assertEqual("act_x", references.resolve("act_x"))
        self.assertEqual({}, references.local_ids(["ride-1"]))


class ActivityReadReferenceTests(_Fixture):
    def _service(self, activities: list[dict[str, object]]) -> ActivityReadService:
        snapshot = {
            "synced_at": STAMP,
            "athlete": {},
            "recent_wellness": [],
            "recent_activities": activities,
        }
        feedback = Mock(
            attach_to_activities=Mock(
                side_effect=lambda rows: [
                    dict(row) for row in rows if isinstance(row, dict)
                ]
            )
        )
        return ActivityReadService(
            self.manager,
            Mock(latest_snapshot=Mock(return_value=snapshot)),
            feedback,
            references=ActivityReferences(self.manager),
        )

    def test_page_items_carry_local_activity_id_or_null(self) -> None:
        local = self.seed("ride-1")
        service = self._service(
            [
                {
                    "id": "ride-1",
                    "start_date_local": "2026-06-01T07:00:00",
                    "type": "Ride",
                },
                {
                    "id": "ride-2",
                    "start_date_local": "2026-05-01T07:00:00",
                    "type": "Ride",
                },
            ]
        )
        result = service.page(today=TODAY)
        by_id = {item["id"]: item["local_activity_id"] for item in result["activities"]}
        self.assertEqual({"ride-1": local, "ride-2": None}, by_id)

    def test_versioned_cursor_resumes_after_the_provider_key(self) -> None:
        self.seed("ride-1")
        service = self._service(
            [
                {
                    "id": "ride-1",
                    "start_date_local": "2026-06-01T07:00:00",
                    "type": "Ride",
                },
                {
                    "id": "ride-2",
                    "start_date_local": "2026-05-01T07:00:00",
                    "type": "Ride",
                },
            ]
        )
        first = service.page(today=TODAY, limit=1)
        second = service.page(today=TODAY, limit=1, cursor=first["next_cursor"])
        self.assertEqual(["ride-1"], [item["id"] for item in first["activities"]])
        self.assertEqual(["ride-2"], [item["id"] for item in second["activities"]])
        self.assertIsNone(second["next_cursor"])

    def test_recent_items_carry_local_activity_id_or_null(self) -> None:
        local = self.seed("ride-1")
        service = self._service(
            [
                {
                    "id": "ride-1",
                    "start_date_local": "2026-06-01T07:00:00",
                    "type": "Ride",
                },
                {
                    "id": "ride-2",
                    "start_date_local": "2026-05-01T07:00:00",
                    "type": "Ride",
                },
            ]
        )
        result = service.recent(today=TODAY)
        by_id = {item["id"]: item["local_activity_id"] for item in result["activities"]}
        self.assertEqual({"ride-1": local, "ride-2": None}, by_id)


class ActivityCallerResolutionTests(_Fixture):
    def test_detail_resolves_local_id_and_reports_it(self) -> None:
        local = self.seed("ride-1")
        raw = {
            "id": "ride-1",
            "start_date_local": "2026-06-01T07:00:00",
            "type": "Ride",
            "moving_time": 3600,
        }
        service = ActivityAnalysisReadService(
            self.manager,
            Mock(
                latest_snapshot=Mock(
                    return_value={
                        "synced_at": STAMP,
                        "athlete": {},
                        "recent_wellness": [],
                        "recent_activities": [],
                        "raw_provider_data": {"activities": [raw]},
                    }
                )
            ),
            Mock(
                attach_to_activities=Mock(side_effect=lambda rows: list(rows)),
                list=Mock(return_value=[]),
            ),
            ActivityDetailStore(self.manager),
            references=ActivityReferences(self.manager),
        )
        result = service.detail(local, garmin_snapshot={}, profile={}, today=TODAY)
        self.assertEqual(local, result["local_activity_id"])
        self.assertEqual(3600, result["activity"]["moving_time"])

    def test_feedback_is_stored_under_the_provider_id(self) -> None:
        local = self.seed("ride-1")
        repository = Mock()
        repository.get.return_value = None
        repository.list.return_value = []
        service = ActivityFeedbackService(
            self.manager,
            repository,
            Mock(),
            references=ActivityReferences(self.manager),
        )
        service.save(local, {"session_rpe": 6})
        self.assertEqual("ride-1", repository.get.call_args.args[1])
        self.assertEqual("ride-1", repository.upsert.call_args.args[1]["activity_id"])

    def test_coach_feedback_route_accepts_local_id(self) -> None:
        local = self.seed("ride-1")
        snapshot_reader = Mock(
            latest_snapshot=Mock(return_value={"recent_activities": [{"id": "ride-1"}]})
        )
        repository = Mock()
        repository.get.return_value = None
        repository.list.return_value = [{"activity_id": "ride-1", "session_rpe": 6}]
        service = ActivityFeedbackService(
            self.manager,
            repository,
            snapshot_reader,
            references=ActivityReferences(self.manager),
        )
        routes = FeedbackPostRoutes(lambda: Mock(), lambda: service)
        handler = SimpleNamespace(
            read_json=Mock(return_value={"session_rpe": 6}), send_json=Mock()
        )
        self.assertTrue(routes.handle(handler, f"/api/activities/{local}/feedback"))
        status, body = handler.send_json.call_args.args
        self.assertEqual(200, status)
        self.assertEqual("ride-1", body["activity_feedback"]["activity_id"])

    def test_coach_feedback_route_keeps_not_found_for_unknown_local_id(self) -> None:
        snapshot_reader = Mock(
            latest_snapshot=Mock(return_value={"recent_activities": [{"id": "ride-1"}]})
        )
        service = ActivityFeedbackService(
            self.manager,
            Mock(get=Mock(return_value=None)),
            snapshot_reader,
            references=ActivityReferences(self.manager),
        )
        routes = FeedbackPostRoutes(lambda: Mock(), lambda: service)
        handler = SimpleNamespace(
            read_json=Mock(return_value={"session_rpe": 6}), send_json=Mock()
        )
        with self.assertRaises(AppError):
            routes.handle(handler, "/api/activities/act_missing/feedback")
        handler.send_json.assert_not_called()

    def test_equipment_assignment_resolves_the_reference_at_the_boundary(self) -> None:
        local = self.seed("ride-1")
        resolver = Mock(return_value="ride-1")
        service = EquipmentService(
            self.manager,
            read_snapshot=dict,
            today=lambda: TODAY,
            utc_now=lambda: STAMP,
            canonical_rows=lambda _snapshot: ([], 0),
            resolve_activity=resolver,
        )
        with self.assertRaises(AppError):
            service.assign({"activity_id": local, "equipment_id": "bike-1"})
        resolver.assert_called_once_with(local)

    def test_equipment_without_resolver_keeps_the_reference_unchanged(self) -> None:
        service = EquipmentService(
            self.manager,
            read_snapshot=dict,
            today=lambda: TODAY,
            utc_now=lambda: STAMP,
            canonical_rows=lambda _snapshot: ([], 0),
        )
        with self.assertRaises(AppError):
            service.assign({"activity_id": "act_missing", "equipment_id": "bike-1"})

    def test_duplicate_delete_validates_resolved_provider_ids(self) -> None:
        canonical = self.seed("wahoo-1")
        duplicate = self.seed("garmin-1")
        service = DuplicateActivityService(
            self.manager,
            Mock(),
            Mock(latest_snapshot=Mock(return_value=None)),
            Mock(),
            Mock(),
            references=ActivityReferences(self.manager),
        )
        with (
            patch(
                "backend.activities.duplicate_service.latest_wahoo_garmin_duplicate",
                return_value=None,
            ),
            patch(
                "backend.activities.duplicate_service.validate_duplicate_delete",
                side_effect=RuntimeError("stop after resolution"),
            ) as validate,
            self.assertRaises(RuntimeError),
        ):
            service.delete(
                {"canonical_id": canonical, "duplicate_id": duplicate},
                intervals_client=Mock(),
            )
        self.assertEqual(
            {"canonical_id": "wahoo-1", "duplicate_id": "garmin-1"},
            validate.call_args.args[0],
        )

    def test_activity_detail_job_is_stored_under_the_provider_id(self) -> None:
        local = self.seed("ride-1")
        store = MagicMock()
        store.enqueue.return_value = ({"id": "job-1"}, True)
        service = SyncJobQueueService(
            store,
            Mock(),
            MagicMock(),
            Mock(),
            7,
            Mock(),
            references=ActivityReferences(self.manager),
        )
        with (
            patch(
                "backend.sync.queue.normalize_sync_job_request",
                side_effect=RuntimeError("stop after resolution"),
            ) as normalize,
            self.assertRaises(RuntimeError),
        ):
            service.enqueue(
                "intervals",
                "activity_details",
                {"activity_id": local},
            )
        self.assertEqual({"activity_id": "ride-1"}, normalize.call_args.args[2])

    def test_detail_refresh_fetches_the_provider_activity(self) -> None:
        local = self.seed("ride-1")
        api = Mock()
        api.get.side_effect = [
            {"id": "ride-1", "name": "Synthetic ride"},
            [
                {"type": "time", "data": [0, 1, 2]},
                {"type": "watts", "data": [200, 210, 220]},
            ],
        ]
        state = Mock()
        state.latest_snapshot.return_value = {
            "raw_provider_data": {"activities": [{"id": "ride-1"}]}
        }
        service = ActivityDetailRefreshService(
            api_client=api,
            state_repository=state,
            store=ActivityDetailStore(self.manager),
            utc_now=lambda: "2026-10-02T08:00:00Z",
            configured=True,
            references=ActivityReferences(self.manager),
        )
        service.refresh(local)
        self.assertEqual("/activity/ride-1", api.get.call_args_list[0].args[0])
        self.assertIsNotNone(ActivityDetailStore(self.manager).get("ride-1"))


if __name__ == "__main__":
    unittest.main()
