from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

from backend.config import Config
from backend.db import DatabaseManager, row_factory
from backend.errors import AppError
from backend.planning import library
from backend.sync.planned_calendar import (
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)
from backend.sync.reconcile import PlannedUnitSyncStateWriter

TODAY = date(2026, 9, 20)
LOCAL_ID = "12345678-1234-5678-1234-567812345678"


class TestRedactor:
    def redact_text(self, value: str) -> str:
        return f"redacted:{value}"


class RevisionCounter:
    def __init__(self) -> None:
        self.count = 0

    def bump(self, _db) -> None:
        self.count += 1


class FakeIntervalsClient:
    def __init__(self, *, responses=None, remote_event=None, events=None) -> None:
        self.responses = list(responses or [])
        self.remote_event = remote_event
        self.events = list(events or [])
        self.upserts = []
        self.get_paths = []
        self.deleted = []
        self.collection_reads = 0
        self.collection_error = None
        self.on_collection = None
        self.on_get = None

    def upsert_calendar_events(self, events):
        self.upserts.append(events)
        result = self.responses.pop(0)
        if (
            isinstance(result, list)
            and len(result) == 1
            and isinstance(result[0], dict)
        ):
            saved = {**events[0], **result[0]}
            self.events = [
                event
                for event in self.events
                if str(event.get("id")) != str(saved["id"])
            ]
            self.events.append(saved)
        return result

    def get(self, path):
        self.get_paths.append(path)
        if self.on_get:
            return self.on_get(path)
        if isinstance(self.remote_event, Exception):
            raise self.remote_event
        return self.remote_event

    def delete_event(self, event_id):
        self.deleted.append(event_id)
        self.events = [
            event for event in self.events if str(event.get("id")) != event_id
        ]

    def get_paged_collection(self, _path, _params, _label):
        self.collection_reads += 1
        if self.on_collection:
            self.on_collection(self.collection_reads)
        if self.collection_error is not None:
            raise self.collection_error
        return list(self.events)


class PlannedCalendarSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "planned.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                "sync_dirty INTEGER NOT NULL DEFAULT 1, sync_state TEXT NOT NULL DEFAULT 'local', "
                "sync_error TEXT, sync_conflict TEXT NOT NULL DEFAULT '', external_id TEXT, "
                "baseline_hash TEXT, last_synced_at TEXT, updated_at TEXT)"
            )
        self.revisions = RevisionCounter()
        self.writer = PlannedUnitSyncStateWriter(self.revisions, TestRedactor())
        self.client = FakeIntervalsClient()
        self.factory_calls = 0
        self.config = self.config_with_key("api-key")
        self.service = self.make_service()

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def config_with_key(api_key: str) -> Config:
        return Config(
            port=8090,
            openai_api_key="",
            openai_base_url="https://api.openai.com/v1",
            openai_model="test",
            gemini_api_key="",
            gemini_model="test",
            ai_provider="",
            intervals_api_key=api_key,
            intervals_athlete_id="athlete/1",
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
            garmin_fixture_path="",
            calendar_ical_url="",
            app_password="",
            secure_cookies=False,
            data_retention_days=365,
        )

    def make_service(self, *, config=None, client=None):
        selected_client = client or self.client

        def factory():
            self.factory_calls += 1
            return selected_client

        return PlannedCalendarSyncService(
            config or self.config,
            self.manager,
            factory,
            self.writer,
            lambda: "2026-09-20T12:00:00+00:00",
            lambda: TODAY,
        )

    def make_repair_service(self, *, client=None):
        selected_client = client or self.client

        def factory():
            self.factory_calls += 1
            return selected_client

        return PlannedCalendarRepairService(
            self.config,
            self.manager,
            factory,
            self.writer,
            lambda: "2026-09-20T12:00:00+00:00",
            lambda: TODAY,
            35,
        )

    def payload_hash(self, local_id=LOCAL_ID):
        return library.library_payload_hash(self.unit(local_id)["payload"])

    @staticmethod
    def remote_event(event_id, *, external_id=None, name="Strength", **changes):
        return {
            "id": event_id,
            "external_id": external_id or f"intervals-coach-{LOCAL_ID}",
            "category": "WORKOUT",
            "start_date_local": TODAY.isoformat() + "T06:00:00",
            "name": name,
            "type": "WeightTraining",
            **changes,
        }

    @staticmethod
    def workout(**changes):
        return {
            "date": TODAY.isoformat(),
            "sport": "WeightTraining",
            "name": "Strength",
            "description": "Oberkoerperkraft: 3x8 Wiederholungen",
            "duration_minutes": 35,
            "target": "AUTO",
            **changes,
        }

    def add_unit(self, *, local_id=LOCAL_ID, payload=None, raw_payload=None):
        serialized = (
            raw_payload
            if raw_payload is not None
            else json.dumps(
                payload if payload is not None else self.workout(), ensure_ascii=False
            )
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(local_id, payload, sync_state) VALUES (?, ?, 'local')",
                (local_id, serialized),
            )

    def unit(self, local_id=LOCAL_ID):
        with self.manager.reader() as db:
            return db.execute(
                "SELECT * FROM planned_units WHERE local_id=?", (local_id,)
            ).fetchone()

    def test_invalid_uuid_missing_row_and_corrupt_payload_errors(self):
        for local_id, expected_status in (("invalid", 400), (LOCAL_ID, 404)):
            with self.subTest(local_id=local_id), self.assertRaises(AppError) as caught:
                self.service.sync_entry(local_id)
            self.assertEqual(caught.exception.status, expected_status)

        for raw_payload in ("not json", "[]"):
            with self.subTest(raw_payload=raw_payload):
                self.add_unit(raw_payload=raw_payload)
                with self.assertRaises(AppError) as caught:
                    self.service.sync_entry(LOCAL_ID)
                self.assertEqual(caught.exception.status, 500)
                self.assertEqual(
                    caught.exception.message, "Die lokale Planung ist beschädigt."
                )
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "DELETE FROM planned_units WHERE local_id=?", (LOCAL_ID,)
                    )

    def test_missing_api_key_blocks_upsert_before_client_creation(self):
        self.add_unit()
        service = self.make_service(config=self.config_with_key(""))
        with self.assertRaises(AppError) as caught:
            service.sync_entry(LOCAL_ID)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.factory_calls, 0)

        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?",
                (
                    json.dumps(self.workout(archived=True, remote_event_id="event-1")),
                    LOCAL_ID,
                ),
            )
        with self.assertRaises(AppError) as caught:
            service.sync_entry(LOCAL_ID)
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.factory_calls, 0)

    def test_create_and_retry_use_stable_external_identity(self):
        self.add_unit()
        self.client.responses = [
            [{"id": "event-1", "type": "WeightTraining"}],
            [{"id": "event-1", "type": "WeightTraining"}],
        ]
        created = self.service.sync_entry(LOCAL_ID)
        retried = self.service.sync_entry(LOCAL_ID)
        self.assertEqual(created["id"], "event-1")
        self.assertEqual(retried["id"], "event-1")
        first_payload = self.client.upserts[0][0]
        second_payload = self.client.upserts[1][0]
        self.assertEqual(first_payload["external_id"], second_payload["external_id"])
        self.assertEqual(first_payload["external_id"], f"intervals-coach-{LOCAL_ID}")
        self.assertEqual(second_payload["id"], "event-1")
        self.assertEqual(self.unit()["sync_state"], "synced")
        self.assertEqual(self.revisions.count, 2)

    def test_malformed_provider_result_is_rejected(self):
        self.add_unit()
        self.client.responses = [{"id": "wrong-shape"}]
        with self.assertRaises(AppError) as caught:
            self.service.sync_entry(LOCAL_ID)
        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(self.unit()["sync_state"], "local")

    def test_readback_validation_failure_persists_identity_and_sync_error(self):
        self.add_unit()
        self.client.responses = [[{"id": "event-1", "type": "Ride"}]]
        with self.assertRaises(AppError) as caught:
            self.service.sync_entry(LOCAL_ID)
        self.assertEqual(caught.exception.reason, "intervals_workout_sport_mismatch")
        row = self.unit()
        self.assertEqual(row["sync_state"], "sync_error")
        payload = json.loads(row["payload"])
        self.assertEqual(payload["remote_event_id"], "event-1")
        self.assertEqual(
            payload["remote_event_external_id"], f"intervals-coach-{LOCAL_ID}"
        )
        self.assertEqual(row["external_id"], f"intervals-coach-{LOCAL_ID}")

    def test_archived_or_deleted_without_remote_id_only_marks_local_sync(self):
        for flag in ("archived", "local_deleted"):
            with self.subTest(flag=flag):
                self.add_unit(payload=self.workout(**{flag: True}))
                self.assertIsNone(self.service.sync_entry(LOCAL_ID))
                self.assertEqual(self.factory_calls, 0)
                self.assertEqual(self.unit()["sync_state"], "synced")
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "DELETE FROM planned_units WHERE local_id=?", (LOCAL_ID,)
                    )

    def test_delete_success_rechecks_and_persists_removed_state(self):
        remote = {
            "id": "event-1",
            "category": "WORKOUT",
            "start_date_local": TODAY.isoformat() + "T06:00:00",
        }
        self.add_unit(payload=self.workout(archived=True, remote_event_id="event-1"))
        self.client.remote_event = remote
        self.assertIsNone(self.service.sync_entry(LOCAL_ID))
        self.assertEqual(self.client.deleted, ["event-1"])
        self.assertEqual(self.unit()["sync_state"], "synced")
        self.assertTrue(self.client.get_paths[0].endswith("/events/event-1"))

    def test_delete_404_is_already_removed(self):
        self.add_unit(
            payload=self.workout(local_deleted=True, remote_event_id="event-1")
        )
        self.client.remote_event = AppError(404, "missing")
        self.assertIsNone(self.service.sync_entry(LOCAL_ID))
        self.assertEqual(self.client.deleted, [])
        self.assertEqual(self.unit()["sync_state"], "synced")

    def test_delete_treats_http_error_404_cause_as_already_removed(self):
        self.add_unit(
            payload=self.workout(local_deleted=True, remote_event_id="event-1")
        )
        error = AppError(502, "provider wrapper error")
        error.__cause__ = HTTPError("url", 404, "missing", {}, None)
        self.client.remote_event = error
        self.assertIsNone(self.service.sync_entry(LOCAL_ID))
        self.assertEqual(self.unit()["sync_state"], "synced")

    def test_delete_identity_conflicts(self):
        variants = (
            None,
            {
                "id": "other",
                "category": "WORKOUT",
                "start_date_local": TODAY.isoformat(),
            },
            {
                "id": "event-1",
                "category": "ACTIVITY",
                "start_date_local": TODAY.isoformat(),
            },
            {"id": "event-1", "category": "WORKOUT", "start_date_local": "2026-09-19"},
            {
                "id": "event-1",
                "category": "WORKOUT",
                "start_date_local": TODAY.isoformat(),
                "paired_activity_id": 1,
            },
            {
                "id": "event-1",
                "category": "WORKOUT",
                "start_date_local": TODAY.isoformat(),
                "paired_event_id": 1,
            },
        )
        for event in variants:
            with self.subTest(event=event):
                self.add_unit(
                    payload=self.workout(archived=True, remote_event_id="event-1")
                )
                self.client.remote_event = event
                with self.assertRaises(AppError) as caught:
                    self.service.sync_entry(LOCAL_ID)
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual(
                    caught.exception.reason, "intervals_workout_identity_conflict"
                )
                self.assertEqual(self.client.deleted, [])
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "DELETE FROM planned_units WHERE local_id=?", (LOCAL_ID,)
                    )

    def test_payload_change_after_remote_read_blocks_delete(self):
        self.add_unit(payload=self.workout(archived=True, remote_event_id="event-1"))
        self.client.remote_event = {
            "id": "event-1",
            "category": "WORKOUT",
            "start_date_local": TODAY.isoformat() + "T06:00:00",
        }

        def change_payload(_path):
            with self.manager.unit_of_work() as db:
                db.execute(
                    "UPDATE planned_units SET payload=? WHERE local_id=?",
                    (
                        json.dumps(
                            self.workout(
                                archived=True, name="changed", remote_event_id="event-1"
                            )
                        ),
                        LOCAL_ID,
                    ),
                )
            return self.client.remote_event

        self.client.on_get = change_payload
        with self.assertRaises(AppError) as caught:
            self.service.sync_entry(LOCAL_ID)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "planning_revision_conflict")
        self.assertEqual(self.client.deleted, [])

    def test_same_id_concurrency_rejected_and_guard_cleans_up(self):
        self.add_unit()
        entered = threading.Event()
        release = threading.Event()
        calls = 0

        def blocking_upsert(_events):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                self.assertTrue(release.wait(timeout=5))
            return [{"id": f"event-{calls}", "type": "WeightTraining"}]

        self.client.upsert_calendar_events = blocking_upsert
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(self.service.sync_entry, LOCAL_ID)
            self.assertTrue(entered.wait(timeout=5))
            with self.assertRaises(AppError) as caught:
                self.service.sync_entry(LOCAL_ID)
            self.assertEqual(caught.exception.reason, "planned_unit_sync_running")
            release.set()
        self.assertEqual(first.result(timeout=5)["id"], "event-1")
        self.assertEqual(self.service.sync_entry(LOCAL_ID)["id"], "event-2")

    def test_different_ids_can_push_concurrently(self):
        other_id = "87654321-4321-8765-4321-876543218765"
        self.add_unit()
        self.add_unit(local_id=other_id)
        both_inside_provider = threading.Barrier(2)
        counter_lock = threading.Lock()
        calls = 0

        def synchronized_upsert(_events):
            nonlocal calls
            with counter_lock:
                calls += 1
                event_id = f"event-{calls}"
            both_inside_provider.wait(timeout=5)
            return [{"id": event_id, "type": "WeightTraining"}]

        self.client.upsert_calendar_events = synchronized_upsert
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.service.sync_entry, LOCAL_ID)
            second = executor.submit(self.service.sync_entry, other_id)
            self.assertTrue(first.result(timeout=5)["id"].startswith("event-"))
        self.assertTrue(second.result(timeout=5)["id"].startswith("event-"))
        self.assertEqual(calls, 2)

    def test_repair_create_update_and_remove(self):
        service = self.make_repair_service()
        self.add_unit()
        self.client.responses = [[self.remote_event("event-1")]]
        result = service.repair_entry(LOCAL_ID, self.payload_hash())
        self.assertEqual(result["id"], "event-1")
        self.assertEqual(self.client.collection_reads, 2)
        self.assertEqual(self.unit()["sync_state"], "synced")
        self.assertEqual(
            json.loads(self.unit()["payload"])["remote_event_id"], "event-1"
        )

        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?",
                (
                    json.dumps(
                        self.workout(name="Strength updated", remote_event_id="event-1")
                    ),
                    LOCAL_ID,
                ),
            )
        self.client.events = [self.remote_event("event-1", name="Strength")]
        self.client.responses = [
            [self.remote_event("event-1", name="Strength updated")]
        ]
        result = service.repair_entry(LOCAL_ID, self.payload_hash())
        self.assertEqual(result["name"], "Strength updated")
        self.assertEqual(self.client.upserts[-1][0]["id"], "event-1")
        self.assertEqual(self.client.deleted, [])

        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id=?",
                (
                    json.dumps(self.workout(archived=True, remote_event_id="event-1")),
                    LOCAL_ID,
                ),
            )
        self.client.events = [self.remote_event("event-1", name="Strength")]
        upserts_before_remove = len(self.client.upserts)
        self.assertIsNone(service.repair_entry(LOCAL_ID, self.payload_hash()))
        self.assertEqual(len(self.client.upserts), upserts_before_remove)
        self.assertEqual(self.client.deleted, ["event-1"])
        self.assertEqual(self.unit()["sync_state"], "synced")

    def test_repair_hash_conflict_before_write(self):
        self.add_unit()
        service = self.make_repair_service()
        expected_hash = self.payload_hash()

        def change_after_snapshot(_read_number):
            with self.manager.unit_of_work() as db:
                db.execute(
                    "UPDATE planned_units SET payload=? WHERE local_id=?",
                    (json.dumps(self.workout(name="Changed")), LOCAL_ID),
                )

        self.client.on_collection = change_after_snapshot
        with self.assertRaises(AppError) as caught:
            service.repair_entry(LOCAL_ID, expected_hash)
        self.assertEqual(caught.exception.reason, "planning_revision_conflict")
        self.assertEqual(self.client.upserts, [])

    def test_repair_hash_conflict_before_final_persist_preserves_written_remote_id(
        self,
    ):
        self.add_unit()
        service = self.make_repair_service()
        expected_hash = self.payload_hash()
        self.client.responses = [[self.remote_event("event-1")]]

        def change_after_write(read_number):
            if read_number == 2:
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "UPDATE planned_units SET payload=? WHERE local_id=?",
                        (
                            json.dumps(
                                self.workout(name="Changed", remote_event_id="event-1")
                            ),
                            LOCAL_ID,
                        ),
                    )

        self.client.on_collection = change_after_write
        with self.assertRaises(AppError) as caught:
            service.repair_entry(LOCAL_ID, expected_hash)
        self.assertEqual(caught.exception.reason, "planning_revision_conflict")
        self.assertEqual(
            caught.exception.message,
            "Die Planung wurde waehrend der Reparatur geaendert. Bitte erneut abgleichen.",
        )
        self.assertEqual(
            json.loads(self.unit()["payload"])["remote_event_id"], "event-1"
        )
        self.assertEqual(self.unit()["sync_state"], "syncing")

    def test_repair_rejects_invalid_paired_foreign_and_ambiguous_events(self):
        service = self.make_repair_service()
        invalid_variants = (
            {"category": "ACTIVITY"},
            {"start_date_local": "2026-09-19T06:00:00"},
            {"paired_activity_id": "activity-1"},
            {"paired_event_id": "event-pair"},
        )
        for changes in invalid_variants:
            with self.subTest(changes=changes):
                self.add_unit()
                self.client.events = [self.remote_event("event-1", **changes)]
                with self.assertRaises(AppError) as caught:
                    service.repair_entry(LOCAL_ID, self.payload_hash())
                self.assertEqual(
                    caught.exception.reason, "intervals_workout_identity_conflict"
                )
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "DELETE FROM planned_units WHERE local_id=?", (LOCAL_ID,)
                    )

        other_id = "87654321-4321-8765-4321-876543218765"
        self.add_unit()
        self.add_unit(
            local_id=other_id, payload=self.workout(remote_event_id="foreign-event")
        )
        self.client.events = [self.remote_event("foreign-event")]
        with self.assertRaises(AppError) as caught:
            service.repair_entry(LOCAL_ID, self.payload_hash())
        self.assertEqual(caught.exception.reason, "intervals_workout_identity_conflict")
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM planned_units WHERE local_id=?", (LOCAL_ID,))
            db.execute("DELETE FROM planned_units WHERE local_id=?", (other_id,))

        self.add_unit()
        self.client.events = [
            self.remote_event("unlinked-event", external_id="unrelated-external-id")
        ]
        with self.assertRaises(AppError) as caught:
            service.repair_entry(LOCAL_ID, self.payload_hash())
        self.assertEqual(
            caught.exception.reason, "intervals_workout_identity_ambiguous"
        )

    def test_repair_deletes_only_identity_checked_duplicates(self):
        self.add_unit(payload=self.workout(remote_event_id="event-1"))
        self.client.events = [
            self.remote_event("event-1"),
            self.remote_event("event-2"),
        ]
        self.client.responses = [[self.remote_event("event-1")]]
        service = self.make_repair_service()
        service.repair_entry(LOCAL_ID, self.payload_hash())
        self.assertEqual(self.client.deleted, ["event-2"])
        self.assertEqual([event["id"] for event in self.client.events], ["event-1"])

    def test_repair_readback_failure_keeps_remote_identity(self):
        self.add_unit()
        self.client.responses = [[self.remote_event("event-1", type="Ride")]]
        service = self.make_repair_service()
        with self.assertRaises(AppError) as caught:
            service.repair_entry(LOCAL_ID, self.payload_hash())
        self.assertEqual(caught.exception.reason, "intervals_workout_sport_mismatch")
        self.assertEqual(self.unit()["sync_state"], "syncing")
        self.assertEqual(
            json.loads(self.unit()["payload"])["remote_event_id"], "event-1"
        )

    def test_repair_batch_shares_two_reads_and_deferred_verification(self):
        other_id = "87654321-4321-8765-4321-876543218765"
        self.add_unit()
        self.add_unit(local_id=other_id, payload=self.workout(name="Other"))
        self.client.responses = [
            [self.remote_event("event-1")],
            [
                self.remote_event(
                    "event-2", external_id=f"intervals-coach-{other_id}", name="Other"
                )
            ],
        ]
        service = self.make_repair_service()
        batch = service.create_batch(
            [{"library_workout_id": LOCAL_ID}, {"library_workout_id": other_id}]
        )
        self.assertIsNone(
            service.repair_entry(LOCAL_ID, self.payload_hash(), batch=batch)
        )
        self.assertIsNone(
            service.repair_entry(other_id, self.payload_hash(other_id), batch=batch)
        )
        self.assertEqual(self.client.collection_reads, 1)
        self.assertEqual(batch.verify(), {LOCAL_ID: None, other_id: None})
        self.assertEqual(self.client.collection_reads, 2)
        self.assertEqual(self.unit()["sync_state"], "synced")
        self.assertEqual(self.unit(other_id)["sync_state"], "synced")

    def test_repair_batch_raises_for_non_dict_and_skips_events_without_ids(self):
        service = self.make_repair_service()
        for malformed in (None, "not-an-event"):
            with self.subTest(malformed=malformed):
                self.add_unit()
                self.client.events = [malformed]
                batch = service.create_batch([{"library_workout_id": LOCAL_ID}])
                with self.assertRaises(AttributeError):
                    service.repair_entry(LOCAL_ID, self.payload_hash(), batch=batch)
                self.assertEqual(self.client.upserts, [])
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "DELETE FROM planned_units WHERE local_id=?", (LOCAL_ID,)
                    )

        for event_without_id in ({}, {"id": None}, {"id": ""}):
            with self.subTest(event_without_id=event_without_id):
                self.add_unit()
                self.client.events = [event_without_id]
                self.client.responses = [[self.remote_event("event-1")]]
                batch = service.create_batch([{"library_workout_id": LOCAL_ID}])
                service.repair_entry(LOCAL_ID, self.payload_hash(), batch=batch)
                self.assertEqual(batch.events["event-1"]["id"], "event-1")
                with self.manager.unit_of_work() as db:
                    db.execute(
                        "DELETE FROM planned_units WHERE local_id=?", (LOCAL_ID,)
                    )

    def test_repair_batch_reads_remote_collection_each_time_verify_runs(self):
        self.add_unit()
        service = self.make_repair_service()
        batch = service.create_batch([{"library_workout_id": LOCAL_ID}])
        self.client.responses = [[self.remote_event("event-1")]]
        service.repair_entry(LOCAL_ID, self.payload_hash(), batch=batch)

        self.assertEqual(batch.verify(), {LOCAL_ID: None})
        self.assertEqual(self.client.collection_reads, 2)
        second_outcome = batch.verify()[LOCAL_ID]
        self.assertIsInstance(second_outcome, AppError)
        self.assertEqual(second_outcome.reason, "planning_revision_conflict")
        self.assertEqual(self.client.collection_reads, 3)

    def test_repair_preserves_requested_external_id_from_provider_response(self):
        self.add_unit()
        service = self.make_repair_service()
        batch = service.create_batch([{"library_workout_id": LOCAL_ID}])
        self.client.responses = [
            [self.remote_event("event-1", external_id="provider-returned-foreign-id")]
        ]

        service.repair_entry(LOCAL_ID, self.payload_hash(), batch=batch)

        expected_external_id = f"intervals-coach-{LOCAL_ID}"
        self.assertEqual(
            json.loads(self.unit()["payload"])["remote_event_external_id"],
            expected_external_id,
        )
        self.assertEqual(batch.events["event-1"]["external_id"], expected_external_id)

    def test_repair_batch_verify_failure_and_collection_error_are_propagated(self):
        self.add_unit()
        service = self.make_repair_service()
        batch = service.create_batch([{"library_workout_id": LOCAL_ID}])
        self.client.responses = [[self.remote_event("event-1")]]
        service.repair_entry(LOCAL_ID, self.payload_hash(), batch=batch)
        self.client.events.clear()
        outcome = batch.verify()[LOCAL_ID]
        self.assertIsInstance(outcome, AppError)
        self.assertEqual(outcome.reason, "intervals_workout_verification_failed")

        second_id = "87654321-4321-8765-4321-876543218765"
        self.add_unit(local_id=second_id)
        error = RuntimeError("provider unavailable")
        self.client.collection_error = error
        failed_batch = service.create_batch([{"library_workout_id": second_id}])
        for _ in range(2):
            with self.assertRaises(RuntimeError) as caught:
                service.repair_entry(
                    second_id, self.payload_hash(second_id), batch=failed_batch
                )
            self.assertIs(caught.exception, error)
        self.assertEqual(self.client.collection_reads, 3)

    def test_repair_provider_write_failure_propagates(self):
        self.add_unit()
        failure = RuntimeError("write failed")

        def fail_write(_events):
            raise failure

        self.client.upsert_calendar_events = fail_write
        service = self.make_repair_service()
        with self.assertRaises(RuntimeError) as caught:
            service.repair_entry(LOCAL_ID, self.payload_hash())
        self.assertIs(caught.exception, failure)

    def test_repair_error_persistence_uses_shared_state_writer(self):
        self.add_unit()
        service = self.make_repair_service()

        self.assertTrue(service.record_error(LOCAL_ID, "synthetic failure"))

        unit = self.unit()
        self.assertEqual(unit["sync_state"], "sync_error")
        self.assertEqual(unit["sync_error"], "redacted:synthetic failure")
        self.assertEqual(json.loads(unit["payload"])["sync_status"], "sync_error")

    def test_repair_and_normal_sync_share_per_id_guard(self):
        self.add_unit()
        entered = threading.Event()
        release = threading.Event()

        def blocking_upsert(_events):
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return [{"id": "event-1", "type": "WeightTraining"}]

        self.client.upsert_calendar_events = blocking_upsert
        with ThreadPoolExecutor(max_workers=1) as executor:
            normal_sync = executor.submit(self.service.sync_entry, LOCAL_ID)
            self.assertTrue(entered.wait(timeout=5))
            repair = self.make_repair_service()
            with self.assertRaises(AppError) as caught:
                repair.repair_entry(LOCAL_ID, self.payload_hash())
            self.assertEqual(caught.exception.reason, "planned_unit_sync_running")
            release.set()
        self.assertEqual(normal_sync.result(timeout=5)["id"], "event-1")


if __name__ == "__main__":
    unittest.main()
