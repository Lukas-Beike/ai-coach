"""Consumers of the session purpose: weekly volume and the activity detail."""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any, cast

from backend.performance.activity_read_service import _add_purpose
from backend.performance.progress_report import _bucket


def _session(session_id: str, purpose: str | None, seconds: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": session_id,
        "sport": "ride",
        "started_at_local": "2026-10-12T08:00:00",
        "moving_duration_s": seconds,
    }
    if purpose is not None:
        row["purpose"] = purpose
    return row


class WeeklyVolumeTests(unittest.TestCase):
    def test_commutes_count_in_volume_and_are_named_separately(self) -> None:
        sessions = [
            _session("act_1", None, 3600.0),
            _session("act_2", "commute", 1200.0),
            _session("act_3", "commute", 900.0),
        ]
        week = (date(2026, 10, 12), date(2026, 10, 18))

        bucket = _bucket(cast(Any, sessions), {}, None, week, "ride", "UTC")

        self.assertEqual(bucket["sessions"], 3)
        self.assertEqual(bucket["commute_sessions"], 2)
        self.assertEqual(bucket["commute_duration_s"]["value"], 2100.0)

    def test_a_week_without_commutes_keeps_its_shape(self) -> None:
        week = (date(2026, 10, 12), date(2026, 10, 18))
        bucket = _bucket(
            cast(Any, [_session("act_1", "race", 3600.0)]),
            {},
            None,
            week,
            "ride",
            "UTC",
        )

        self.assertNotIn("commute_sessions", bucket)


class DetailPurposeTests(unittest.TestCase):
    def test_detail_session_carries_purpose_link_and_source(self) -> None:
        session: dict[str, Any] = {"activity_id": "act_1"}
        summary = {
            "id": "act_1",
            "purpose": "race",
            "competition_id": "c-1",
            "sources": {"purpose": "Lokale Wettkämpfe"},
        }

        _add_purpose(session, cast(Any, summary))

        self.assertEqual(
            session,
            {
                "activity_id": "act_1",
                "purpose": "race",
                "competition_id": "c-1",
                "purpose_source": "Lokale Wettkämpfe",
            },
        )

    def test_detail_without_a_summary_or_purpose_is_unchanged(self) -> None:
        session: dict[str, Any] = {"activity_id": "act_1"}
        _add_purpose(session, None)
        _add_purpose(session, cast(Any, {"id": "act_1", "sources": {}}))

        self.assertEqual(session, {"activity_id": "act_1"})


if __name__ == "__main__":
    unittest.main()
