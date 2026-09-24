from __future__ import annotations

import ast
import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.repositories import PlanAdjustmentRepository
from backend.planning import adaptive_preview_service
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService


class _Checkins:
    def __init__(self, feedback: dict):
        self.feedback = feedback

    def context(self):
        return {"today": self.feedback}


class _PlannedUnits:
    def __init__(self, drafts: list[dict]):
        self.drafts = drafts
        self.limits = []

    def list(self, limit):
        self.limits.append(limit)
        return self.drafts


class _Calendar:
    def __init__(self, events: list[dict]):
        self.events = events
        self.limits = []

    def list_events(self, limit):
        self.limits.append(limit)
        return self.events


class _Weather:
    def __init__(self, days: list[dict]):
        self.days = days
        self.calls = []

    def state(self, **kwargs):
        self.calls.append(kwargs)
        return {"days": self.days}


class AdaptiveReplanPreviewServiceTests(unittest.TestCase):
    today = date(2026, 9, 20)
    now_value = "2026-09-20T12:00:00+00:00"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = DatabaseManager(
            Path(self.temp_dir.name) / "adaptive-preview.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE plan_adjustments ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL, "
                "created_at TEXT NOT NULL, applied_at TEXT)"
            )
        self.repository = PlanAdjustmentRepository()
        self.feedback = {}
        self.drafts = []
        self.events = []
        self.weather_days = []
        self.checkins = _Checkins(self.feedback)
        self.planned = _PlannedUnits(self.drafts)
        self.calendar = _Calendar(self.events)
        self.weather = _Weather(self.weather_days)
        self.id_count = 0
        self.service = self.make_service()

    def make_service(self, repository=None):
        return AdaptiveReplanPreviewService(
            self.manager,
            repository or self.repository,
            self.checkins,
            self.planned,
            self.calendar,
            self.weather,
            lambda: self.today,
            lambda: self.now_value,
            self._next_id,
            56,
            1000,
            3,
            90,
        )

    def _next_id(self):
        self.id_count += 1
        return f"adjustment-{self.id_count}"

    def insert_adjustment(
        self, adjustment_id: str, payload: str, status: str, created_at: str
    ) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO plan_adjustments(id, payload, status, created_at) "
                "VALUES (?, ?, ?, ?)",
                (adjustment_id, payload, status, created_at),
            )

    def test_latest_preview_status_and_latest_illness_pause(self):
        self.insert_adjustment(
            "older",
            json.dumps({"illness_pause": {"illness": "Erkältung"}}),
            "applied",
            "2026-09-19T12:00:00+00:00",
        )
        self.insert_adjustment(
            "newer",
            json.dumps(
                {
                    "changes": [{"date": "2026-09-21"}],
                    "illness_pause": {"illness": "Infekt", "approved": False},
                }
            ),
            "preview",
            self.now_value,
        )

        self.assertEqual(
            self.service.latest_preview(),
            {
                "id": "newer",
                "status": "preview",
                "created_at": self.now_value,
                "applied_at": None,
                "changes": [{"date": "2026-09-21"}],
                "illness_pause": {"illness": "Infekt", "approved": False},
            },
        )
        self.assertEqual(
            self.service.status(),
            {
                "needs_replan": True,
                "replan_changes": 1,
                "illness_pause_pending": True,
            },
        )
        self.assertEqual(
            self.service.latest_illness_pause(),
            ("preview", {"illness": "Infekt", "approved": False}),
        )

    def test_corrupt_latest_payload_is_empty_and_invalid_illness_payload_is_skipped(
        self,
    ):
        self.insert_adjustment(
            "valid-pause",
            json.dumps({"illness_pause": {"illness": "Grippe"}}),
            "partial",
            "2026-09-18T12:00:00+00:00",
        )
        self.insert_adjustment(
            "corrupt-pause", "{not-json", "preview", "2026-09-19T12:00:00+00:00"
        )
        self.insert_adjustment("corrupt-latest", "[]", "preview", self.now_value)

        self.assertEqual(
            self.service.latest_preview(),
            {
                "id": "corrupt-latest",
                "status": "preview",
                "created_at": self.now_value,
                "applied_at": None,
            },
        )
        self.assertEqual(
            self.service.status(),
            {
                "needs_replan": False,
                "replan_changes": 0,
                "illness_pause_pending": False,
            },
        )
        self.assertEqual(
            self.service.latest_illness_pause(),
            ("partial", {"illness": "Grippe"}),
        )

    def test_preview_without_changes_only_includes_future_local_drafts(self):
        self.drafts.extend(
            [
                {
                    "id": "past",
                    "date": "2026-09-19",
                    "name": "Threshold run",
                    "duration_minutes": 60,
                },
                {
                    "id": "future",
                    "date": "2026-09-21",
                    "name": "Easy run",
                    "sport": "Run",
                    "duration_minutes": 30,
                },
            ]
        )

        result = self.service.preview()

        self.assertEqual(result["changes"], [])
        self.assertEqual(
            result["message"],
            "Keine zukünftigen lokalen Einheiten müssen angepasst werden.",
        )
        self.assertIsNone(result["illness_pause"])
        self.assertEqual(self.planned.limits, [500])
        self.assertEqual(self.calendar.limits, [1000])
        self.assertEqual(self.weather.calls, [{"refresh": False}])
        self.assertEqual(self.id_count, 1)

    def test_combined_illness_calendar_weather_preview_keeps_triggers_and_fingerprint(
        self,
    ):
        target = "2026-09-21"
        draft = {
            "id": "ride-1",
            "date": target,
            "name": "Threshold Ride",
            "type": "Ride",
            "duration_minutes": 210,
            "description": "Intervals outdoors",
            "target": "POWER",
        }
        event = {
            "name": "Family appointment",
            "event_date": target,
            "start_local": f"{target}T10:00:00",
            "end_local": f"{target}T14:00:00",
            "duration_minutes": 240,
            "training_relevant": True,
            "no_intensity": True,
            "short_only": False,
        }
        self.feedback.update(
            {
                "checkin_date": self.today.isoformat(),
                "illness": "Infekt",
                "pain": "Knee pain",
                "soreness": 9,
                "stress": 8,
                "motivation": 1,
                "available_minutes": 120,
            }
        )
        self.drafts.append(draft)
        self.events.append(event)
        self.weather_days.append(
            {
                "date": target,
                "weather_code": 63,
                "precipitation_probability_max": 70,
                "rain_sum": 3,
            }
        )
        before = copy.deepcopy(
            (self.feedback, self.drafts, self.events, self.weather_days)
        )

        result = self.service.preview()

        self.assertEqual(
            result["signals"],
            [
                "illness reported",
                "pain/injury reported",
                "high soreness",
                "high subjective stress",
                "low motivation",
                f"family calendar on {target}: 1 event(s)",
            ],
        )
        self.assertEqual(result["illness_pause"]["start_date"], self.today.isoformat())
        self.assertEqual(result["illness_pause"]["end_date"], "2026-09-22")
        self.assertEqual(
            result["message"],
            "Krankheitsprognose: 3 Tage Sportpause bis 2026-09-22. 1 zukünftige lokale Einheit(en) brauchen eine Prüfung.",
        )
        self.assertEqual(len(result["changes"]), 1)
        change = result["changes"][0]
        self.assertEqual(
            change["blocking_triggers"], ["illness", "injury", "calendar", "weather"]
        )
        self.assertEqual(
            change["source_fingerprint"],
            adaptive_preview_service.adaptive.adaptive_workout_fingerprint(draft),
        )
        self.assertIn("private_calendar_adjustment", change["payload"])
        self.assertEqual(
            change["payload"]["private_calendar_adjustment"]["events"][0]["name"],
            "Family appointment",
        )
        self.assertTrue(change["payload"]["archived"])
        self.assertEqual(
            (self.feedback, self.drafts, self.events, self.weather_days), before
        )

    def test_existing_applied_matching_illness_pause_is_approved(self):
        self.feedback.update(
            {"checkin_date": self.today.isoformat(), "illness": "Infekt"}
        )
        self.drafts.append(
            {
                "id": "today-ride",
                "date": self.today.isoformat(),
                "name": "Easy ride",
                "type": "Ride",
                "duration_minutes": 45,
            }
        )
        self.insert_adjustment(
            "applied-pause",
            json.dumps(
                {
                    "illness_pause": {
                        "start_date": self.today.isoformat(),
                        "end_date": "2026-09-22",
                        "illness": "Infekt",
                    }
                }
            ),
            "applied",
            "2026-09-19T12:00:00+00:00",
        )

        result = self.service.preview()

        self.assertTrue(result["illness_pause"]["approved"])
        self.assertEqual(result["changes"], [])
        self.assertFalse(self.service.status()["illness_pause_pending"])

    def test_preview_persists_once_and_reads_back(self):
        class CountingRepository(PlanAdjustmentRepository):
            def __init__(self):
                self.created = 0

            def create_preview(self, db, adjustment_id, payload, created_at):
                self.created += 1
                super().create_preview(db, adjustment_id, payload, created_at)

        repository = CountingRepository()
        service = self.make_service(repository)

        result = service.preview()

        self.assertEqual(repository.created, 1)
        readback = service.latest_preview()
        self.assertEqual(readback["id"], result["id"])
        self.assertEqual(readback["status"], "preview")
        self.assertIsNone(readback["applied_at"])
        for key, value in result.items():
            self.assertEqual(readback[key], value)

    def test_create_preview_failure_rolls_back_partial_insert(self):
        class FailingRepository(PlanAdjustmentRepository):
            def create_preview(self, db, adjustment_id, payload, created_at):
                super().create_preview(db, adjustment_id, payload, created_at)
                raise RuntimeError("insert failed after write")

        service = self.make_service(FailingRepository())

        with self.assertRaisesRegex(RuntimeError, "insert failed"):
            service.preview()

        with self.manager.unit_of_work() as db:
            self.assertIsNone(self.repository.latest(db))

    def test_service_imports_no_server_provider_or_event_modules(self):
        source = Path(adaptive_preview_service.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )

        self.assertFalse(
            any(
                module == "server"
                or module.startswith("server.")
                or ".providers" in module
                or ".events" in module
                or module.endswith(".event")
                for module in imported_modules
            ),
            imported_modules,
        )


if __name__ == "__main__":
    unittest.main()
