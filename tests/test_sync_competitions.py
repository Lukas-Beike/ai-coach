from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import CompetitionRepository, KeyValueRepository
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.planning import competitions as planning_competitions
from backend.planning.competition_service import CompetitionService
from backend.sync.competitions import CompetitionSyncReconciler, CompetitionSyncService

NOW = "2026-09-20T12:00:00+00:00"
IMPORT_ID = "00000000-0000-0000-0000-000000000099"


class CountingDatabaseManager:
    def __init__(self, manager):
        self.manager = manager
        self.unit_of_work_calls = 0

    def reader(self):
        return self.manager.reader()

    def unit_of_work(self):
        self.unit_of_work_calls += 1
        return self.manager.unit_of_work()


class FakeLock:
    def __init__(self, locked=False):
        self.locked = locked
        self.acquire_calls = []
        self.release_calls = 0

    def acquire(self, blocking=False):
        self.acquire_calls.append(blocking)
        if self.locked:
            return False
        self.locked = True
        return True

    def release(self):
        self.release_calls += 1
        self.locked = False


class FakeCompetitionClient:
    def __init__(self, events=None, pushed=None, fetch_error=None):
        self.events = events or []
        self.pushed = pushed or []
        self.fetch_error = fetch_error
        self.delete_calls = []
        self.upsert_calls = []

    def fetch_competition_events(self):
        if self.fetch_error:
            raise self.fetch_error
        return self.events

    def bulk_delete_events(self, identifiers):
        self.delete_calls.append(copy.deepcopy(identifiers))

    def upsert_competition_events(self, events):
        self.upsert_calls.append(copy.deepcopy(events))
        return copy.deepcopy(self.pushed)


class FakeRedactor:
    def redact_text(self, text):
        return text.replace("secret-token", "[REDACTED]")


class FakeLogger:
    def __init__(self):
        self.exceptions = []

    def exception(self, message, **kwargs):
        self.exceptions.append((message, kwargs))


class FakePublisher:
    def __init__(self):
        self.events = []

    def publish(self, channel, payload):
        self.events.append((channel, copy.deepcopy(payload)))


class CompetitionSyncReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        raw_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "competitions.db",
            sqlite3,
            row_factory=row_factory,
        )
        self.database_manager = CountingDatabaseManager(raw_manager)
        self.reconciler = CompetitionSyncReconciler(
            self.database_manager, lambda: IMPORT_ID
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE competitions ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, event_date TEXT NOT NULL, "
                "sport TEXT NOT NULL, priority TEXT NOT NULL, distance TEXT NOT NULL, "
                "target TEXT NOT NULL, course_profile TEXT NOT NULL, notes TEXT NOT NULL, "
                "category TEXT NOT NULL DEFAULT 'RACE_B', start_date_local TEXT, "
                "description TEXT NOT NULL DEFAULT '', moving_time INTEGER, intervals_event_id TEXT, "
                "external_id TEXT, sync_dirty INTEGER NOT NULL DEFAULT 1, "
                "sync_state TEXT NOT NULL DEFAULT 'local', sync_conflict TEXT NOT NULL DEFAULT '', "
                "last_synced_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE competition_sync_tombstones ("
                "id TEXT PRIMARY KEY, intervals_event_id TEXT, external_id TEXT, "
                "created_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        self.database_manager.unit_of_work_calls = 0
        self.key_value_repository = KeyValueRepository(lambda: NOW)

    def tearDown(self):
        self.database_manager.manager.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def local_competition(
        local_id="local-1",
        *,
        name="Gran Fondo",
        event_date="2026-10-01",
        sport="Ride",
        intervals_event_id=None,
        external_id=None,
        sync_dirty=1,
        sync_state="local",
    ):
        return {
            "id": local_id,
            "name": name,
            "event_date": event_date,
            "sport": sport,
            "priority": "B",
            "distance": "100000",
            "target": "",
            "course_profile": "",
            "notes": "",
            "category": "RACE_B",
            "start_date_local": f"{event_date}T00:00:00",
            "description": "Local description",
            "moving_time": None,
            "intervals_event_id": intervals_event_id,
            "external_id": external_id,
            "sync_dirty": sync_dirty,
            "sync_state": sync_state,
            "sync_conflict": "",
            "last_synced_at": None,
            "created_at": "created",
            "updated_at": "updated",
        }

    @staticmethod
    def remote_event(
        remote_id,
        external_id,
        *,
        name="Gran Fondo",
        event_date="2026-10-01",
        description="Remote description",
    ):
        return {
            "id": remote_id,
            "external_id": external_id,
            "name": name,
            "start_date_local": f"{event_date}T08:00:00",
            "type": "Ride",
            "category": "RACE_B",
            "distance": 100000,
            "moving_time": 14400,
            "target": "finish",
            "description": description,
        }

    def insert_competition(self, row):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competitions(id, name, event_date, sport, priority, distance, target, "
                "course_profile, notes, category, start_date_local, description, moving_time, "
                "intervals_event_id, external_id, sync_dirty, sync_state, sync_conflict, "
                "last_synced_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row[key] for key in self.local_competition()),
            )

    def insert_tombstone(
        self, tombstone_id, intervals_event_id, external_id, created_at
    ):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competition_sync_tombstones(id, intervals_event_id, external_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (tombstone_id, intervals_event_id, external_id, created_at),
            )

    def stored_competition(self, local_id):
        with self.database_manager.manager.reader() as db:
            return db.execute(
                "SELECT * FROM competitions WHERE id=?", (local_id,)
            ).fetchone()

    def stored_kv(self, key):
        with self.database_manager.manager.reader() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def make_sync_service(
        self,
        client,
        *,
        api_key="intervals-key",
        reconciler=None,
        lock=None,
        key_value_repository=None,
        publisher=None,
        logger=None,
    ):
        return CompetitionSyncService(
            SimpleNamespace(intervals_api_key=api_key),
            lambda: client,
            reconciler or self.reconciler,
            CompetitionService(
                self.database_manager, CompetitionRepository(), lambda: NOW
            ),
            self.database_manager,
            key_value_repository or self.key_value_repository,
            publisher or SimpleNamespace(publish=lambda *args: None),
            FakeRedactor(),
            logger or FakeLogger(),
            lambda: NOW,
            lock,
        )

    def sync_plan(self, local_rows, remote_events, tombstones=None):
        return planning_competitions.competition_sync_plan(
            local_rows, tombstones or [], remote_events
        )

    def test_records_returns_ordered_tombstones_and_local_rows(self):
        self.insert_competition(
            self.local_competition("later", event_date="2026-10-03")
        )
        self.insert_competition(
            self.local_competition("first", event_date="2026-09-30")
        )
        self.insert_tombstone("second", "remote-2", None, "2026-02")
        self.insert_tombstone("first", "remote-1", None, "2026-01")

        tombstones, local_rows = self.reconciler.records()

        self.assertEqual([row["id"] for row in tombstones], ["first", "second"])
        self.assertEqual([row["id"] for row in local_rows], ["first", "later"])

    def test_clear_tombstones_requires_matching_id_and_created_at(self):
        self.insert_tombstone("same-id", "remote-old", None, "old")
        self.insert_tombstone("exact", "remote-exact", None, "exact-time")
        self.insert_tombstone("other", "remote-other", None, "other-time")

        removed = self.reconciler.clear_tombstones(
            [
                {"id": "same-id", "created_at": "new"},
                {"id": "exact", "created_at": "exact-time"},
            ]
        )

        self.assertEqual(removed, 1)
        tombstones, _ = self.reconciler.records()
        self.assertEqual(
            {(row["id"], row["created_at"]) for row in tombstones},
            {("same-id", "old"), ("other", "other-time")},
        )

    def test_dirty_remote_deviations_persist_identity_changed_and_missing_conflicts(
        self,
    ):
        identity = self.local_competition("identity")
        changed = self.local_competition(
            "changed",
            name="Local Edited",
            intervals_event_id="remote-changed",
            external_id="external-changed",
        )
        missing = self.local_competition(
            "missing",
            intervals_event_id="remote-missing",
            external_id="external-missing",
        )
        for row in (identity, changed, missing):
            self.insert_competition(row)
        remote_events = [
            self.remote_event("remote-identity", "external-identity"),
            self.remote_event("remote-changed", "external-changed", name="Remote Edit"),
        ]
        plan = self.sync_plan([identity, changed, missing], remote_events)
        self.database_manager.unit_of_work_calls = 0

        result = self.reconciler.reconcile(
            plan, [], [], [identity, changed, missing], push_local=False, now=NOW
        )

        self.assertEqual(result["conflicts"], 3)
        expected = {
            "identity": "identity_only",
            "changed": "remote_changed",
            "missing": "remote_missing",
        }
        for local_id, conflict_type in expected.items():
            row = self.stored_competition(local_id)
            self.assertEqual(row["sync_state"], "conflict")
            self.assertEqual(row["updated_at"], NOW)
            self.assertEqual(json.loads(row["sync_conflict"])["type"], conflict_type)
        self.assertEqual(self.database_manager.unit_of_work_calls, 1)

    def test_push_marks_dirty_row_synced_only_after_readback_or_push_result(self):
        row = self.local_competition("local-push")
        self.insert_competition(row)
        plan = self.sync_plan([row], [])

        first = self.reconciler.reconcile(plan, [], [], [row], push_local=True, now=NOW)

        self.assertEqual(first["conflicts"], 0)
        self.assertEqual(self.stored_competition("local-push")["sync_dirty"], 1)
        self.assertIsNone(self.stored_competition("local-push")["intervals_event_id"])
        self.assertIsNone(self.stored_competition("local-push")["external_id"])

        pushed = self.remote_event(
            "remote-created",
            planning_competitions.competition_external_id("local-push"),
        )
        second = self.reconciler.reconcile(
            plan, [pushed], [], [row], push_local=True, now=NOW
        )

        stored = self.stored_competition("local-push")
        self.assertEqual(stored["sync_dirty"], 0)
        self.assertEqual(stored["sync_state"], "synced")
        self.assertEqual(stored["intervals_event_id"], "remote-created")
        self.assertEqual(stored["external_id"], pushed["external_id"])
        self.assertEqual(second["remote_events"], [pushed])

    def test_synced_local_row_is_updated_from_remote(self):
        row = self.local_competition(
            "local-clean",
            intervals_event_id="remote-clean",
            external_id="external-clean",
            sync_dirty=0,
            sync_state="synced",
        )
        self.insert_competition(row)
        remote = self.remote_event(
            "remote-clean",
            "external-clean",
            name="Remote Name",
            description="Remote details",
        )
        plan = self.sync_plan([row], [remote])

        result = self.reconciler.reconcile(
            plan, [], [], [row], push_local=False, now=NOW
        )

        stored = self.stored_competition("local-clean")
        self.assertEqual(result["updated"], 1)
        self.assertEqual(stored["name"], "Remote Name")
        self.assertEqual(stored["description"], "Remote details")
        self.assertEqual(stored["moving_time"], 14400)
        self.assertEqual(stored["last_synced_at"], NOW)

    def test_optimistic_check_skips_competition_edited_after_capture(self):
        captured = self.local_competition(
            "local-edit",
            intervals_event_id="remote-edit",
            external_id="external-edit",
            sync_dirty=0,
        )
        self.insert_competition(captured)
        remote = self.remote_event("remote-edit", "external-edit", name="Remote Name")
        plan = self.sync_plan([captured], [remote])
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET name='New local name', sync_dirty=1 WHERE id=?",
                (captured["id"],),
            )

        result = self.reconciler.reconcile(
            plan, [], [], [captured], push_local=False, now=NOW
        )

        stored = self.stored_competition("local-edit")
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(stored["name"], "New local name")
        self.assertEqual(stored["sync_dirty"], 1)

    def test_remote_import_respects_tombstones_limit_and_does_not_mutate_inputs(self):
        for index in range(19):
            self.insert_competition(
                self.local_competition(
                    f"existing-{index}",
                    name=f"Existing {index}",
                    event_date=f"2026-11-{index + 1:02d}",
                    sync_dirty=0,
                    sync_state="synced",
                )
            )
        self.insert_tombstone("stored-tombstone", "suppressed-db", None, "stored")
        tombstones = [
            {
                "id": "captured-tombstone",
                "intervals_event_id": "suppressed-input",
                "external_id": None,
                "created_at": "captured",
            }
        ]
        local_rows = self.reconciler.records()[1]
        remote_events = [
            self.remote_event("suppressed-input", "external-input"),
            self.remote_event("suppressed-db", "external-db"),
            self.remote_event(
                "import-1", "external-1", name="Imported One", event_date="2026-12-01"
            ),
            self.remote_event(
                "import-2", "external-2", name="Imported Two", event_date="2026-12-02"
            ),
        ]
        plan = self.sync_plan(local_rows, remote_events, tombstones)
        plan_before = copy.deepcopy(plan)
        pushed = []
        pushed_before = copy.deepcopy(pushed)
        tombstones_before = copy.deepcopy(tombstones)
        rows_before = copy.deepcopy(local_rows)

        result = self.reconciler.reconcile(
            plan,
            pushed,
            tombstones,
            local_rows,
            push_local=False,
            now=NOW,
        )

        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(result["remote_events"]), 4)
        self.assertEqual(plan, plan_before)
        self.assertEqual(pushed, pushed_before)
        self.assertEqual(tombstones, tombstones_before)
        self.assertEqual(local_rows, rows_before)
        with self.database_manager.manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS count FROM competitions").fetchone()[
                    "count"
                ],
                20,
            )
            self.assertIsNone(
                db.execute(
                    "SELECT id FROM competitions WHERE intervals_event_id IN (?, ?)",
                    ("suppressed-input", "suppressed-db"),
                ).fetchone()
            )
            self.assertEqual(
                db.execute(
                    "SELECT id FROM competitions WHERE intervals_event_id='import-1'"
                ).fetchone()["id"],
                IMPORT_ID,
            )
            self.assertIsNone(
                db.execute(
                    "SELECT id FROM competitions WHERE intervals_event_id='import-2'"
                ).fetchone()
            )

    def test_sync_requires_configured_intervals_key_before_lock_or_client(self):
        lock = FakeLock()
        service = self.make_sync_service(FakeCompetitionClient(), api_key="", lock=lock)

        with self.assertRaises(AppError) as raised:
            service.sync()

        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(raised.exception.message, INTERVALS_API_KEY_ERROR)
        self.assertEqual(lock.acquire_calls, [])

    def test_sync_returns_already_running_without_side_effects(self):
        lock = FakeLock(locked=True)
        service = self.make_sync_service(FakeCompetitionClient(), lock=lock)

        result = service.sync()

        self.assertEqual(result, {"status": "already_running"})
        self.assertEqual(lock.acquire_calls, [False])
        self.assertEqual(lock.release_calls, 0)
        self.assertIsNone(self.stored_kv("competition_sync_running"))

    def test_service_instances_share_default_competition_lock(self):
        first = self.make_sync_service(FakeCompetitionClient())
        second = self.make_sync_service(FakeCompetitionClient())
        shared_lock = first._competition_lock

        self.assertIs(second._competition_lock, shared_lock)
        self.assertTrue(shared_lock.acquire(blocking=False))
        try:
            self.assertEqual(second.sync(), {"status": "already_running"})
        finally:
            shared_lock.release()

    def test_read_only_sync_never_deletes_or_upserts_and_keeps_tombstones(self):
        row = self.local_competition("local-read-only")
        self.insert_competition(row)
        self.insert_tombstone("tombstone", "remote-delete", None, "created")
        client = FakeCompetitionClient()
        service = self.make_sync_service(client)

        result = service.sync(push_local=False)

        self.assertEqual(client.delete_calls, [])
        self.assertEqual(client.upsert_calls, [])
        self.assertEqual(result["pushed"], 0)
        self.assertEqual(result["deleted_remote"], 0)
        tombstones, _ = self.reconciler.records()
        self.assertEqual([row["id"] for row in tombstones], ["tombstone"])

    def test_authorized_sync_deletes_tombstones_and_upserts_outbound(self):
        row = self.local_competition("local-push")
        self.insert_competition(row)
        self.insert_tombstone("tombstone", "remote-delete", None, "created")
        remote = self.remote_event(
            "remote-created",
            planning_competitions.competition_external_id("local-push"),
        )
        client = FakeCompetitionClient(pushed=[remote])
        service = self.make_sync_service(client)

        result = service.sync(push_local=True)

        self.assertEqual(client.delete_calls, [[{"id": "remote-delete"}]])
        self.assertEqual(len(client.upsert_calls), 1)
        self.assertEqual(len(client.upsert_calls[0]), 1)
        self.assertEqual(result["pushed"], 1)
        self.assertEqual(result["deleted_remote"], 1)
        self.assertEqual(self.reconciler.records()[0], [])
        self.assertEqual(self.stored_competition("local-push")["sync_state"], "synced")

    def test_failed_remote_delete_does_not_clear_tombstones_or_upsert(self):
        self.insert_tombstone("tombstone", "remote-delete", None, "created")
        error = RuntimeError("delete failed")
        client = FakeCompetitionClient()

        def fail_delete(identifiers):
            client.delete_calls.append(copy.deepcopy(identifiers))
            raise error

        client.bulk_delete_events = fail_delete
        service = self.make_sync_service(client)

        with self.assertRaises(RuntimeError) as raised:
            service.sync(push_local=True)

        self.assertIs(raised.exception, error)
        self.assertEqual(self.reconciler.records()[0][0]["id"], "tombstone")
        self.assertEqual(client.upsert_calls, [])

    def test_remote_filter_keeps_linked_ids_and_rejects_other_events(self):
        row = self.local_competition(
            "local-linked",
            intervals_event_id="linked-id",
            external_id="linked-external",
            sync_dirty=0,
            sync_state="synced",
        )
        self.insert_competition(row)
        linked = self.remote_event("linked-id", "", name="Linked", description="")
        linked["category"] = "OTHER"
        unlinked = self.remote_event("unlinked-id", "", name="Unlinked")
        unlinked["category"] = "OTHER"
        unsupported = self.remote_event(
            "unsupported-id", "external-unsupported", name="Unsupported"
        )
        unsupported["type"] = "Swim"
        client = FakeCompetitionClient(events=[linked, unlinked, unsupported])
        service = self.make_sync_service(client)

        with patch.object(
            self.reconciler, "reconcile", wraps=self.reconciler.reconcile
        ) as reconcile:
            service.sync()

        plan = reconcile.call_args.args[0]
        self.assertEqual(plan["remote_events"], [linked])

    def test_success_result_status_values_and_coach_event(self):
        row = self.local_competition(
            "local-clean",
            intervals_event_id="remote-clean",
            external_id="external-clean",
            sync_dirty=0,
            sync_state="synced",
        )
        self.insert_competition(row)
        publisher = FakePublisher()
        client = FakeCompetitionClient(
            events=[
                self.remote_event(
                    "remote-clean", "external-clean", name="Updated remotely"
                )
            ]
        )
        service = self.make_sync_service(client, publisher=publisher)

        result = service.sync(reason="scheduled")

        self.assertEqual(
            result,
            {
                "status": "ok",
                "synced_at": NOW,
                "imported": 0,
                "updated": 1,
                "pushed": 0,
                "skipped": 0,
                "conflicts": 0,
                "removed": 0,
                "deleted_remote": 0,
                "total": 1,
            },
        )
        self.assertEqual(self.stored_kv("last_competition_sync_at"), NOW)
        self.assertEqual(self.stored_kv("last_competition_sync_error"), "")
        self.assertEqual(self.stored_kv("competition_sync_running"), "0")
        self.assertEqual(self.stored_kv("competition_sync_status"), "")
        self.assertEqual(publisher.events, [("coach", {"status": "changed"})])

    def test_provider_failure_redacts_error_and_releases_lock_after_cleanup(self):
        error = RuntimeError("provider failed with secret-token" + "x" * 1200)
        client = FakeCompetitionClient(fetch_error=error)
        lock = FakeLock()
        logger = FakeLogger()
        service = self.make_sync_service(client, lock=lock, logger=logger)

        with self.assertRaises(RuntimeError) as raised:
            service.sync(reason="manual")

        self.assertIs(raised.exception, error)
        stored_error = self.stored_kv("last_competition_sync_error")
        self.assertEqual(len(stored_error), 1000)
        self.assertTrue(stored_error.startswith("provider failed with [REDACTED]"))
        self.assertEqual(self.stored_kv("competition_sync_running"), "0")
        self.assertEqual(self.stored_kv("competition_sync_status"), "")
        self.assertEqual(lock.release_calls, 1)
        self.assertEqual(
            logger.exceptions[0][1]["extra"]["context"], {"reason": "manual"}
        )

    def test_reconcile_and_cleanup_failures_release_lock_and_cleanup_error_is_visible(
        self,
    ):
        client = FakeCompetitionClient()
        lock = FakeLock()
        logger = FakeLogger()
        service = self.make_sync_service(client, lock=lock, logger=logger)
        error = RuntimeError("reconciliation failed")
        original_set = self.key_value_repository.set

        def fail_running_reset(db, key, value):
            if key == "competition_sync_running" and value == "0":
                raise sqlite3.OperationalError("cleanup unavailable")
            return original_set(db, key, value)

        with (
            patch.object(self.reconciler, "reconcile", side_effect=error),
            patch.object(
                self.key_value_repository, "set", side_effect=fail_running_reset
            ),
            self.assertRaises(sqlite3.OperationalError) as raised,
        ):
            service.sync()

        self.assertEqual(str(raised.exception), "cleanup unavailable")
        self.assertEqual(
            self.stored_kv("last_competition_sync_error"), "reconciliation failed"
        )
        self.assertEqual(
            self.stored_kv("competition_sync_status"),
            "Zielwettkämpfe werden synchronisiert…",
        )
        self.assertEqual(logger.exceptions[0][0], "Competition synchronization failed")
        self.assertEqual(logger.exceptions[0][1]["exc_info"], True)
        self.assertEqual(lock.release_calls, 1)

    def test_cleanup_error_after_success_is_visible_and_releases_lock(self):
        lock = FakeLock()
        service = self.make_sync_service(FakeCompetitionClient(), lock=lock)
        original_set = self.key_value_repository.set

        def fail_running_reset(db, key, value):
            if key == "competition_sync_running" and value == "0":
                raise sqlite3.OperationalError("cleanup unavailable")
            return original_set(db, key, value)

        with (
            patch.object(
                self.key_value_repository, "set", side_effect=fail_running_reset
            ),
            self.assertRaises(sqlite3.OperationalError) as raised,
        ):
            service.sync()

        self.assertEqual(str(raised.exception), "cleanup unavailable")
        self.assertEqual(lock.release_calls, 1)
        self.assertEqual(self.stored_kv("competition_sync_running"), "1")
        self.assertEqual(
            self.stored_kv("competition_sync_status"),
            "Zielwettkämpfe werden synchronisiert…",
        )


if __name__ == "__main__":
    unittest.main()
