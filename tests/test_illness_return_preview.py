"""Stepwise illness return in the adaptive preview (#2042)."""

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.repositories import PlanAdjustmentRepository
from backend.planning import (
    adaptive,
    adaptive_preview_service,
    illness_return,
    illness_return_signals,
)
from backend.planning.adaptive_preview_service import (
    AdaptivePreviewLimits,
    AdaptiveReplanPreviewService,
)

GOOD_NIGHT = {
    "hrv": {"source": "Garmin", "value": 55, "position": "within"},
    "resting_hr": {"source": "Garmin", "value": 50, "median": 48},
}


class _Stub:
    def __init__(self, owner: IllnessReturnPreviewTests, name: str) -> None:
        self.owner, self.name = owner, name

    def context(self) -> dict[str, Any]:
        return {"today": self.owner.checkin}

    def list(self, limit: int, *, future_only: bool = False) -> Any:
        return self.owner.drafts

    def list_events(self, limit: int) -> Any:
        return []

    def state(self, **kwargs: Any) -> dict[str, Any]:
        return {"days": []}


class IllnessReturnPreviewTests(unittest.TestCase):
    today = date(2026, 9, 20)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = DatabaseManager(
            Path(self.temp.name) / "return.sqlite",
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
        self.checkin: dict[str, Any] = {}
        self.drafts: list[dict[str, Any]] = []
        self.night: dict[str, Any] = GOOD_NIGHT
        self.ids = 0
        self.set_day(self.today)
        # The pause ended 2026-09-16, so stage 1 runs from 2026-09-17.
        self.insert(
            "pause", {"illness_pause": self._pause()}, "2026-09-11T08:00:00+00:00"
        )

    def set_day(self, day: date) -> None:
        self.today = day
        self.checkin.clear()
        self.checkin.update(
            checkin_date=day.isoformat(), pain="", illness="", soreness=2
        )
        self.service = AdaptiveReplanPreviewService(
            self.manager,
            PlanAdjustmentRepository(),
            _Stub(self, "checkins"),
            _Stub(self, "planned"),
            _Stub(self, "calendar"),
            _Stub(self, "weather"),
            lambda: self.today,
            lambda: "2026-09-20T12:00:00+00:00",
            self._next_id,
            AdaptivePreviewLimits(56, 1000, adaptive.DEFAULT_ILLNESS_PAUSE_DAYS, 90),
            None,
            lambda: self.night,
        )

    @staticmethod
    def _pause() -> dict[str, Any]:
        return {
            "start_date": "2026-09-11",
            "end_date": "2026-09-16",
            "illness": "Infekt",
            "approved": True,
        }

    def _next_id(self) -> str:
        self.ids += 1
        return f"adjustment-{self.ids}"

    def insert(self, key: str, payload: dict[str, Any], created: str) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO plan_adjustments(id, payload, status, created_at) "
                "VALUES (?, ?, 'applied', ?)",
                (key, json.dumps(payload), created),
            )

    def apply_preview(self, preview: dict[str, Any], created: str) -> None:
        """Store the preview as approved, as the apply service marks it."""
        payload = {k: v for k, v in preview.items() if k not in {"id", "status"}}
        self.insert(f"applied-{preview['id']}", payload, created)

    def draft(self, focus: str, day: str | None = None, name: str = "Lauf") -> dict:
        draft = {
            "id": f"{name}-{focus}",
            "date": day or self.today.isoformat(),
            "name": name,
            "type": "Run",
            "duration_minutes": 50,
            "session_focus": focus,
        }
        self.drafts.append(draft)
        return draft

    def test_good_signals_after_two_days_propose_stage_two(self) -> None:
        preview = self.service.preview()

        block = preview["illness_return"]
        self.assertEqual(
            ("advance", 1, 2), (block["action"], block["from_stage"], block["stage"])
        )
        self.assertTrue(block["pending"])
        self.assertTrue(self.service.status()["illness_return_pending"])
        self.assertTrue(self.service.status()["needs_replan"])
        self.assertEqual(
            {"Check-in (lokal)", "Garmin"}, {e["source"] for e in block["evidence"]}
        )
        self.assertEqual("2026-09-20", block["state_after"]["since"])

    def test_one_day_into_the_stage_holds_and_proposes_nothing(self) -> None:
        self.set_day(date(2026, 9, 18))

        preview = self.service.preview()

        block = preview["illness_return"]
        self.assertEqual(("hold", ["stage_days"]), (block["action"], block["reasons"]))
        self.assertFalse(block["pending"])
        self.assertFalse(self.service.status()["needs_replan"])

    def test_low_hrv_holds_the_stage(self) -> None:
        self.night = {**GOOD_NIGHT, "hrv": {**GOOD_NIGHT["hrv"], "position": "below"}}

        block = self.service.preview()["illness_return"]

        self.assertEqual(
            ("hold", 1, ["hrv_below_range"]),
            (block["action"], block["stage"], block["reasons"]),
        )
        self.assertFalse(block["pending"])

    def test_high_resting_hr_holds_the_stage(self) -> None:
        self.night = {
            **GOOD_NIGHT,
            "resting_hr": {"source": "Garmin", "value": 55, "median": 48},
        }

        block = self.service.preview()["illness_return"]

        self.assertEqual(
            ("hold", ["resting_hr_high"]), (block["action"], block["reasons"])
        )

    def test_missing_overnight_values_let_the_check_in_decide(self) -> None:
        self.night = {}

        block = self.service.preview()["illness_return"]

        self.assertEqual(("advance", 2), (block["action"], block["stage"]))
        self.assertEqual(2, sum(1 for e in block["evidence"] if e.get("missing")))

    def test_new_complaint_steps_back_from_the_stored_stage(self) -> None:
        stage_two = {
            "pause_end": "2026-09-16",
            "stage": 2,
            "since": "2026-09-18",
            "history": [],
        }
        self.insert(
            "stage",
            {"illness_return": {"state_after": stage_two}},
            "2026-09-18T08:00:00+00:00",
        )
        self.checkin["pain"] = "Wade"

        block = self.service.preview()["illness_return"]

        self.assertEqual(("step_back", 1), (block["action"], block["stage"]))
        self.assertEqual("2026-09-20", block["state_after"]["since"])

    def test_applied_stage_is_the_stored_state_and_the_guard_stage(self) -> None:
        self.assertEqual(1, self.service.enforced_return_stage())
        self.apply_preview(self.service.preview(), "2026-09-20T12:00:00+00:00")

        self.assertEqual(2, self.service.enforced_return_stage())
        self.set_day(date(2026, 9, 21))
        self.assertEqual("hold", self.service.preview()["illness_return"]["action"])
        self.set_day(date(2026, 9, 22))
        block = self.service.preview()["illness_return"]
        self.assertEqual(("advance", 3), (block["action"], block["stage"]))
        self.apply_preview(self.service.preview(), "2026-09-22T12:00:00+00:00")
        self.assertIsNone(self.service.enforced_return_stage())

    def test_state_survives_more_than_a_hundred_newer_previews(self) -> None:
        with self.manager.unit_of_work() as db:
            for number in range(150):
                db.execute(
                    "INSERT INTO plan_adjustments(id, payload, status, created_at) "
                    "VALUES (?, '{}', 'preview', ?)",
                    (f"noise-{number}", f"2026-09-19T10:{number % 60:02d}:00+00:00"),
                )
        self.apply_preview(self.service.preview(), "2026-09-20T12:00:00+00:00")
        with self.manager.unit_of_work() as db:
            for number in range(150):
                db.execute(
                    "INSERT INTO plan_adjustments(id, payload, status, created_at) "
                    "VALUES (?, '{}', 'preview', ?)",
                    (f"later-{number}", f"2026-09-21T10:{number % 60:02d}:00+00:00"),
                )

        self.assertEqual(2, self.service.enforced_return_stage())
        self.assertIsNotNone(self.service.latest_illness_pause())

    def test_unapplied_preview_does_not_move_the_stage(self) -> None:
        self.service.preview()

        self.assertEqual(1, self.service.enforced_return_stage())

    def test_drafts_above_the_proposed_stage_get_local_easy_replacements(self) -> None:
        hard = self.draft("threshold", name="Intervalle")
        moderate = self.draft("endurance", "2026-09-21", name="Grundlage")
        far = self.draft("threshold", "2026-09-23", name="Spaeter")
        before = copy.deepcopy(self.drafts)

        preview = self.service.preview()

        changes = {c["library_workout_id"]: c for c in preview["changes"]}
        self.assertEqual({hard["id"]}, set(changes))
        change = changes[hard["id"]]
        self.assertEqual("easy", change["payload"]["session_focus"])
        self.assertLessEqual(change["payload"]["duration_minutes"], 60)
        self.assertIn("illness", change["blocking_triggers"])
        self.assertIn("return after illness", change["after"]["rationale"])
        self.assertNotIn(moderate["id"], changes)
        self.assertNotIn(far["id"], changes)
        self.assertEqual(before, self.drafts)

    def test_held_stage_still_replaces_sessions_above_it(self) -> None:
        self.night = {**GOOD_NIGHT, "hrv": {**GOOD_NIGHT["hrv"], "position": "below"}}
        moderate = self.draft("endurance")

        preview = self.service.preview()

        self.assertFalse(preview["illness_return"]["pending"])
        self.assertEqual(
            [moderate["id"]], [c["library_workout_id"] for c in preview["changes"]]
        )
        self.assertTrue(self.service.status()["needs_replan"])

    def test_new_illness_report_outranks_the_return(self) -> None:
        self.checkin["illness"] = "Grippe"

        preview = self.service.preview()

        self.assertIsNone(preview["illness_return"])
        self.assertFalse(preview["illness_pause"].get("approved"))

    def test_no_return_without_an_approved_pause_or_after_the_normal_plan(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM plan_adjustments")

        self.assertIsNone(self.service.preview()["illness_return"])
        self.assertIsNone(self.service.enforced_return_stage())

    def test_preview_stays_local_and_leaves_drafts_untouched(self) -> None:
        for module in (
            illness_return,
            illness_return_signals,
            adaptive_preview_service,
        ):
            source = Path(module.__file__ or "").read_text(encoding="utf-8")
            for forbidden in (
                "intervals_client",
                "import requests",
                "urllib",
                "import server",
            ):
                self.assertNotIn(forbidden, source)
        self.draft("threshold")
        before = copy.deepcopy(self.drafts)
        self.service.preview()
        self.assertEqual(before, self.drafts)


if __name__ == "__main__":
    unittest.main()
