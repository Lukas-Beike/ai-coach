"""Contracts for the visible change summary of a Coach turn."""

from __future__ import annotations

import unittest
from typing import Any

from backend.coach.change_receipts import change_summary, turn_changes
from backend.coach.request_payload import model_confirmed_steps

_PROFILE_CHANGE = {
    "id": "change-1",
    "entity_type": "profile",
    "action": "update",
    "after_hash": "hash-1",
}
_LIBRARY_CHANGE = {
    "id": "change-2",
    "entity_type": "workout_library",
    "action": "create",
    "after_hash": "hash-2",
}


def _step(tool, result=None, changes=None):
    step = {"tool": tool, "result": {"ok": True} if result is None else result}
    if changes:
        step["changes"] = changes
    return step


class ChangeSummaryTests(unittest.TestCase):
    def test_applied_tracked_writes_are_listed_once_and_undoable(self) -> None:
        summary = change_summary(
            [
                _step("update_profile", changes=[_PROFILE_CHANGE]),
                _step("update_profile", changes=[_PROFILE_CHANGE]),
                _step(
                    "manage_training_templates",
                    {"ok": True, "templates": [{"id": "a"}, {"id": "b"}]},
                    [_LIBRARY_CHANGE],
                ),
            ]
        )

        self.assertEqual(
            summary,
            {
                "labels": ["Profil aktualisiert", "Trainingsvorlagen bearbeitet (2)"],
                "undoable": True,
                "undone_at": None,
            },
        )

    def test_a_write_without_history_makes_the_whole_turn_not_undoable(
        self,
    ) -> None:
        summary = change_summary(
            [
                _step("update_profile", changes=[_PROFILE_CHANGE]),
                _step("save_checkin"),
            ]
        )

        assert summary is not None
        self.assertEqual(
            summary["labels"], ["Profil aktualisiert", "Tages-Check-in gespeichert"]
        )
        self.assertFalse(summary["undoable"])

    def test_a_write_with_untracked_effects_is_listed_without_turn_undo(
        self,
    ) -> None:
        summary = change_summary(
            [
                _step("update_profile", changes=[_PROFILE_CHANGE]),
                _step("apply_training_patch", changes=[_LIBRARY_CHANGE]),
            ]
        )

        assert summary is not None
        self.assertEqual(len(summary["labels"]), 2)
        self.assertFalse(summary["undoable"])

    def test_an_applied_history_undo_is_listed_and_blocks_turn_undo(self) -> None:
        summary = change_summary(
            [
                _step("update_profile", changes=[_PROFILE_CHANGE]),
                _step("undo_training_change", {"ok": True, "status": "applied"}),
            ]
        )

        self.assertEqual(
            summary,
            {
                "labels": ["Profil aktualisiert", "Lokale Änderung zurückgenommen"],
                "undoable": False,
                "undone_at": None,
            },
        )

    def test_reads_failures_proposals_and_previews_are_not_changes(self) -> None:
        self.assertIsNone(
            change_summary(
                [
                    _step("get_training_context"),
                    _step("update_profile", {"ok": False, "error": "x"}),
                    _step(
                        "save_nutrition_template",
                        {"ok": True, "status": "approval_required"},
                    ),
                    _step("cancel_coach_request", {"ok": True, "status": "cancelled"}),
                    _step("preview_adaptive_replan", {"ok": True, "id": "preview"}),
                    _step("stage_training_plan"),
                    _step("undo_training_change", {"ok": True, "proposed_action": {}}),
                    _step("save_competition", "malformed"),
                    {"tool": "save_competition"},
                ]
            )
        )

    def test_turn_changes_keep_record_order_and_ignore_malformed_entries(
        self,
    ) -> None:
        receipts: list[Any] = [
            _step("update_profile", changes=[_PROFILE_CHANGE]),
            "malformed",
            {"tool": "x", "changes": "malformed"},
            _step("manage_training_templates", changes=[_LIBRARY_CHANGE]),
        ]

        self.assertEqual(turn_changes(receipts), [_PROFILE_CHANGE, _LIBRARY_CHANGE])

    def test_the_model_never_receives_undo_references(self) -> None:
        steps = [_step("update_profile", changes=[_PROFILE_CHANGE])]

        projected = model_confirmed_steps(steps)

        self.assertEqual(
            projected, [{"tool": "update_profile", "result": {"ok": True}}]
        )
        self.assertIn("changes", steps[0])


if __name__ == "__main__":
    unittest.main()
