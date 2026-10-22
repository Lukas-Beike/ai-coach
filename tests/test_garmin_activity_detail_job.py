"""On-demand Garmin activity detail job: service, reader, executor, queue, and guard."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from canonical_detail_support import NOW, ZONE, open_manager
from support import make_config

from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ActivityRecordState,
    ProviderId,
    RecordingOrigin,
)
from backend.db.activity_detail_store import detail_sets_for
from backend.errors import AppError
from backend.providers import canonical_plans as plans
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin_activity_detail_mapping import MAPPER_VERSION
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_ingest import ingest_plan
from backend.sync.executor import GarminSyncJobOwner
from backend.sync.garmin_activity_details import COOLDOWN, GarminActivityDetailService
from backend.sync.garmin_assembly import GarminAssembly, _non_blocking_garmin_guard
from backend.sync.garmin_service import GarminRemoteReader, GarminSyncCoordination
from backend.sync.jobs import normalize_sync_job_request
from backend.sync.queue import SyncJobQueueService

ACTIVITY = "123456789"
NOW_AT = datetime.fromisoformat(NOW)
KINDS = ["heart_rate_zones", "laps", "power_zones", "streams"]
FIXTURES = (
    Path(__file__).parent / "fixtures" / "providers" / "garmin" / "activity_detail"
)


def _collected() -> dict[str, Any]:
    collected: dict[str, Any] = {"activity_id": ACTIVITY}
    for part in ("details", "splits", "hr_zones", "power_zones"):
        text = (FIXTURES / f"{part}.json").read_text(encoding="utf-8")
        collected[part] = json.loads(text)
    return collected


def _seed_garmin_activity(
    manager: Any, activity_id: str, *, distance: float = 20000.0
) -> None:
    payload = {
        "synced_at": NOW,
        "activities": [
            {
                "activityId": int(activity_id),
                "activityName": "Synthetic ride",
                "activityType": {"typeKey": "cycling"},
                "startTimeLocal": "2026-10-08 07:15:00",
                "distance": distance,
                "duration": 3600.0,
                "averageHR": 140,
                "activityTrainingLoad": 50.0,
            }
        ],
    }
    plan = plans.garmin_ingest_plan(payload, zone=ZONE)
    with manager.unit_of_work() as db:
        ingest_plan(
            db,
            plan,
            retrieved_at=NOW_AT,
            deletion_window=None,
            zone=ZONE,
        )


def _session_id(manager: Any, activity_id: str) -> str:
    with manager.reader() as db:
        row = db.execute(
            "SELECT activity_id FROM activity_records "
            "WHERE provider = ? AND provider_activity_id = ?",
            (GARMIN_ID, activity_id),
        ).fetchone()
    return str(row["activity_id"])


def _stored(manager: Any, activity_id: str = ACTIVITY) -> dict[str, str]:
    with manager.reader() as db:
        items = detail_sets_for(db, GARMIN_ID, activity_id)
    return {item.detail.kind.value: item.fetched_at for item in items}


def _service(manager: Any, reader: Any, *, now: str = NOW, configured: bool = True):
    return GarminActivityDetailService(
        database_manager=manager,
        reader=reader,
        configured=lambda: configured,
        guard=lambda: nullcontext(),
        utc_now=lambda: now,
    )


def _owner(
    *, activity_detail_service: Any, garmin_sync_service: Any = None
) -> GarminSyncJobOwner:
    return GarminSyncJobOwner(
        historical_sync=Mock(),
        garmin_sync_service=garmin_sync_service or Mock(),
        morning_body_battery_service=Mock(),
        garmin_fixture_loader=Mock(),
        all_sync_days=-1,
        activity_detail_service=activity_detail_service,
    )


def _config():
    return make_config(
        openai_base_url="",
        openai_model="",
        intervals_athlete_id="",
        data_retention_days=30,
        garmin_email="athlete@example.invalid",
        garmin_password="secret",
        garmin_tokenstore="missing-tokenstore",
    )


class GarminActivityDetailJobTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        _seed_garmin_activity(self.manager, ACTIVITY)
        self.reader = Mock()
        self.reader.fetch_activity_detail.return_value = _collected()

    def service(self, **kwargs: Any) -> GarminActivityDetailService:
        return _service(self.manager, self.reader, **kwargs)

    def test_happy_path_writes_every_kind_with_garmin_provenance(self) -> None:
        result = self.service().refresh(ACTIVITY)

        self.assertEqual(
            result,
            {"status": "completed", "activity_id": ACTIVITY, "kinds": KINDS},
        )
        self.reader.fetch_activity_detail.assert_called_once_with(ACTIVITY)
        with self.manager.reader() as db:
            items = detail_sets_for(db, GARMIN_ID, ACTIVITY)
        self.assertEqual(len(items), 4)
        for item in items:
            with self.subTest(kind=item.detail.kind.value):
                self.assertEqual(item.provider, GARMIN_ID)
                self.assertEqual(item.mapper_version, MAPPER_VERSION)
                self.assertEqual(item.detail.provenance.provider, ProviderId.GARMIN)
                self.assertEqual(item.detail.origin, ActivityDetailOrigin.FETCH)
                self.assertEqual(datetime.fromisoformat(item.fetched_at), NOW_AT)

    def test_partial_payload_writes_returned_kinds_and_keeps_stored_laps(self) -> None:
        self.service().refresh(ACTIVITY)
        stored_laps = _stored(self.manager)["laps"]
        partial = _collected()
        del partial["splits"]
        partial["errors"] = [{"source": "splits", "message": "synthetic"}]
        self.reader.fetch_activity_detail.return_value = partial
        later = NOW_AT + timedelta(hours=1)

        result = self.service(now=later.isoformat()).refresh(ACTIVITY)

        self.assertEqual(
            result,
            {
                "status": "partial",
                "activity_id": ACTIVITY,
                "kinds": ["heart_rate_zones", "power_zones", "streams"],
            },
        )
        stored = _stored(self.manager)
        self.assertEqual(sorted(stored), KINDS)
        self.assertEqual(stored["laps"], stored_laps)
        self.assertEqual(datetime.fromisoformat(stored["streams"]), later)

    def test_paused_part_makes_the_refresh_partial(self) -> None:
        paused = _collected()
        del paused["splits"]
        paused["skipped"] = ["activity_splits"]
        self.reader.fetch_activity_detail.return_value = paused

        result = self.service().refresh(ACTIVITY)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["kinds"], ["heart_rate_zones", "power_zones", "streams"]
        )

    def test_sets_carry_the_hash_of_the_stored_garmin_summary(self) -> None:
        self.service().refresh(ACTIVITY)

        with self.manager.reader() as db:
            summary = db.execute(
                "SELECT payload_hash FROM provider_records "
                "WHERE provider = ? AND record_kind = 'activity' "
                "AND source_record_id = ?",
                (GARMIN_ID, ACTIVITY),
            ).fetchone()["payload_hash"]
            items = detail_sets_for(db, GARMIN_ID, ACTIVITY)
        self.assertRegex(summary, r"^[0-9a-f]{64}$")
        self.assertEqual({item.summary_sha256 for item in items}, {summary})

    def test_every_part_failing_gives_502_and_keeps_stored_sets(self) -> None:
        self.service().refresh(ACTIVITY)
        stored = _stored(self.manager)
        self.reader.fetch_activity_detail.return_value = {
            "activity_id": ACTIVITY,
            "errors": [{"source": "activity_details", "message": "synthetic"}],
        }
        later = NOW_AT + timedelta(hours=1)

        with self.assertRaises(AppError) as ctx:
            self.service(now=later.isoformat()).refresh(ACTIVITY)

        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.reason, "activity_details_unavailable")
        self.assertEqual(_stored(self.manager), stored)

    def test_no_returned_part_reports_unchanged(self) -> None:
        self.reader.fetch_activity_detail.return_value = {"activity_id": ACTIVITY}

        result = self.service().refresh(ACTIVITY)

        self.assertEqual(
            result, {"status": "unchanged", "activity_id": ACTIVITY, "kinds": []}
        )
        self.assertEqual(_stored(self.manager), {})

    def test_manual_activity_is_skipped_without_reader_call(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET recorded_by = ? "
                "WHERE provider = ? AND provider_activity_id = ?",
                (RecordingOrigin.MANUAL.value, GARMIN_ID, ACTIVITY),
            )

        result = self.service().refresh(ACTIVITY)

        self.assertEqual(
            result,
            {"status": "skipped", "reason": "manual_activity", "activity_id": ACTIVITY},
        )
        self.reader.fetch_activity_detail.assert_not_called()
        self.assertEqual(_stored(self.manager), {})

    def test_cooldown_skips_reader_until_it_expires(self) -> None:
        self.service().refresh(ACTIVITY)

        within = NOW_AT + timedelta(minutes=5)
        result = self.service(now=within.isoformat()).refresh(ACTIVITY)

        self.assertEqual(
            result,
            {"status": "unchanged", "activity_id": ACTIVITY, "kinds": KINDS},
        )
        self.reader.fetch_activity_detail.assert_called_once()

        after = NOW_AT + COOLDOWN + timedelta(seconds=1)
        refreshed = self.service(now=after.isoformat()).refresh(ACTIVITY)
        self.assertEqual(refreshed["status"], "completed")
        self.assertEqual(self.reader.fetch_activity_detail.call_count, 2)

    def test_changed_summary_bypasses_the_cooldown(self) -> None:
        self.service().refresh(ACTIVITY)
        _seed_garmin_activity(self.manager, ACTIVITY, distance=21000.0)
        # The sets stay stored; only their summary hash is now stale.
        self.assertEqual(sorted(_stored(self.manager)), KINDS)

        within = NOW_AT + timedelta(minutes=5)
        result = self.service(now=within.isoformat()).refresh(ACTIVITY)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.reader.fetch_activity_detail.call_count, 2)

    def test_malformed_part_reports_partial(self) -> None:
        collected = _collected()
        collected["hr_zones"] = "synthetic malformed"
        self.reader.fetch_activity_detail.return_value = collected

        result = self.service().refresh(ACTIVITY)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["kinds"], ["laps", "power_zones", "streams"])

    def test_only_malformed_parts_give_502_without_writes(self) -> None:
        self.reader.fetch_activity_detail.return_value = {
            "activity_id": ACTIVITY,
            "hr_zones": "synthetic malformed",
        }

        with self.assertRaises(AppError) as ctx:
            self.service().refresh(ACTIVITY)

        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.reason, "activity_details_unavailable")
        self.assertEqual(_stored(self.manager), {})

    def test_unknown_activity_gives_404_without_reader_call(self) -> None:
        for requested in ("999999999", "act_missing"):
            with (
                self.subTest(requested=requested),
                self.assertRaises(AppError) as ctx,
            ):
                self.service().refresh(requested)
            self.assertEqual(ctx.exception.status, 404)
            self.assertEqual(ctx.exception.reason, "activity_details_not_found")
        self.reader.fetch_activity_detail.assert_not_called()

    def test_unconfigured_garmin_gives_503_without_reader_call(self) -> None:
        with self.assertRaises(AppError) as ctx:
            self.service(configured=False).refresh(ACTIVITY)

        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(ctx.exception.reason, "not_configured")
        self.reader.fetch_activity_detail.assert_not_called()

    def test_session_alias_resolves_to_the_garmin_record(self) -> None:
        session = _session_id(self.manager, ACTIVITY)

        result = self.service().refresh(session)

        self.assertEqual(result["activity_id"], ACTIVITY)
        self.reader.fetch_activity_detail.assert_called_once_with(ACTIVITY)

    def test_mfa_required_from_the_reader_propagates_as_401(self) -> None:
        self.reader.fetch_activity_detail.side_effect = AppError(
            401, "Garmin benötigt eine Bestätigung.", reason="garmin_mfa_required"
        )

        with self.assertRaises(AppError) as ctx:
            self.service().refresh(ACTIVITY)

        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(_stored(self.manager), {})

    def test_record_removed_during_fetch_is_not_written(self) -> None:
        def fetch_then_delete(_activity_id: str) -> dict[str, Any]:
            with self.manager.unit_of_work() as db:
                db.execute(
                    "UPDATE activity_records SET state = ? "
                    "WHERE provider = ? AND provider_activity_id = ?",
                    (ActivityRecordState.DELETED.value, GARMIN_ID, ACTIVITY),
                )
            return _collected()

        self.reader.fetch_activity_detail.side_effect = fetch_then_delete

        with self.assertRaises(AppError) as ctx:
            self.service().refresh(ACTIVITY)

        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(_stored(self.manager), {})


class GarminActivityDetailWiringTests(unittest.TestCase):
    def test_garmin_activity_details_job_is_accepted_by_normalization(self) -> None:
        envelope = normalize_sync_job_request(
            "garmin",
            "activity_details",
            {"activity_id": ACTIVITY},
            all_sync_days=-1,
        )

        self.assertEqual(envelope["provider"], GARMIN_ID)
        self.assertEqual(envelope["type"], "activity_details")
        self.assertEqual(envelope["payload"]["activity_id"], ACTIVITY)

    def test_executor_routes_garmin_activity_details_to_the_service(self) -> None:
        detail_service = Mock()
        detail_service.refresh.return_value = {"status": "completed"}
        sync_service = Mock()
        owner = _owner(
            activity_detail_service=detail_service,
            garmin_sync_service=sync_service,
        )

        result = owner.execute(
            {"type": "activity_details"}, {"activity_id": ACTIVITY}, "manual"
        )

        self.assertEqual(result, {"status": "completed"})
        detail_service.refresh.assert_called_once_with(ACTIVITY)
        self.assertEqual(sync_service.mock_calls, [])

    def test_executor_answers_503_when_the_service_is_not_composed(self) -> None:
        owner = _owner(activity_detail_service=None)

        with self.assertRaises(AppError) as ctx:
            owner.execute(
                {"type": "activity_details"}, {"activity_id": ACTIVITY}, "manual"
            )

        self.assertEqual(ctx.exception.status, 503)

    def test_queue_leaves_garmin_payload_unchanged(self) -> None:
        store = Mock()
        store.enqueue.return_value = (
            {
                "id": "job-1",
                "provider": GARMIN_ID,
                "type": "activity_details",
                "status": "queued",
                "progress": 0,
            },
            True,
        )
        references = Mock()
        queue = SyncJobQueueService(
            store,
            Mock(),
            MaintenanceGate(),
            threading.Event(),
            all_sync_days=-1,
            daily_sync_markers=Mock(),
            references=references,
        )

        queue.enqueue(
            GARMIN_ID,
            "activity_details",
            {"activity_id": ACTIVITY},
            requested_by="athlete",
        )

        references.resolve.assert_not_called()
        envelope = store.enqueue.call_args.args[0]
        self.assertEqual(envelope["payload"], {"activity_id": ACTIVITY})


class GarminActivityDetailGuardTests(unittest.TestCase):
    def test_busy_garmin_lock_answers_503_without_waiting(self) -> None:
        lock = threading.Lock()
        lock.acquire()
        self.addCleanup(lock.release)
        coordination = GarminSyncCoordination(lock)

        with (
            self.assertRaises(AppError) as ctx,
            _non_blocking_garmin_guard(coordination),
        ):
            self.fail("guard body must not run while Garmin is busy")

        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(ctx.exception.reason, "provider_busy")
        self.assertTrue(lock.locked())

    def test_free_garmin_lock_is_held_inside_the_guard_and_released_after(self) -> None:
        lock = threading.Lock()
        coordination = GarminSyncCoordination(lock)

        with _non_blocking_garmin_guard(coordination):
            self.assertTrue(lock.locked())

        self.assertFalse(lock.locked())


class GarminActivityDetailReaderTests(unittest.TestCase):
    def test_tokens_are_persisted_even_when_detail_collection_fails(self) -> None:
        client = Mock()
        client.login.return_value = (False, None)
        factory = Mock()
        factory.available.return_value = True
        factory.create.return_value = client
        tokens = Mock()
        tokens.login_argument.return_value = '{"di_token": "synthetic"}'
        reader = GarminRemoteReader(
            _config(),
            factory,
            Mock(),
            Mock(),
            lambda value: value,
            Mock(),
            lambda: NOW,
            lambda: date(2026, 9, 20),
            date(2000, 1, 1),
            90,
            -1,
            garmin_tokens=tokens,
        )
        with (
            patch(
                "backend.sync.garmin_service.provider_http.external_call",
                side_effect=lambda _service, _operation, call, _details, **_kwargs: (
                    call()
                ),
            ),
            patch(
                "backend.sync.garmin_service.collect_garmin_activity_detail",
                side_effect=RuntimeError("collection failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            reader.fetch_activity_detail(ACTIVITY)

        client.login.assert_called_once_with('{"di_token": "synthetic"}')
        tokens.write_back.assert_called_once_with(client, '{"di_token": "synthetic"}')


class GarminActivityDetailAssemblyTests(unittest.TestCase):
    def _configured(self, *, fixture_path: Any, remote_configured: bool) -> bool:
        control: Any = Mock(name="control")
        control.resync_gate = None
        assembly = GarminAssembly(
            dependencies=GarminAssembly.Inputs(
                provider=Mock(name="provider"),
                persistence=Mock(name="persistence"),
                telemetry=Mock(name="telemetry"),
                control=control,
            )
        )
        fixture_loader = Mock()
        fixture_loader.path.return_value = fixture_path
        reader = Mock()
        reader.configured.return_value = remote_configured
        with (
            patch.object(assembly, "fixture_loader", return_value=fixture_loader),
            patch.object(assembly, "remote_reader", return_value=reader),
        ):
            service = assembly.activity_detail_service()
        return service._configured()

    def test_fixture_mode_counts_as_not_configured(self) -> None:
        self.assertFalse(
            self._configured(fixture_path=Path("fixture.json"), remote_configured=True)
        )

    def test_remote_garmin_without_fixture_is_configured(self) -> None:
        self.assertTrue(self._configured(fixture_path=None, remote_configured=True))
        self.assertFalse(self._configured(fixture_path=None, remote_configured=False))


if __name__ == "__main__":
    unittest.main()
