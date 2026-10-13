"""Workout-library synchronization driven through the WorkoutLibraryExportPort.

The orchestration tests use an in-memory fake port, so no HTTP transport or
Intervals.icu client is involved. The adapter tests run the Intervals.icu
adapter over the real IntervalsClient with only the request function mocked and
pin the REST calls the library flow used before it went through the port.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from remote_link_fixtures import create_remote_links_table

from backend.canonical.vocabulary import (
    ProviderId,
    RemoteEntityKind,
    RemoteLinkState,
)
from backend.config import Config
from backend.db import DatabaseManager, row_factory
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.planning import workouts as planning_workouts
from backend.providers.intervals_client import IntervalsClient
from backend.sync.intervals_workout_export import IntervalsWorkoutExport
from backend.sync.library import (
    WorkoutLibraryRefreshService,
    WorkoutLibraryRemoteReconciler,
    WorkoutLibrarySyncService,
    WorkoutLibrarySyncStateService,
)
from backend.sync.workout_export import (
    WorkoutExportCapabilities,
    WorkoutLibraryExportPort,
)

NOW = "2026-10-12T08:00:00+00:00"
LOCAL_ID = "12345678-1234-5678-1234-567812345678"
OTHER_ID = "87654321-4321-8765-4321-876543218765"
INTERVALS = ProviderId.INTERVALS.value
LIBRARY = RemoteEntityKind.LIBRARY_WORKOUT


def strength(name: str = "Strength") -> dict[str, Any]:
    return {
        "sport": "WeightTraining",
        "type": "WeightTraining",
        "name": name,
        "description": "Three sets of ten.",
        "duration_minutes": 30,
    }


def config() -> Config:
    return Config(
        port=8090,
        openai_api_key="",
        openai_base_url="",
        openai_model="",
        intervals_api_key="fake-key",
        intervals_athlete_id="0",
        garmin_email="",
        garmin_password="",
        garmin_tokenstore="",
        garmin_fixture_path="",
        calendar_ical_url="",
        app_password="x" * 12,
        secure_cookies=False,
        data_retention_days=-1,
    )


class FakeLibraryPort:
    """An in-memory export target that records every call and never uses HTTP."""

    capabilities = WorkoutExportCapabilities(library=True)

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.remote: list[dict[str, Any]] = []
        self.readback_error: AppError | None = None
        self.fail_update: Exception | None = None

    def serialize_library(self, workout: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("serialize_library", workout["name"]))
        return {"name": workout["name"], "type": workout["type"], "target": "AUTO"}

    def library_list(
        self, *, cancel_event: threading.Event | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append(("library_list", cancel_event))
        return list(self.remote)

    def library_create(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.calls.append(("library_create", payloads))
        created = [
            {**payload, "id": f"remote-{len(self.remote) + index + 1}"}
            for index, payload in enumerate(payloads)
        ]
        self.remote.extend(created)
        return created

    def library_update(self, remote_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("library_update", (remote_id, payload)))
        if self.fail_update is not None:
            raise self.fail_update
        return {**payload, "id": remote_id}

    def library_plan(
        self,
        remote_id: str,
        workout: dict[str, Any],
        plan_date: str,
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("library_plan", (remote_id, plan_date, today)))
        return {"id": "event-1", "external_id": f"event-{remote_id}", "type": "Run"}

    def verify_library_readback(
        self, workout: dict[str, Any], remote: dict[str, Any]
    ) -> None:
        self.calls.append(("verify_library_readback", remote.get("id")))
        if self.readback_error is not None:
            raise self.readback_error

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


class _LibraryDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "library.db",
            sqlite3,
            row_factory=row_factory,
        )
        self.addCleanup(self.database_manager.close)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE workout_library (id TEXT NOT NULL, local_id TEXT PRIMARY KEY, external_id TEXT, "
                "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL, "
                "sync_error TEXT, last_synced_at TEXT, updated_at TEXT NOT NULL)"
            )
            create_remote_links_table(db)
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, external_id TEXT, "
                "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL)"
            )
        self.state = WorkoutLibrarySyncStateService(
            self.database_manager,
            Mock(redact_text=lambda text: text),
            KeyValueRepository(lambda: NOW),
            lambda: NOW,
        )

    def add_entry(
        self,
        local_id: str = LOCAL_ID,
        *,
        state: str = "local",
        external_id: str | None = None,
        workout: dict[str, Any] | None = None,
        link: bool = False,
    ) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, external_id, payload, "
                "sync_dirty, sync_state, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                (
                    f"workout-{local_id}",
                    local_id,
                    external_id,
                    json.dumps(workout or strength()),
                    state,
                    NOW,
                ),
            )
            if link:
                RemoteLinkRepository().refresh_from_slots(db, LIBRARY, local_id)

    def row(self, local_id: str = LOCAL_ID) -> dict[str, Any]:
        with self.database_manager.reader() as db:
            return db.execute(
                "SELECT * FROM workout_library WHERE local_id=?", (local_id,)
            ).fetchone()

    def link(self, local_id: str = LOCAL_ID) -> dict[str, Any]:
        link = self.find_link(local_id)
        assert link is not None
        return link

    def find_link(self, local_id: str = LOCAL_ID) -> dict[str, Any] | None:
        with self.database_manager.reader() as db:
            return db.execute(
                "SELECT remote_external_id, sync_state FROM remote_links "
                "WHERE entity_kind=? AND local_id=? AND provider=?",
                (LIBRARY.value, local_id, INTERVALS),
            ).fetchone()


class LibrarySyncThroughFakePortTests(_LibraryDatabase):
    def setUp(self) -> None:
        super().setUp()
        self.port = FakeLibraryPort()
        self.service = WorkoutLibrarySyncService(config(), self.port, self.state)

    def test_fake_port_satisfies_the_library_protocol(self) -> None:
        self.assertIsInstance(self.port, WorkoutLibraryExportPort)
        self.assertTrue(self.port.capabilities.library)
        self.assertFalse(self.port.capabilities.planned_events)

    def test_new_entry_is_listed_created_verified_and_linked(self) -> None:
        self.add_entry()

        synced = self.service.sync_entry(LOCAL_ID)

        self.assertEqual(
            self.port.names(),
            [
                "serialize_library",
                "library_list",
                "library_create",
                "verify_library_readback",
            ],
        )
        self.assertEqual(synced["external_id"], "remote-1")
        self.assertEqual(self.row()["external_id"], "remote-1")
        self.assertEqual(self.row()["sync_state"], "synced")
        self.assertEqual(self.link()["remote_external_id"], "remote-1")

    def test_known_entry_is_updated_by_the_link_identity(self) -> None:
        self.add_entry(state="sync_error", external_id="remote-slot", link=True)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE remote_links SET remote_external_id='remote-link' "
                "WHERE local_id=?",
                (LOCAL_ID,),
            )

        self.service.sync_entry(LOCAL_ID)

        update = [value for name, value in self.port.calls if name == "library_update"]
        self.assertEqual([remote_id for remote_id, _ in update], ["remote-link"])
        self.assertNotIn("library_list", self.port.names())
        self.assertNotIn("library_create", self.port.names())

    def test_recovered_remote_entry_is_adopted_without_creating(self) -> None:
        self.add_entry(state="remote_missing", external_id="remote-gone", link=True)
        self.port.remote = [{**strength(), "id": "remote-recovered"}]

        self.service.sync_entry(LOCAL_ID)

        self.assertNotIn("library_create", self.port.names())
        self.assertEqual(self.link()["remote_external_id"], "remote-recovered")
        self.assertEqual(self.row()["external_id"], "remote-recovered")

    def test_failed_readback_keeps_identity_in_slot_and_link_together(self) -> None:
        self.add_entry()
        self.port.readback_error = AppError(502, "Sportart nicht bestätigt.")

        with self.assertRaises(AppError):
            self.service.sync_entry(LOCAL_ID)

        row = self.row()
        self.assertEqual(row["external_id"], "remote-1")
        self.assertEqual(row["sync_state"], "sync_error")
        self.assertEqual(self.link()["remote_external_id"], "remote-1")

    def test_provider_failure_leaves_slot_and_link_unchanged(self) -> None:
        self.add_entry(state="sync_error", external_id="remote-old", link=True)
        self.port.fail_update = RuntimeError("provider down")

        with self.assertRaisesRegex(RuntimeError, "provider down"):
            self.service.sync_entry(LOCAL_ID)

        self.assertEqual(self.row()["external_id"], "remote-old")
        self.assertEqual(self.link()["remote_external_id"], "remote-old")

    def test_finish_failure_rolls_back_slot_and_link_in_one_transaction(self) -> None:
        self.add_entry(state="syncing", external_id="remote-old", link=True)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER fail_library_sync_error BEFORE INSERT ON kv "
                "WHEN NEW.key='last_library_sync_error' BEGIN "
                "SELECT RAISE(ABORT, 'forced rollback'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.state.finish(
                LOCAL_ID,
                "remote-new",
                strength(),
                {**strength(), "id": "remote-new"},
                verify_readback=self.port.verify_library_readback,
            )

        self.assertEqual(self.row()["external_id"], "remote-old")
        self.assertEqual(self.row()["sync_state"], "syncing")
        self.assertEqual(self.link()["remote_external_id"], "remote-old")

    def test_finish_verifies_through_the_supplied_readback_before_writing(self) -> None:
        self.add_entry(state="syncing")
        self.port.readback_error = AppError(502, "abgelehnt")

        with self.assertRaises(AppError):
            self.state.finish(
                LOCAL_ID,
                "remote-1",
                strength(),
                {**strength(), "id": "remote-1"},
                verify_readback=self.port.verify_library_readback,
            )

        self.assertEqual(self.row()["sync_state"], "syncing")
        self.assertIsNone(self.find_link())

    def test_calendar_entry_plans_and_verifies_through_the_port(self) -> None:
        self.add_entry(external_id="remote-1", link=True)
        service = WorkoutLibrarySyncService(
            config(), self.port, self.state, local_today=lambda: date(2026, 10, 12)
        )

        event = service.sync_calendar_entry(
            LOCAL_ID,
            {**strength(), "date": "2026-10-20", "external_id": "remote-1"},
        )

        self.assertIsNotNone(event)
        self.assertEqual((event or {}).get("id"), "event-1")
        self.assertEqual(
            [value for name, value in self.port.calls if name == "library_plan"],
            [("remote-1", "2026-10-20", date(2026, 10, 12))],
        )
        self.assertIn("verify_library_readback", self.port.names())

    def test_plan_remote_defaults_the_day_to_the_target_clock(self) -> None:
        self.service.plan_remote("remote-1", strength(), "2026-10-20")

        self.assertEqual(
            [value for name, value in self.port.calls if name == "library_plan"],
            [("remote-1", "2026-10-20", None)],
        )


class LibraryRefreshThroughFakePortTests(_LibraryDatabase):
    def test_refresh_reads_the_library_through_the_port_with_cancellation(
        self,
    ) -> None:
        port = FakeLibraryPort()
        port.remote = [{**strength("Remote"), "id": "remote-9"}]
        reconciler = Mock()
        reconciler.reconcile.return_value = [{"external_id": "remote-9"}]
        sync_state = Mock()
        sync_state.summary.return_value = {}
        service = WorkoutLibraryRefreshService(
            config(),
            self.database_manager,
            port,
            reconciler,
            Mock(),
            sync_state,
            KeyValueRepository(lambda: NOW),
            Mock(),
            lambda: NOW,
        )
        cancel_event = threading.Event()

        result = service.refresh(cancel_event=cancel_event)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(port.calls, [("library_list", cancel_event)])
        reconciler.reconcile.assert_called_once_with(port.remote, remove_missing=True)


class LibraryReadsResolveThroughRemoteLinksTests(_LibraryDatabase):
    def test_preview_prefers_the_link_and_uses_the_slot_only_without_one(self) -> None:
        self.add_entry("lib-linked", external_id="slot-id", link=True)
        self.add_entry("lib-legacy", external_id="legacy-id")
        self.add_entry("lib-unlinked-id", external_id="stale-slot", link=True)
        with self.database_manager.unit_of_work() as db:
            # A link without an external id outranks a retained legacy slot.
            RemoteLinkRepository().upsert(
                db,
                RemoteLink(
                    entity_kind=LIBRARY,
                    local_id="lib-unlinked-id",
                    provider=INTERVALS,
                    sync_state=RemoteLinkState.PENDING,
                ),
            )

        _, entries, _ = self.state.preview()

        by_id = {entry["local_id"]: entry for entry in entries}
        self.assertTrue(by_id["lib-linked"]["has_remote_id"])
        self.assertTrue(by_id["lib-legacy"]["has_remote_id"])
        self.assertFalse(by_id["lib-unlinked-id"]["has_remote_id"])
        self.assertEqual(by_id["lib-unlinked-id"]["category"], "new")

    def test_missing_remote_marking_resolves_the_external_id_through_the_link(
        self,
    ) -> None:
        self.add_entry("lib-seen", state="synced", external_id="slot-seen", link=True)
        self.add_entry("lib-gone", state="synced", external_id="slot-gone", link=True)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE remote_links SET remote_external_id='link-seen' "
                "WHERE local_id='lib-seen'"
            )
            db.execute(
                "UPDATE workout_library SET sync_dirty=0 WHERE sync_state='synced'"
            )
        reconciler = WorkoutLibraryRemoteReconciler(
            self.database_manager, lambda: NOW, lambda: OTHER_ID
        )

        reconciler.reconcile([], remove_missing=False)
        with self.database_manager.unit_of_work() as db:
            reconciler._mark_missing_remote_library_workouts(db, {"link-seen"}, NOW)

        self.assertEqual(self.row("lib-seen")["sync_state"], "synced")
        self.assertEqual(self.row("lib-gone")["sync_state"], "remote_missing")

    def test_missing_remote_marking_covers_a_link_without_a_slot(self) -> None:
        self.add_entry(
            "lib-linked-only", state="synced", external_id="slot-x", link=True
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET external_id=NULL, sync_dirty=0 "
                "WHERE local_id='lib-linked-only'"
            )
            WorkoutLibraryRemoteReconciler(
                self.database_manager, lambda: NOW, lambda: OTHER_ID
            )._mark_missing_remote_library_workouts(db, set(), NOW)

        self.assertEqual(self.row("lib-linked-only")["sync_state"], "remote_missing")


class IntervalsLibraryAdapterParityTests(unittest.TestCase):
    """The adapter issues exactly the REST calls the library flow used before."""

    def setUp(self) -> None:
        self.request = Mock(return_value=None)
        stub = type(
            "ConfigStub",
            (),
            {"intervals_api_key": "test-key", "intervals_athlete_id": "athlete/1"},
        )()
        self.client = IntervalsClient(
            stub,
            request=self.request,
            now=lambda: datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
        )
        self.export = IntervalsWorkoutExport(lambda: self.client)

    def calls(self) -> list[tuple[str, str]]:
        return [(call.args[0], call.args[1]) for call in self.request.call_args_list]

    def test_serialize_library_matches_the_planning_payload(self) -> None:
        factory = Mock()
        export = IntervalsWorkoutExport(factory)

        self.assertEqual(
            export.serialize_library(strength()),
            planning_workouts.library_workout_payload(strength()),
        )
        factory.assert_not_called()

    def test_library_list_reads_the_athlete_workouts_and_keeps_known_fields(
        self,
    ) -> None:
        self.request.return_value = [
            {"id": 3, "name": "A", "secret": "dropped", "tags": None}
        ]

        listed = self.export.library_list()

        self.assertEqual(listed, [{"id": 3, "name": "A"}])
        method, url = self.calls()[0]
        self.assertEqual(method, "GET")
        self.assertIn("/athlete/athlete%2F1/workouts", url)

    def test_library_list_forwards_the_cancel_event_to_the_paged_read(self) -> None:
        cancel_event = threading.Event()
        paged = Mock(return_value=[])
        self.client.get_paged_collection = paged  # type: ignore[method-assign]

        self.export.library_list(cancel_event=cancel_event)
        self.export.library_list()

        self.assertIs(paged.call_args_list[0].kwargs["cancel_event"], cancel_event)
        self.assertIsNone(paged.call_args_list[1].kwargs["cancel_event"])

    def test_library_create_posts_into_the_coach_folder(self) -> None:
        self.request.side_effect = [
            [{"id": 7, "name": "Intervals Coach"}],
            {"id": "remote-1", "type": "WeightTraining"},
        ]
        payload = self.export.serialize_library(strength())

        created = self.export.library_create([payload])

        self.assertEqual(created, [{"id": "remote-1", "type": "WeightTraining"}])
        (folder_method, folder_url), (method, url) = self.calls()
        self.assertEqual(folder_method, "GET")
        self.assertTrue(folder_url.endswith("/athlete/athlete%2F1/folders"))
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/athlete/athlete%2F1/workouts"))
        self.assertEqual(
            self.request.call_args.args[2],
            {
                "name": "Strength",
                "description": "Three sets of ten.",
                "type": "WeightTraining",
                "folder_id": 7,
                "target": "AUTO",
            },
        )

    def test_library_update_puts_to_the_quoted_remote_id(self) -> None:
        self.request.return_value = {"id": "remote/1", "type": "WeightTraining"}
        payload = {**self.export.serialize_library(strength()), "folder_id": 7}

        updated = self.export.library_update("remote/1", payload)

        self.assertEqual(updated["id"], "remote/1")
        method, url = self.calls()[0]
        self.assertEqual(method, "PUT")
        self.assertTrue(url.endswith("/athlete/athlete%2F1/workouts/remote%2F1"))
        self.assertEqual(self.request.call_args.args[2]["folder_id"], 7)

    def test_library_plan_posts_one_upserted_event_using_the_client_day(self) -> None:
        self.request.return_value = [{"id": "event-1", "type": "WeightTraining"}]

        event = self.export.library_plan("remote-1", strength(), "2026-09-22")

        self.assertEqual(event["id"], "event-1")
        method, url = self.calls()[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/athlete/athlete%2F1/events/bulk?upsert=true"))
        self.assertEqual(
            self.request.call_args.args[2],
            [
                planning_workouts.library_workout_event_payload(
                    "remote-1", strength(), "2026-09-22", today=date(2026, 9, 20)
                )
            ],
        )

    def test_library_plan_honours_an_explicit_day_without_asking_the_client(
        self,
    ) -> None:
        client = Mock()
        client.plan_library_workout.return_value = {"id": "event-1"}
        export = IntervalsWorkoutExport(lambda: client)

        export.library_plan(
            "remote-1", strength(), "2026-09-22", today=date(2026, 9, 21)
        )

        client.local_today.assert_not_called()
        client.plan_library_workout.assert_called_once_with(
            planning_workouts.library_workout_event_payload(
                "remote-1", strength(), "2026-09-22", today=date(2026, 9, 21)
            )
        )

    def test_library_readback_rejects_a_sport_mismatch(self) -> None:
        saved = {**strength(), "id": "remote-1"}
        self.export.verify_library_readback(strength(), saved)

        with self.assertRaises(AppError) as caught:
            self.export.verify_library_readback(strength(), {**saved, "type": "Run"})
        self.assertEqual(caught.exception.reason, "intervals_workout_sport_mismatch")

    def test_serialize_and_readback_never_open_the_transport(self) -> None:
        factory = Mock()
        export = IntervalsWorkoutExport(factory)

        export.serialize_library(strength())
        export.verify_library_readback(strength(), {**strength(), "id": "remote-1"})

        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
