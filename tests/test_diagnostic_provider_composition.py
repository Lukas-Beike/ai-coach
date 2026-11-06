"""Diagnostics count canonical sessions and observations by the providers backing them."""

from __future__ import annotations

import json
import tempfile
import unittest
from typing import Any
from unittest import mock

from canonical_detail_support import (
    NOW,
    add_session_record,
    open_manager,
    seed_intervals_activity,
)

from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager
from backend.diagnostics.provider_composition import summarize_provider_composition

_PRIVATE = "private athlete text"


def _add_raw_activity(
    manager: DatabaseManager, provider_activity_id: str, source: str
) -> None:
    with manager.unit_of_work() as db:
        db.execute(
            "INSERT INTO provider_records(provider, record_kind, source_record_id, "
            "payload, payload_hash, fetched_at, created_at, updated_at) "
            "VALUES ('intervals', 'activity', ?, ?, ?, ?, ?, ?)",
            (
                provider_activity_id,
                json.dumps({"source": source, "name": _PRIVATE}),
                "0" * 64,
                NOW,
                NOW,
                NOW,
            ),
        )


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

    def test_counts_sessions_by_providers_and_intervals_only_by_year_and_source(
        self,
    ) -> None:
        # Ingested the way a sync does: the raw payload names the source.
        seed_intervals_activity(self.manager, "i1", source="ZWIFT")
        seed_intervals_activity(
            self.manager, "i2", source="MANUAL", start_date_local="2021-03-01T07:00:00"
        )
        add_session_record(self.manager, ProviderId.INTERVALS, "i3", "act_i3")
        add_session_record(
            self.manager, ProviderId.GARMIN, "g3", "act_g3", merged_into="act_i3"
        )
        add_session_record(self.manager, ProviderId.GARMIN, "g4", "act_g4")
        # No raw record, and the Garmin record of the session is deleted.
        add_session_record(self.manager, ProviderId.INTERVALS, "i5", "act_i5")
        add_session_record(
            self.manager, ProviderId.GARMIN, "g5", "act_g5", merged_into="act_i5"
        )
        # A deleted session is not counted.
        add_session_record(self.manager, ProviderId.INTERVALS, "i6", "act_i6")
        # Two Intervals.icu copies of one double-tracked session.
        add_session_record(self.manager, ProviderId.INTERVALS, "i7", "act_i7")
        add_session_record(
            self.manager,
            ProviderId.INTERVALS,
            "i8",
            "act_i8",
            recorded_by="wahoo",
            merged_into="act_i7",
        )
        _add_raw_activity(self.manager, "i7", "GARMIN_CONNECT")
        _add_raw_activity(self.manager, "i8", "wahoo")
        # Free text outside the source enum is never reported.
        add_session_record(self.manager, ProviderId.INTERVALS, "i9", "act_i9")
        _add_raw_activity(self.manager, "i9", _PRIVATE)
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET state = 'deleted' "
                "WHERE provider_activity_id = 'g5'"
            )
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted' "
                "WHERE activity_id = 'act_i6'"
            )

        summary = self.summary()

        self.assertEqual(
            {
                "total": 7,
                "by_providers": {"garmin": 1, "garmin+intervals": 1, "intervals": 5},
                "intervals_only": {
                    "total": 5,
                    "by_year": {"2021": 1, "2026": 4},
                    "by_source": {
                        "GARMIN_CONNECT+WAHOO": 1,
                        "MANUAL": 1,
                        "ZWIFT": 1,
                        "other": 1,
                        "unknown": 1,
                    },
                    "by_year_and_source": {
                        "2021": {"MANUAL": 1},
                        "2026": {
                            "GARMIN_CONNECT+WAHOO": 1,
                            "ZWIFT": 1,
                            "other": 1,
                            "unknown": 1,
                        },
                    },
                },
            },
            summary["sessions"],
        )
        serialized = json.dumps(summary)
        for private in (_PRIVATE, "act_", "Ride i1", "2021-03-01", "2026-09-10"):
            self.assertNotIn(private, serialized)

    def test_counts_observation_days_only_intervals_holds(self) -> None:
        _add_observation(self.manager, "ctl", "intervals", "2024-01-01")
        _add_observation(self.manager, "ctl", "intervals", "2025-01-01")
        _add_observation(self.manager, "hrv_rmssd", "intervals", "2023-05-01")
        _add_observation(self.manager, "hrv_rmssd", "intervals", "2026-01-01")
        _add_observation(self.manager, "hrv_rmssd", "garmin", "2026-01-01")
        _add_observation(self.manager, "hrv_rmssd", "garmin", "2026-01-02")
        # A local value (no provider) on the same day is another source.
        _add_observation(self.manager, "ftp", "intervals", "2026-01-01", sport="ride")
        _add_observation(self.manager, "ftp", None, "2026-01-01", sport="ride")
        _add_observation(self.manager, "weight", "garmin", "2026-01-01")
        _add_observation(
            self.manager, "resting_hr", "intervals", "2026-01-01", state="retired"
        )
        # Text outside the vocabulary is only counted, never summed into a key.
        _add_observation(self.manager, _PRIVATE, "intervals", "2026-01-01")
        _add_observation(self.manager, "private_two", "intervals", "2026-01-01")
        _add_observation(self.manager, "ctl", "intervals", "2026-01-01", sport=_PRIVATE)

        summary = self.summary()["observations"]

        self.assertEqual(["ctl"], summary["only_from_intervals"])
        self.assertEqual(3, summary["unrecognized_kinds"])
        self.assertEqual(
            {
                "ctl": {
                    "intervals_days": 2,
                    "intervals_only_days": 2,
                    "other_days": 0,
                    "intervals_only_days_by_year": {"2024": 1, "2025": 1},
                },
                "ftp/ride": {
                    "intervals_days": 1,
                    "intervals_only_days": 0,
                    "other_days": 1,
                    "intervals_only_days_by_year": {},
                },
                "hrv_rmssd": {
                    "intervals_days": 2,
                    "intervals_only_days": 1,
                    "other_days": 2,
                    "intervals_only_days_by_year": {"2023": 1},
                },
            },
            summary["by_kind"],
        )
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
