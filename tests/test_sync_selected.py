from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from backend.db import DatabaseManager, row_factory
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.sync.gates import ProviderResyncGate
from backend.sync.selected import SelectedWorkoutSyncService


class RecordingLock:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.acquire_calls: list[dict[str, float]] = []
        self.release_calls = 0

    def acquire(self, *, timeout: float) -> bool:
        self.acquire_calls.append({"timeout": timeout})
        return self.acquired

    def release(self) -> None:
        self.release_calls += 1


class CountingResyncGate(ProviderResyncGate):
    def __init__(self) -> None:
        super().__init__("Intervals.icu")
        self.operation_entries = 0
        self.operation_exits = 0

    @contextmanager
    def operation(self):
        self.operation_entries += 1
        try:
            with super().operation():
                yield
        finally:
            self.operation_exits += 1


class SelectedWorkoutSyncServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "selected.sqlite3"
        with closing(sqlite3.connect(self.database_path)) as db:
            db.execute(
                "CREATE TABLE workout_library "
                "(local_id TEXT PRIMARY KEY, payload TEXT, sync_state TEXT)"
            )
            db.execute(
                "CREATE TABLE planned_units "
                "(local_id TEXT PRIMARY KEY, payload TEXT, sync_state TEXT)"
            )
            db.commit()
        self.database = DatabaseManager(
            self.database_path,
            sqlite3,
            row_factory=row_factory,
            persist_connections=False,
        )
        self.config = SimpleNamespace(intervals_api_key="fake-key")
        self.library_sync = MagicMock()
        self.calendar_sync = MagicMock()
        self.repair_sync = MagicMock()
        self.lock = RecordingLock()

    def tearDown(self) -> None:
        self.database.close()
        self.temp_dir.cleanup()

    def _add(
        self, kind: str, payload: dict[str, object], state: str = "local"
    ) -> dict[str, str]:
        local_id = str(uuid.uuid4())
        raw_payload = json.dumps(payload, separators=(",", ":"))
        table = "planned_units" if kind == "planned" else "workout_library"
        with closing(sqlite3.connect(self.database_path)) as db:
            db.execute(
                f"INSERT INTO {table}(local_id, payload, sync_state) VALUES (?, ?, ?)",
                (local_id, raw_payload, state),
            )
            db.commit()
        return {
            "library_workout_id": local_id,
            "expected_payload_hash": planning_library.library_payload_hash(raw_payload),
        }

    def _service(
        self,
        *,
        api_key: str | None = None,
        redactor=None,
        lock: RecordingLock | None = None,
        wait_seconds: float = 3.0,
        provider_resync_gate: ProviderResyncGate | None = None,
    ) -> SelectedWorkoutSyncService:
        if api_key is not None:
            self.config.intervals_api_key = api_key
        return SelectedWorkoutSyncService(
            self.config,
            self.database,
            self.library_sync,
            self.calendar_sync,
            self.repair_sync,
            redactor or (lambda text: text),
            lock=lock or self.lock,
            wait_seconds=wait_seconds,
            **(
                {"provider_resync_gate": provider_resync_gate}
                if provider_resync_gate is not None
                else {}
            ),
        )

    def test_api_key_gate_precedes_request_normalization(self) -> None:
        service = self._service(api_key="")
        with (
            patch(
                "backend.sync.selected.planning_library.library_bulk_request_entries"
            ) as normalize,
            self.assertRaises(AppError) as raised,
        ):
            service.sync({"entries": "invalid"})
        self.assertEqual(raised.exception.status, 503)
        normalize.assert_not_called()
        self.assertEqual(self.lock.acquire_calls, [])

    def test_pending_and_existing_library_entries(self) -> None:
        pending = self._add("library", {"date": "2026-10-01"})
        calendar_candidate = self._add(
            "library", {"date": "2026-10-02", "name": "Keep me"}, "synced"
        )
        already_remote = self._add(
            "library",
            {"date": "2026-10-03", "remote_event_id": "event-3"},
            "synced",
        )
        self.library_sync.sync_entry.return_value = {
            "external_id": "remote-workout",
            "date": "2026-10-01",
        }
        self.library_sync.sync_calendar_entry.side_effect = [
            {"id": "event-1"},
            None,
        ]
        gate = CountingResyncGate()

        result = self._service(provider_resync_gate=gate).sync(
            {"entries": [pending, calendar_candidate, already_remote]}
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [item["status"] for item in result["results"]],
            ["synced", "synced", "already_synced"],
        )
        self.assertEqual(result["results"][0]["external_id"], True)
        self.assertTrue(result["results"][0]["calendar_synced"])
        self.assertTrue(result["results"][1]["calendar_synced"])
        self.library_sync.sync_entry.assert_called_once_with(
            pending["library_workout_id"]
        )
        self.assertEqual(
            self.library_sync.sync_calendar_entry.call_args_list,
            [
                call(
                    pending["library_workout_id"],
                    self.library_sync.sync_entry.return_value,
                ),
                call(
                    calendar_candidate["library_workout_id"],
                    {"date": "2026-10-02", "name": "Keep me"},
                ),
            ],
        )
        self.assertEqual(self.lock.acquire_calls, [])
        self.assertEqual(gate.operation_entries, 3)
        self.assertEqual(gate.operation_exits, 3)
        self.assertEqual(gate.active, 0)

    def test_resetting_gate_blocks_library_remote_operations(self) -> None:
        pending = self._add("library", {"date": "2026-10-01"})
        existing = self._add("library", {"date": "2026-10-02"}, "synced")
        gate = ProviderResyncGate("Intervals.icu")
        reset_acquired = threading.Event()
        release_reset = threading.Event()
        reset_result: list[bool] = []

        def hold_reset() -> None:
            reset_result.append(gate.begin_reset())
            reset_acquired.set()
            release_reset.wait(timeout=5)
            gate.end_reset()

        worker = threading.Thread(target=hold_reset, daemon=True)
        worker.start()
        self.assertTrue(reset_acquired.wait(timeout=2))
        self.assertTrue(reset_result[0])
        try:
            result = self._service(provider_resync_gate=gate).sync(
                {"entries": [pending, existing]}
            )
        finally:
            release_reset.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result["status"], "error")
        self.assertEqual(
            [item["status"] for item in result["results"]], ["error", "error"]
        )
        self.library_sync.sync_entry.assert_not_called()
        self.library_sync.sync_calendar_entry.assert_not_called()

    def test_selected_row_reuses_active_outer_unit_of_work(self) -> None:
        local_id = str(uuid.uuid4())
        raw_payload = json.dumps({"date": "2026-10-01"}, separators=(",", ":"))
        entry = {
            "library_workout_id": local_id,
            "expected_payload_hash": planning_library.library_payload_hash(raw_payload),
        }
        self.library_sync.sync_entry.return_value = {"external_id": "remote"}
        self.library_sync.sync_calendar_entry.return_value = None

        with self.database.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(local_id, payload, sync_state) VALUES (?, ?, ?)",
                (local_id, raw_payload, "local"),
            )
            result = self._service().sync({"entries": [entry]})

        self.assertEqual(result["status"], "ok")
        self.library_sync.sync_entry.assert_called_once_with(local_id)

    def test_planned_normal_and_repair_paths(self) -> None:
        normal = self._add("planned", {"date": "2026-10-01"})
        repair = self._add("planned", {"date": "2026-10-02"})
        self.calendar_sync.sync_entry.return_value = {"id": "event-normal"}
        batch = MagicMock()
        batch.verify.return_value = {}
        self.repair_sync.create_batch.return_value = batch
        self.repair_sync.repair_entry.return_value = None
        gate = CountingResyncGate()

        normal_result = self._service(provider_resync_gate=gate).sync(
            {"entries": [normal]}
        )
        repair_result = self._service(provider_resync_gate=gate).sync(
            {"entries": [repair], "repair": True}
        )

        self.assertEqual(normal_result["status"], "ok")
        self.assertTrue(normal_result["results"][0]["calendar_synced"])
        self.calendar_sync.sync_entry.assert_called_once_with(
            normal["library_workout_id"]
        )
        self.repair_sync.create_batch.assert_called_once()
        self.repair_sync.repair_entry.assert_called_once_with(
            repair["library_workout_id"], repair["expected_payload_hash"], batch=batch
        )
        self.assertEqual(repair_result["status"], "ok")
        self.assertTrue(repair_result["results"][0]["calendar_synced"])
        self.assertEqual(self.lock.acquire_calls, [{"timeout": 3.0}])
        self.assertEqual(self.lock.release_calls, 1)
        self.assertEqual(gate.operation_entries, 0)
        self.assertEqual(gate.operation_exits, 0)

    def test_hash_and_not_found_conflicts_are_aggregated(self) -> None:
        changed = self._add("library", {"name": "current"})
        changed["expected_payload_hash"] = "0" * 64
        missing = {
            "library_workout_id": str(uuid.uuid4()),
            "expected_payload_hash": "1" * 64,
        }

        result = self._service().sync({"entries": [changed, missing]})

        self.assertEqual(result["ok"], False)
        self.assertEqual(result["status"], "error")
        self.assertEqual(
            result["failed_object_ids"],
            [changed["library_workout_id"], missing["library_workout_id"]],
        )
        self.assertEqual(
            [item["error"] for item in result["results"]],
            ["Seit der Vorschau geändert", "Einheit nicht gefunden"],
        )
        self.assertEqual(
            result["retry_scope"], "Nur fehlgeschlagene Objekte erneut auswählen."
        )

    def test_partial_and_all_failure_aggregation(self) -> None:
        entries = [self._add("library", {"name": str(index)}) for index in range(3)]
        self.library_sync.sync_entry.side_effect = [
            {"external_id": "remote-ok"},
            RuntimeError("first failure"),
            RuntimeError("second failure"),
        ]
        self.library_sync.sync_calendar_entry.return_value = None
        result = self._service().sync({"entries": entries})
        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["failed_object_ids"],
            [entries[1]["library_workout_id"], entries[2]["library_workout_id"]],
        )
        self.assertEqual(
            result["retry_scope"], "Nur fehlgeschlagene Objekte erneut auswählen."
        )

        self.library_sync.sync_entry.side_effect = [
            RuntimeError("retry one"),
            RuntimeError("retry two"),
        ]
        all_failed = self._service().sync({"entries": entries[1:]})
        self.assertEqual(all_failed["ok"], False)
        self.assertEqual(all_failed["status"], "error")
        self.assertEqual(
            all_failed["failed_object_ids"],
            [entries[1]["library_workout_id"], entries[2]["library_workout_id"]],
        )

    def test_errors_are_redacted_and_limited_to_500_characters(self) -> None:
        entry = self._add("library", {"name": "workout"})
        self.library_sync.sync_entry.side_effect = RuntimeError(
            "token=secret-123 " + "x" * 600
        )
        service = self._service(
            redactor=lambda value: value.replace("secret-123", "[redacted]")
        )

        result = service.sync({"entries": [entry]})

        error = result["results"][0]["error"]
        self.assertIn("[redacted]", error)
        self.assertNotIn("secret-123", error)
        self.assertEqual(len(error), 500)

    def test_repair_errors_are_recorded_and_verification_failure_overrides_result(
        self,
    ) -> None:
        failed = self._add("planned", {"date": "2026-10-01"})
        verification_failed = self._add("planned", {"date": "2026-10-02"})
        batch = MagicMock()
        batch.verify.return_value = {
            verification_failed["library_workout_id"]: RuntimeError(
                "verification failed"
            )
        }
        self.repair_sync.create_batch.return_value = batch
        self.repair_sync.repair_entry.side_effect = [
            RuntimeError("repair failed"),
            None,
        ]

        result = self._service().sync(
            {"entries": [failed, verification_failed], "repair": True}
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(
            [item["error"] for item in result["results"]],
            ["repair failed", "verification failed"],
        )
        self.assertEqual(result["results"][1]["calendar_synced"], False)
        self.assertEqual(
            self.repair_sync.record_error.call_args_list,
            [
                call(failed["library_workout_id"], "repair failed"),
                call(verification_failed["library_workout_id"], "verification failed"),
            ],
        )

    def test_repair_lock_timeout_release_and_exception_cleanup(self) -> None:
        entry = self._add("planned", {"date": "2026-10-01"})
        timed_out_lock = RecordingLock(acquired=False)
        with self.assertRaises(AppError) as raised:
            self._service(lock=timed_out_lock).sync(
                {"entries": [entry], "repair": True}
            )
        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(timed_out_lock.acquire_calls, [{"timeout": 3.0}])
        self.assertEqual(timed_out_lock.release_calls, 0)
        self.repair_sync.create_batch.assert_not_called()

        raising_lock = RecordingLock()
        self.repair_sync.create_batch.side_effect = RuntimeError("batch failed")
        with self.assertRaisesRegex(RuntimeError, "batch failed"):
            self._service(lock=raising_lock).sync({"entries": [entry], "repair": True})
        self.assertEqual(raising_lock.release_calls, 1)


if __name__ == "__main__":
    unittest.main()
