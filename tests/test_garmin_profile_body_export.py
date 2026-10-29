"""Synthetic Garmin export and real SQLite coordination checks."""

import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from time import monotonic
from unittest.mock import Mock, patch

from backend.athlete.profile import ProfileService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.db.schema import initialize_schema
from backend.http_api.athlete_put import AthletePutRoutes
from backend.sync.garmin_profile_body_export import GarminProfileBodyExport
from backend.sync.garmin_service import shared_garmin_sync_lock


class BodyExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(
            Path(self.tmp.name) / "test.db", sqlite3, row_factory=row_factory
        )
        with self.db.unit_of_work() as db:
            initialize_schema(db)
        self.kv = KeyValueRepository(lambda: "2026-10-29T00:00:00Z")
        self.profile = ProfileService(
            self.db,
            ProfileRepository(self.kv),
            self.kv,
            on_location_changed=lambda *a, **k: None,
            mutation_coordinator=threading.RLock(),
        )
        self.saved = self.profile.patch(
            {"weight_kg": "75", "body_fat_pct": "15", "timezone": "Europe/Berlin"}
        )
        self.revision = self.profile.revision()
        self.client = Mock()
        self.client.add_body_composition.return_value = {
            "detailedImportResult": {"successes": [{"id": "synthetic"}], "failures": []}
        }
        self.reader = Mock()
        self.reader.configured.return_value = True
        self.reader._authenticated_client.return_value = (self.client, "synthetic")
        self.fixture = Mock()
        self.fixture.path.return_value = None
        self.tokens = Mock()

        def write_back(*_args):
            with self.db.unit_of_work() as db:
                self.kv.set(db, "synthetic_token", "updated")

        self.tokens.write_back.side_effect = write_back
        self.exporter = GarminProfileBodyExport(
            self.profile, self.reader, self.fixture, self.tokens
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_results_and_token_writeback(self):
        self.assertEqual(self.exporter.export(self.saved, self.revision), "success")
        with self.db.reader() as db:
            self.assertEqual(self.kv.get(db, "synthetic_token"), "updated")
        self.client.add_body_composition.return_value = {}
        self.assertEqual(self.exporter.export(self.saved, self.revision), "uncertain")
        self.client.add_body_composition.return_value = {
            "detailedImportResult": {
                "successes": [],
                "failures": [{"error": "synthetic"}],
            }
        }
        self.assertEqual(self.exporter.export(self.saved, self.revision), "rejected")
        for missing in ({}, {"successes": None}, {"successes": "invalid"}):
            self.client.add_body_composition.return_value = {
                "detailedImportResult": {
                    **missing,
                    "failures": [{"error": "synthetic"}],
                }
            }
            self.assertEqual(
                self.exporter.export(self.saved, self.revision), "uncertain"
            )
        self.client.add_body_composition.return_value = {
            "detailedImportResult": {
                "successes": [{"id": "synthetic"}],
                "failures": [{"error": "synthetic"}],
            }
        }
        self.assertEqual(self.exporter.export(self.saved, self.revision), "uncertain")
        self.client.add_body_composition.side_effect = TimeoutError("synthetic")
        self.client.add_body_composition.reset_mock()
        self.assertEqual(self.exporter.export(self.saved, self.revision), "uncertain")
        self.client.add_body_composition.assert_called_once()
        self.reader._authenticated_client.side_effect = RuntimeError("synthetic")
        self.assertEqual(self.exporter.export(self.saved, self.revision), "unavailable")

    def test_invalid_fixture_and_superseded(self):
        for value in ("NaN", "inf", "19", "301", ""):
            saved = self.profile.patch({"weight_kg": value})
            self.assertEqual(
                self.exporter.export(saved, self.profile.revision()), "invalid"
            )
        saved = self.profile.patch({"weight_kg": "75"})
        self.fixture.path.return_value = Path("synthetic")
        self.assertEqual(
            self.exporter.export(saved, self.profile.revision()), "unavailable"
        )
        old_revision = self.profile.revision()
        self.profile.patch({"weight_kg": "76"})
        self.assertEqual(self.exporter.export(saved, old_revision), "superseded")
        self.client.add_body_composition.assert_not_called()

    def test_timeout_releases_coordinator_for_other_thread(self):
        self.client.add_body_composition.side_effect = TimeoutError("synthetic")
        self.assertEqual(self.exporter.export(self.saved, self.revision), "uncertain")
        finished = threading.Event()
        thread = threading.Thread(
            target=lambda: (self.profile.patch({"name": "after"}), finished.set())
        )
        thread.start()
        thread.join(5)
        self.assertTrue(finished.is_set())
        self.assertFalse(thread.is_alive())

    def test_explicit_retry_sends_unchanged_profile_once(self):
        handler = Mock()
        handler.read_json.return_value = {
            "sync_body_to_garmin": True,
            "retry_body_to_garmin": True,
        }
        send = Mock(return_value="success")
        routes = AthletePutRoutes(
            Mock(), lambda: self.profile, threading.RLock(), None, send
        )
        routes.handle(handler, "/api/profile")
        send.assert_called_once()
        self.assertEqual(
            handler.send_json.call_args.args[1]["garmin_body_export"], "success"
        )

    def test_busy_garmin_lock_expires_without_upload(self):
        results = []
        with shared_garmin_sync_lock():
            thread = threading.Thread(
                target=lambda: results.append(
                    self.exporter.export(self.saved, self.revision, monotonic() + 0.1)
                )
            )
            thread.start()
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results, ["unavailable"])
        self.client.add_body_composition.assert_not_called()

    def test_waiting_export_is_superseded(self):
        started = threading.Event()
        result = []

        def run():
            started.set()
            result.append(self.exporter.export(self.saved, self.revision))

        with shared_garmin_sync_lock():
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(started.wait(2))
            self.profile.patch({"weight_kg": "76"})
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["superseded"])
        self.client.add_body_composition.assert_not_called()

    def test_waiting_export_rejects_aba_profile_revision(self):
        earlier = self.profile.patch({"weight_kg": "76"})
        old_revision = self.profile.revision()
        self.profile.patch({"weight_kg": "77"})
        self.profile.patch({"weight_kg": "76"})
        self.assertEqual(self.exporter.export(earlier, old_revision), "superseded")
        self.client.add_body_composition.assert_not_called()

    def test_upload_serializes_mutation_but_not_other_writes(self):
        entered, release, changed = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def upload(**_kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError()
            return {
                "detailedImportResult": {
                    "successes": [{"id": "synthetic"}],
                    "failures": [],
                }
            }

        self.client.add_body_composition.side_effect = upload
        results = []
        export_thread = threading.Thread(
            target=lambda: results.append(
                self.exporter.export(self.saved, self.revision)
            )
        )
        export_thread.start()
        self.assertTrue(entered.wait(2))
        mutation = threading.Thread(
            target=lambda: (self.profile.patch({"name": "later"}), changed.set())
        )
        mutation.start()
        try:
            self.assertFalse(changed.wait(0.15))
            with self.db.unit_of_work() as db:
                self.kv.set(db, "unrelated", "available")
        finally:
            release.set()
            export_thread.join(5)
            mutation.join(5)
        self.assertEqual(results, ["success"])
        self.assertTrue(changed.is_set())

    def test_route_opt_in_only_after_committed_change(self):
        handler = Mock()
        handler.read_json.return_value = {
            "weight_kg": "76",
            "sync_body_to_garmin": True,
        }
        routes = AthletePutRoutes(
            Mock(),
            lambda: self.profile,
            threading.RLock(),
            body_export=self.exporter.export,
        )
        routes.handle(handler, "/api/profile")
        self.assertEqual(
            handler.send_json.call_args.args[1]["garmin_body_export"], "success"
        )
        self.client.add_body_composition.reset_mock()
        routes.handle(handler, "/api/profile")
        self.client.add_body_composition.assert_not_called()
        self.assertEqual(
            handler.send_json.call_args.args[1]["garmin_body_export"], "unchanged"
        )
        handler.read_json.return_value = {"weight_kg": "77"}
        routes.handle(handler, "/api/profile")
        self.client.add_body_composition.assert_not_called()


class BodyExportMockTests(unittest.TestCase):
    def test_authentication_finishing_after_deadline_never_uploads(self):
        profile = Mock()
        profile.mutation_coordinator = threading.RLock()
        profile.get.return_value = {
            "weight_kg": "75",
            "body_fat_pct": "15",
            "timezone": "UTC",
        }
        profile.revision.return_value = "revision"
        client = Mock()
        reader = Mock()
        reader.configured.return_value = True
        reader._authenticated_client.return_value = (client, "synthetic")
        fixture = Mock()
        fixture.path.return_value = None
        tokens = Mock()
        exporter = GarminProfileBodyExport(profile, reader, fixture, tokens)
        with patch(
            "backend.sync.garmin_profile_body_export.monotonic",
            side_effect=[0, 0, 0, 11],
        ):
            self.assertEqual(
                exporter.export(profile.get.return_value, "revision", 10), "unavailable"
            )
        client.add_body_composition.assert_not_called()
        tokens.write_back.assert_called_once()

    def test_outcomes_and_local_timestamp_without_database(self):
        profile = Mock()
        profile.mutation_coordinator = threading.RLock()
        profile.revision.return_value = "synthetic-revision"
        profile.get.return_value = {
            "weight_kg": "75",
            "body_fat_pct": "15",
            "timezone": "Europe/Berlin",
        }
        fixture = Mock()
        fixture.path.return_value = None
        client = Mock()
        reader = Mock()
        reader.configured.return_value = True
        reader._authenticated_client.return_value = (client, "synthetic")
        exporter = GarminProfileBodyExport(profile, reader, fixture, Mock())
        saved = profile.get.return_value.copy()
        client.add_body_composition.return_value = {
            "detailedImportResult": {"successes": [{"id": "synthetic"}], "failures": []}
        }
        self.assertEqual(exporter.export(saved, "synthetic-revision"), "success")
        args = client.add_body_composition.call_args.kwargs
        self.assertEqual((args["weight"], args["percent_fat"]), (75, 15))
        self.assertIsNotNone(datetime.fromisoformat(args["timestamp"]).utcoffset())
        client.add_body_composition.side_effect = TimeoutError("synthetic")
        client.add_body_composition.reset_mock()
        self.assertEqual(exporter.export(saved, "synthetic-revision"), "uncertain")
        client.add_body_composition.assert_called_once()
