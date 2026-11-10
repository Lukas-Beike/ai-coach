"""Diagnostics count canonical sessions and observations by the providers backing them."""

from __future__ import annotations

import json
import tempfile
import unittest
from typing import Any
from unittest import mock

from canonical_detail_support import NOW, add_session_record, open_manager

from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager
from backend.diagnostics.provider_composition import summarize_provider_composition

_PRIVATE = "private athlete text"


def _add_observation(
    manager: DatabaseManager,
    metric: str,
    provider: str | None,
    observed_on: str,
    *,
    sport: str | None = None,
    state: str = "active",
) -> None:
    with manager.unit_of_work() as db:
        db.execute(
            "INSERT INTO observations(natural_key, metric, value, unit, source_kind, "
            "recorded_by, provider, sport, observed_on, mapper_version, state, "
            "created_at, updated_at) "
            "VALUES (?, ?, 1, 'x', 'provider_reported', 'garmin', ?, ?, ?, 1, ?, ?, ?)",
            (
                f"{metric}|{provider}|{sport}|{observed_on}",
                metric,
                provider,
                sport,
                observed_on,
                state,
                NOW,
                NOW,
            ),
        )


def _add_zone(
    manager: DatabaseManager, key: str, provider: str | None, state: str = "active"
) -> None:
    with manager.unit_of_work() as db:
        db.execute(
            "INSERT INTO zone_configurations(config_key, provider, metric, "
            "source_kind, recorded_by, state, created_at, updated_at) "
            "VALUES (?, ?, 'power', 'provider_reported', 'garmin', ?, ?, ?)",
            (key, provider, state, NOW, NOW),
        )


class ProviderCompositionDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)

    def summary(self) -> dict[str, Any]:
        with self.manager.read_snapshot() as db:
            return summarize_provider_composition(db)

    def test_counts_sessions_by_the_providers_of_their_active_records(self) -> None:
        add_session_record(self.manager, ProviderId.GARMIN, "g1", "act_g1")
        add_session_record(self.manager, ProviderId.GARMIN, "g2", "act_g2")
        add_session_record(self.manager, ProviderId.WAHOO, "w1", "act_w1")
        add_session_record(
            self.manager, ProviderId.GARMIN, "g3", "act_g3", merged_into="act_w1"
        )
        # The Garmin record of this session is deleted, a deleted session is not counted.
        add_session_record(self.manager, ProviderId.WAHOO, "w2", "act_w2")
        add_session_record(
            self.manager, ProviderId.GARMIN, "g4", "act_g4", merged_into="act_w2"
        )
        add_session_record(self.manager, ProviderId.GARMIN, "g5", "act_g5")
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET state = 'deleted' "
                "WHERE provider_activity_id = 'g4'"
            )
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted' "
                "WHERE activity_id = 'act_g5'"
            )

        summary = self.summary()

        self.assertEqual(
            {"total": 4, "by_providers": {"garmin": 2, "garmin+wahoo": 1, "wahoo": 1}},
            summary["sessions"],
        )
        serialized = json.dumps(summary)
        for private in ("act_", "2026-09-10"):
            self.assertNotIn(private, serialized)

    def test_no_intervals_only_subsection_remains(self) -> None:
        summary = self.summary()

        self.assertNotIn("intervals_only", summary["sessions"])
        self.assertEqual({"unrecognized_kinds": 0}, summary["observations"])
        self.assertNotIn("intervals_only", json.dumps(summary))
        self.assertNotIn("only_from_intervals", json.dumps(summary))

    def test_counts_observation_kinds_outside_the_vocabulary_without_naming_them(
        self,
    ) -> None:
        _add_observation(self.manager, "ctl", "garmin", "2024-01-01")
        _add_observation(self.manager, "ftp", None, "2026-01-01", sport="ride")
        _add_observation(
            self.manager, "resting_hr", "garmin", "2026-01-01", state="retired"
        )
        # Text outside the vocabulary is only counted, never reported.
        _add_observation(self.manager, _PRIVATE, "garmin", "2026-01-01")
        _add_observation(self.manager, "private_two", "garmin", "2026-01-01")
        _add_observation(self.manager, "private_two", "garmin", "2026-01-02")
        _add_observation(self.manager, "ctl", "garmin", "2026-01-01", sport=_PRIVATE)

        summary = self.summary()["observations"]

        self.assertEqual({"unrecognized_kinds": 3}, summary)
        serialized = json.dumps(summary)
        for private in (_PRIVATE, "private_two"):
            self.assertNotIn(private, serialized)

    def test_a_failing_query_reports_unavailable(self) -> None:
        failing = mock.Mock()
        failing.execute.side_effect = RuntimeError("private failure text")

        self.assertEqual(
            {"status": "unavailable"}, summarize_provider_composition(failing)
        )

    def test_counts_active_domain_rows_per_provider(self) -> None:
        _add_zone(self.manager, "z1", "intervals")
        _add_zone(self.manager, "z2", None)
        _add_zone(self.manager, "z3", "garmin", state="retired")
        _add_zone(self.manager, "z4", _PRIVATE)

        self.assertEqual(
            {
                "sleep_periods": {},
                "zone_configurations": {"intervals": 1, "local": 1, "other": 1},
                "power_curve_points": {},
            },
            self.summary()["domain_rows"],
        )


if __name__ == "__main__":
    unittest.main()
