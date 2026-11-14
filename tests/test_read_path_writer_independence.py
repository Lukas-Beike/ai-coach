"""Read-path GET services must not wait for the writer.

A thread holds the database writer for the whole test. Each
read service runs on another thread and has to finish: a service that still
takes the writer stalls here, and a hidden write fails on
the query-only snapshot instead of being silently serialized.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
import unittest
import zipfile
from collections.abc import Callable
from datetime import date
from typing import Any

from server_test_support import ServerTestCase, server

from backend.db.manager import background_writer
from backend.errors import AppError
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS

WAIT_SECONDS = 15


class ReadPathWriterIndependenceTests(ServerTestCase):
    def hold_writer(self) -> None:
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with server.database_manager().unit_of_work() as db:
                db.execute("UPDATE sessions SET last_seen=last_seen WHERE 0")
                held.set()
                release.wait(WAIT_SECONDS * 4)

        thread = threading.Thread(target=hold, daemon=True)
        thread.start()
        self.assertTrue(held.wait(5))

        def stop() -> None:
            release.set()
            thread.join(5)

        self.addCleanup(stop)

    def call_while_held(self, call):
        outcome: dict[str, object] = {}

        def run() -> None:
            try:
                outcome["value"] = call()
            except BaseException as error:  # noqa: BLE001 - re-raised by the test
                outcome["error"] = error

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(WAIT_SECONDS)
        if thread.is_alive():
            frame = sys._current_frames().get(thread.ident)
            where = "".join(traceback.format_stack(frame)[-6:]) if frame else ""
            self.fail(f"read path waited for the writer at:\n{where}")
        if "error" in outcome:
            raise outcome["error"]  # type: ignore[misc]
        return outcome["value"]

    def test_bootstrap_is_not_blocked_by_a_held_writer(self) -> None:
        expected = server.PUBLIC_STATE.bootstrap_service().read()
        self.hold_writer()
        actual = self.call_while_held(
            lambda: server.PUBLIC_STATE.bootstrap_service().read()
        )
        self.assertEqual(actual["state_versions"], expected["state_versions"])
        self.assertEqual(actual["profile"], expected["profile"])

    def test_performance_is_not_blocked_by_a_held_writer(
        self,
    ) -> None:
        service = server.PUBLIC_STATE.performance_state_service
        expected = service().performance_state()
        self.hold_writer()
        actual = self.call_while_held(lambda: service().performance_state())
        self.assertEqual(actual, expected)

    def read_calls(self) -> dict[str, Callable[[], object]]:
        """Every other moved GET read, as zero-argument callables."""
        public = server.PUBLIC_STATE
        diary = server.NUTRITION_SERVICES.diary_service
        library = server.NUTRITION_SERVICES.meal_library_service
        day = "2026-01-05"
        today = date(2026, 1, 5)
        reports = server.PERFORMANCE.training_reports()

        def outcome(call: Callable[[], object]) -> object:
            # A missing record is a normal answer for these reads; a hidden write
            # still fails loudly on the query-only snapshot instead.
            try:
                return call()
            except AppError as error:
                return ("app-error", error.status, error.reason)

        def without_clock(payload: dict[str, object]) -> dict[str, object]:
            # Each call stamps its own generation time; everything else is stable.
            return {
                key: value
                for key, value in payload.items()
                if key not in {"exported_at", "generated_at"}
            }

        def archive_files(*names: str) -> dict[str, bytes]:
            # The archive stamps its own generation time; its collections are stable.
            path = server.PRIVACY.archive_export_service().create_file()
            try:
                with zipfile.ZipFile(path) as archive:
                    return {name: archive.read(name) for name in names}
            finally:
                path.unlink()

        def without_process_measurements(payload: dict[str, Any]) -> dict[str, Any]:
            # Live process memory counters change between any two reports.
            runtime = {
                key: value
                for key, value in payload["runtime"].items()
                if key != "process_memory"
            }
            return {**without_clock(payload), "runtime": runtime}

        return {
            "profile": lambda: server.ATHLETE_DATA.profile().get(),
            "competitions": lambda: server.PLANNING_DATA.competition().list(limit=100),
            "feedback": lambda: public.feedback_state_service().feedback_state(),
            "plan_local": lambda: public.plan_state_service().read_public(
                local_only=True
            ),
            "weather_local": lambda: public.weather_state_service().state(
                local_only=True
            ),
            "nutrition_day": lambda: diary().sync_status.get_day_summary(day),
            "nutrition_range": lambda: diary().get_range_summary(day, day),
            "nutrition_week": lambda: diary().sync_status.get_week_summary(),
            "nutrition_templates": lambda: library().list_templates(),
            "nutrition_products": lambda: library().product_catalog.list_products(
                query=""
            ),
            "chat_status": lambda: (
                server.COACH_BACKGROUND_JOBS.job_submission_service().stream_status(
                    "csrf-hash"
                )
            ),
            "chat_history": lambda: server.HTTP_API.chat_history_page_service().page(
                limit=20, session_csrf_hash="csrf-hash"
            ),
            "chat_receipt": lambda: outcome(
                lambda: server.COACH_TURNS.command_receipt_service().read(
                    "missing-turn", "csrf-hash"
                )
            ),
            "proposals": lambda: server.COACH_PROPOSALS.read_service().current(
                "csrf-hash"
            ),
            "sync_jobs": lambda: server.SYNC_JOB_QUEUE.service().list(),
            "sync_job_state": lambda: outcome(
                lambda: server.SYNC_JOB_QUEUE.service().state("missing-job")
            ),
            "sync_status": lambda: public.sync_public_state_service().state(),
            "sync_browser_state": lambda: (
                public.sync_public_state_service().browser_state()
            ),
            "activities_page": lambda: server.ACTIVITY_READS.activity_read().page(
                limit=50, today=today
            ),
            "activities_recent": lambda: server.ACTIVITY_READS.activity_read().recent(
                today=today
            ),
            "activity_detail": lambda: outcome(
                lambda: server.ACTIVITY_READS.activity_read().detail(
                    "missing-activity",
                    garmin_status=NO_GARMIN_SYNC_STATUS,
                    profile={},
                    today=today,
                )
            ),
            "library_page": lambda: server.HTTP_API.library_page_service().page(
                limit=20
            ),
            "change_history": lambda: server.HISTORY.change_history_service().list(),
            "season": lambda: reports.season.season("UTC"),
            "derived_impact": lambda: reports.derived.impact("UTC"),
            "readiness": lambda: server.HTTP_API.readiness_service().state(),
            "privacy_preview": lambda: server.PRIVACY.delete_service().preview(),
            "privacy_export": lambda: archive_files(
                "profile.json", "athlete_checkins.jsonl"
            ),
            "diagnostic_report": lambda: without_process_measurements(
                server.DIAGNOSTICS.report_service().report()
            ),
            "coach_history_diagnostics": lambda: (
                server.DIAGNOSTICS.coach_history_service().history()
            ),
            "wahoo_status": lambda: server.WAHOO_CONNECTION.service().status(),
        }

    def test_other_moved_reads_are_not_blocked_and_stay_read_only(self) -> None:
        # Real rows, so a lazy write on a populated table would surface too.
        profile = server.ATHLETE_DATA.profile()
        profile.save({**profile.get(), "weather_location": "Berlin"})
        server.ATHLETE_DATA.checkin().save({"checkin_date": "2026-01-05"})
        calls = self.read_calls()
        expected = {name: call() for name, call in calls.items()}
        self.hold_writer()
        for name, call in calls.items():
            with self.subTest(read=name):
                self.assertEqual(self.call_while_held(call), expected[name])

    def test_a_foreground_write_is_served_before_a_waiting_background_write(
        self,
    ) -> None:
        """Nothing in front of the writer gate may hide a waiting foreground write."""
        manager = server.database_manager()
        gate = manager._writer_lock
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with manager.unit_of_work() as db:
                db.execute("UPDATE sessions SET last_seen=last_seen WHERE 0")
                held.set()
                release.wait(WAIT_SECONDS)

        def write(key: str, background: bool) -> None:
            if background:
                with background_writer():
                    server.key_value_service().set(key, "1")
            else:
                server.key_value_service().set(key, "1")

        def start(target, *args) -> threading.Thread:
            thread = threading.Thread(target=target, args=args, daemon=True)
            thread.start()
            return thread

        def wait_for(condition) -> bool:
            deadline = time.monotonic() + 5
            while not condition() and time.monotonic() < deadline:
                time.sleep(0.005)
            return condition()

        holder = start(hold)
        self.addCleanup(release.set)
        self.assertTrue(held.wait(5))
        background = start(write, "order.background", True)
        self.assertTrue(wait_for(lambda: gate._background_waiting == 1))
        foreground = start(write, "order.foreground", False)
        reached_gate = wait_for(lambda: gate._foreground_waiting == 1)
        release.set()
        for thread in (holder, background, foreground):
            thread.join(WAIT_SECONDS)
        self.assertTrue(reached_gate, "the foreground write never reached the gate")
        with manager.reader() as db:
            written = [
                row["key"]
                for row in db.execute(
                    "SELECT key FROM kv WHERE key LIKE 'order.%' ORDER BY rowid"
                )
            ]
        self.assertEqual(written, ["order.foreground", "order.background"])


if __name__ == "__main__":
    unittest.main()
