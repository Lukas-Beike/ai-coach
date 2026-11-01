"""Frozen detail targets match a planned unit from the activity summaries."""

from __future__ import annotations

import unittest
from typing import Any

from backend.planning.target_snapshot import freeze_targets

PLANNED = [
    {
        "local_id": "u1",
        "id": "u1",
        "name": "Sweet spot",
        "type": "Ride",
        "starts_at_local": "2026-10-08T07:00:00",
        "planned_duration_s": 3600,
        "description": "- 10m 60%\n- 20m 90%\n- 10m 55%",
        "target": "POWER",
        "status": "planned",
    }
]
SUMMARY: dict[str, Any] = {
    "id": "act_1",
    "record_ids": {"intervals": "i1"},
    "started_at_local": "2026-10-08T07:15:00",
    "sport": "ride",
    "environment": "outdoor",
    "moving_duration_s": 3500.0,
}
DETAIL = {"icu_ftp": 250}


class FreezeTargetsTests(unittest.TestCase):
    def test_unique_day_and_sport_freezes_the_targets_by_stored_key(self) -> None:
        frozen = freeze_targets(PLANNED, [SUMMARY], "i1", DETAIL, "2026-10-08T10:00Z")

        assert frozen is not None
        self.assertEqual("unique local date and sport", frozen["matching"])
        self.assertEqual(DETAIL, frozen["basis"])
        self.assertEqual(3, len(frozen["steps"]))

    def test_planned_event_pairing_is_the_provider_match(self) -> None:
        paired = {**SUMMARY, "planned_event_id": "u1"}

        frozen = freeze_targets(PLANNED, [paired], "i1", DETAIL, "2026-10-08T10:00Z")

        assert frozen is not None
        self.assertEqual("provider paired_event_id", frozen["matching"])

    def test_other_activity_freezes_nothing(self) -> None:
        self.assertIsNone(
            freeze_targets(PLANNED, [SUMMARY], "i2", DETAIL, "2026-10-08T10:00Z")
        )


if __name__ == "__main__":
    unittest.main()
