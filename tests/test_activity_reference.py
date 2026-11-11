"""Local canonical and provider activity references resolve once at each boundary.

Each test uses a temporary SQLite file through the real DatabaseManager and the
canonical schema. Provider services are replaced by small mocks. No provider
account, network, real data directory or encryption key is involved.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from activity_row_support import (
    FixedActivityRows,
    canonical_source,
)
from support import temp_database

from backend.activities.activity_reference import (
    ActivityReference,
    ActivityReferences,
    NoActivityReferences,
)
from backend.activities.feedback import ActivityFeedbackService
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
from backend.db import canonical_store, row_factory
from backend.db.repositories import ActivityFeedbackRepository
from backend.errors import AppError
from backend.http_api.feedback_post import FeedbackPostRoutes
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.detail_envelope import DetailEnvelopeReader
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS
from backend.sync.canonical_table_reader import CanonicalTableReader

TODAY = date(2026, 5, 4)
STAMP = "2026-10-11T08:00:00+00:00"
RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
START = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(
            self, "references.db", row_factory=row_factory, schema=True
        )

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
    def test_a_reference_resolves_to_the_session_it_names_not_the_survivor(
        self,
    ) -> None:
        intervals = self.seed("ride-merged")
        garmin = self.seed("garmin-survivor", provider=ProviderId.GARMIN)
        self.merge(intervals, garmin)
        references = ActivityReferences(self.manager)
        for reference, session in (
            (garmin, garmin),
            ("garmin-survivor", garmin),
            (intervals, intervals),
            ("ride-merged", intervals),
        ):
            with self.subTest(reference):
                self.assertEqual(
                    ActivityReference(session), references.resolve_reference(reference)
                )

    def test_references_follow_the_survivor_a_deleted_alias_retained(self) -> None:
        intervals = self.seed("ride-merged")
        garmin = self.seed("garmin-survivor", provider=ProviderId.GARMIN)
        self.merge(intervals, garmin)
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted', merged_into = NULL, "
                "merged_into_retained = ? WHERE activity_id = ?",
                (garmin, intervals),
            )
        references = ActivityReferences(self.manager)
        self.assertEqual(
            ActivityReference(garmin), references.resolve_reference(intervals)
        )
        self.assertEqual(
            ActivityReference(garmin), references.resolve_reference("garmin-survivor")
        )

    def test_unresolvable_references_pass_through(self) -> None:
        local = self.seed("ride-1")
        self.set_state(local, "deleted")
        references = ActivityReferences(self.manager)
        for reference in (local, "act_missing", "unknown-id", " ", 42, None):
            with self.subTest(reference):
                self.assertEqual(
                    ActivityReference(reference),
                    references.resolve_reference(reference),
                )

    def test_null_object_keeps_the_reference(self) -> None:
        self.assertEqual(
            ActivityReference("act_x"),
            NoActivityReferences().resolve_reference("act_x"),
        )

    def test_envelope_reads_feedback_keyed_by_the_session_id(self) -> None:
        intervals = self.seed("ride-merged")
        garmin = self.seed("garmin-survivor", provider=ProviderId.GARMIN)
        self.merge(intervals, garmin)
        feedback = Mock()
        feedback.for_activity_ids.side_effect = lambda ids, **_options: [
            {"activity_id": key, "session_rpe": 6} for key in ids if key == garmin
        ]
        envelope = DetailEnvelopeReader(
            feedback_service=feedback,
            read_equipment=lambda reference: {},
            references=ActivityReferences(self.manager),
            performance=dict,
            summary=lambda: None,
        )
        with self.manager.reader() as db:
            block = envelope(db, garmin)
        self.assertEqual(6, block["activity_feedback"]["session_rpe"])

    def test_envelope_reads_equipment_of_the_live_session_for_a_merged_copy(
        self,
    ) -> None:
        intervals = self.seed("ride-merged")
        garmin = self.seed("garmin-survivor", provider=ProviderId.GARMIN)
        self.merge(intervals, garmin)
        feedback = Mock()
        feedback.for_activity_ids.return_value = []
        read: list[str] = []

        def read_equipment(reference: str) -> dict[str, Any]:
            read.append(reference)
            return {}

        envelope = DetailEnvelopeReader(
            feedback_service=feedback,
            read_equipment=read_equipment,
            references=ActivityReferences(self.manager),
            performance=dict,
            summary=lambda: None,
        )
        with self.manager.reader() as db:
            envelope(db, "ride-merged")
        self.assertEqual([garmin], read)


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
            FixedActivityRows(),
            Mock(
                attach_to_activities=Mock(side_effect=lambda rows: list(rows)),
                list=Mock(return_value=[]),
                for_activity_ids=Mock(return_value=[]),
            ),
            references=ActivityReferences(self.manager),
            canonical=canonical_source(FixedActivityRows([raw]), lambda: self.manager),
            session_records=CanonicalTableReader().session_activities,
        )
        for requested in (local, "ride-1"):
            with self.subTest(requested):
                result = service.detail(
                    requested,
                    garmin_status=NO_GARMIN_SYNC_STATUS,
                    profile={},
                    today=TODAY,
                )
                self.assertEqual(local, result["session"]["activity_id"])
                self.assertEqual(3600, result["metrics"]["duration_s"]["value"])

    def test_feedback_is_stored_under_the_session_id(self) -> None:
        local = self.seed("ride-1")
        repository = Mock()
        repository.all.return_value = []
        service = ActivityFeedbackService(
            self.manager,
            repository,
            references=ActivityReferences(self.manager),
        )
        service.save(local, {"session_rpe": 6})
        self.assertEqual(local, repository.upsert.call_args.args[1]["activity_id"])
        self.assertEqual(local, repository.upsert.call_args.kwargs["session_id"])
        self.assertIsNone(repository.upsert.call_args.kwargs["provider"])

    def test_coach_feedback_route_accepts_local_id(self) -> None:
        local = self.seed("ride-1")
        repository = Mock()
        repository.all.return_value = []
        service = ActivityFeedbackService(
            self.manager,
            repository,
            references=ActivityReferences(self.manager),
        )
        routes = FeedbackPostRoutes(lambda: service)
        handler = SimpleNamespace(
            read_json=Mock(return_value={"session_rpe": 6}), send_json=Mock()
        )
        self.assertTrue(routes.handle(handler, f"/api/activities/{local}/feedback"))
        status, body = handler.send_json.call_args.args
        self.assertEqual(200, status)
        self.assertEqual(local, body["activity_feedback"]["activity_id"])

    def test_coach_feedback_route_keeps_not_found_for_unknown_local_id(self) -> None:
        service = ActivityFeedbackService(
            self.manager,
            Mock(get=Mock(return_value=None)),
            references=ActivityReferences(self.manager),
        )
        routes = FeedbackPostRoutes(lambda: service)
        handler = SimpleNamespace(
            read_json=Mock(return_value={"session_rpe": 6}), send_json=Mock()
        )
        with self.assertRaises(AppError):
            routes.handle(handler, "/api/activities/act_missing/feedback")
        handler.send_json.assert_not_called()

    def test_equipment_without_resolver_keeps_the_reference_unchanged(self) -> None:
        service = EquipmentService(
            self.manager,
            read_summaries=tuple,
            today=lambda: TODAY,
            utc_now=lambda: STAMP,
        )
        with self.assertRaises(AppError):
            service.assign({"activity_id": "act_missing", "equipment_id": "bike-1"})


class ActivityFeedbackKeyTests(_Fixture):
    """Feedback rows are keyed by the live session id and carry no provider."""

    def _service(self):
        return ActivityFeedbackService(
            self.manager,
            ActivityFeedbackRepository(lambda: STAMP),
            references=ActivityReferences(self.manager),
        )

    def _rows(self):
        with self.manager.unit_of_work() as db:
            return db.execute(
                "SELECT activity_id, provider, session_id FROM activity_feedback "
                "ORDER BY activity_id"
            ).fetchall()

    def test_local_id_is_stored_under_the_session_id_without_a_provider(self) -> None:
        local = self.seed("ride-1")
        self._service().save(local, {"session_rpe": 6})
        self.assertEqual(
            [(local, None, local)],
            [tuple(row.values()) for row in self._rows()],
        )

    def test_a_provider_id_is_stored_under_the_session_id_too(self) -> None:
        local = self.seed("ride-1")
        self._service().save("ride-1", {"session_rpe": 6})
        self.assertEqual([local], [row["activity_id"] for row in self._rows()])

    def test_unresolved_id_records_no_provider(self) -> None:
        self._service().save("ride-unknown", {"notes": "passthrough"})
        self.assertEqual(
            [("ride-unknown", None, None)],
            [tuple(row.values()) for row in self._rows()],
        )

    def test_null_reference_resolver_records_no_provider(self) -> None:
        service = ActivityFeedbackService(
            self.manager,
            ActivityFeedbackRepository(lambda: STAMP),
            references=NoActivityReferences(),
        )
        service.save("ride-1", {"notes": "no resolver"})
        self.assertEqual(
            [("ride-1", None)],
            [(row["activity_id"], row["provider"]) for row in self._rows()],
        )

    def test_a_later_edit_by_provider_id_updates_the_same_row(self) -> None:
        local = self.seed("ride-1")
        service = self._service()
        service.save(local, {"session_rpe": 5})
        service.save("ride-1", {"notes": "later edit by provider id"})
        self.assertEqual([local], [row["activity_id"] for row in self._rows()])
        self.assertEqual(5, service.list()[0]["session_rpe"])

    def test_coach_save_is_stored_under_the_session_id(self) -> None:
        local = self.seed("ride-1")
        result = self._service().save_coach(local, {"session_rpe": 4})
        self.assertEqual(local, result["activity_feedback"]["activity_id"])
        self.assertEqual([local], [row["activity_id"] for row in self._rows()])

    def test_api_feedback_json_keeps_the_released_keys(self) -> None:
        local = self.seed("ride-1")
        service = self._service()
        saved = service.save(local, {"notes": "felt good", "session_rpe": 3})
        self.assertEqual(
            {
                "activity_id",
                "activity_name",
                "activity_date",
                "notes",
                "session_rpe",
                "deviation_reason",
                "created_at",
                "updated_at",
                "session_rpe_rated_at",
            },
            set(saved["activity_feedback"]),
        )
        self.assertEqual(saved["activity_feedback"], service.list()[0])


if __name__ == "__main__":
    unittest.main()
