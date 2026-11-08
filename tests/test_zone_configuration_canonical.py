"""Canonical zone configurations drive zones; local edits win and can be undone.

The Intervals.icu sport settings mapped to canonical configurations choose the
same zones as the snapshot settings did. A confirmed local configuration wins on
the days it is valid, survives a provider refresh and is restored by undo. The
calendar reads the configurations without a provider snapshot. Temporary
database and synthetic settings only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from intervals_compaction import compact_sport_settings
from zone_settings_reference import (
    canonical_sport_inputs,
    canonical_zone_settings,
    legacy_sport_settings,
)

from backend import change_history
from backend.activities.zone_settings import ZoneSettings
from backend.athlete.zones import ZoneConfigurationService, local_configuration
from backend.canonical.vocabulary import Environment, ProviderId, Sport
from backend.coach.context import CoachStructuredContextService, coach_training_zones
from backend.db import DatabaseManager, canonical_domain_store, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.planning import calendar_read_model
from backend.providers.intervals_zone_mapping import map_intervals_zone_configurations
from backend.sync.canonical_table_reader import CanonicalTableReader

RETRIEVED_AT = datetime(2026, 10, 11, 6, tzinfo=UTC)
NOW = "2026-10-11T06:00:00+00:00"
RIDE = {
    "types": ["Ride", "VirtualRide"],
    "ftp": 260,
    "indoor_ftp": 250,
    "lthr": 168,
    "max_hr": 190,
    "power_zones": [55, 75, 90, 105, 120, 150, 999],
    "hr_zones": [137, 153, 159, 168, 174, 179, 190],
}
RUN = {
    "types": ["Run"],
    "lthr": 172,
    "max_hr": 194,
    "threshold_pace": 4.2,
    "hr_zones": [140, 155, 163, 172, 180, 194],
    "pace_zones": [77.5, 87.7, 94.3, 100, 103.4, 111.5, 999],
}
SWIM = {"types": ["Swim"], "pace_zones": [80, 90, 100, 110, 999]}
ATHLETE = {"sportSettings": [RIDE, RUN, SWIM]}
LOCAL_POWER = {
    "sport": "ride",
    "metric": "power",
    "threshold": 280,
    "percent_limits": [50, 70, 85, 100, 115, 140, 999],
}


def provider_configurations(athlete: dict[str, Any] = ATHLETE) -> tuple:
    return map_intervals_zone_configurations(
        athlete, source_record_id="athlete", retrieved_at=RETRIEVED_AT
    )


class EffectiveZoneTests(unittest.TestCase):
    def test_provider_configurations_choose_the_snapshot_zones(self) -> None:
        settings = compact_sport_settings(ATHLETE)
        configurations = provider_configurations()
        for sport in (Sport.RIDE, Sport.RUN, Sport.SWIM):
            for environment in Environment:
                with self.subTest(sport=sport, environment=environment):
                    legacy = legacy_sport_settings(settings, sport, environment)
                    # An Intervals.icu configuration gives its limits only; its
                    # thresholds are never a source.
                    self.assertEqual(
                        ZoneSettings.from_configurations(
                            configurations, sport, environment
                        ),
                        replace(legacy, ftp=None, lthr=None, max_hr=None),
                    )
                    # The Intervals.icu indoor FTP is never read: an indoor workout
                    # uses the sport FTP.
                    outdoor = legacy_sport_settings(
                        settings, sport, Environment.UNKNOWN
                    )
                    self.assertEqual(
                        canonical_zone_settings(
                            ATHLETE["sportSettings"], sport, environment
                        ),
                        replace(legacy, ftp=outdoor.ftp),
                    )

    def test_a_local_configuration_wins_on_its_valid_days(self) -> None:
        local = local_configuration({**LOCAL_POWER, "valid_from": "2026-11-01"})
        configurations = (*provider_configurations(), local)
        before = ZoneSettings.from_configurations(
            configurations, Sport.RIDE, Environment.INDOOR, date(2026, 10, 31)
        )
        after = ZoneSettings.from_configurations(
            configurations, Sport.RIDE, Environment.INDOOR, date(2026, 11, 1)
        )
        self.assertEqual((before.ftp, before.power_limits[0]), (None, 55))
        self.assertEqual(
            (after.ftp, after.power_limits), (280, (50, 70, 85, 100, 115, 140))
        )
        # Heart-rate limits still come from the provider, its threshold does not.
        self.assertIsNone(after.lthr)
        self.assertTrue(after.hr_limits)

    def test_absolute_local_limits_become_percent_of_the_threshold(self) -> None:
        local = local_configuration(
            {
                "sport": "run",
                "metric": "heart_rate",
                "threshold": 160,
                "maximum": 190,
                "limits": [120, 140, 152, 160, 168, 190],
            }
        )
        settings = ZoneSettings.from_configurations((local,), Sport.RUN)
        self.assertEqual((settings.lthr, settings.max_hr), (160, 190))
        self.assertEqual(settings.hr_limits, (75, 87.5, 95, 100, 105))

    def test_the_calendar_reads_canonical_zones_without_a_snapshot(self) -> None:
        planned = {
            "id": "p1",
            "date": "2026-10-12",
            "type": "Ride",
            "name": "Threshold",
            "description": "- 10m 280w",
        }

        def zone(configurations: tuple) -> Any:
            projection = calendar_read_model.project_planning_calendar(
                [planned],
                [],
                {},
                [],
                [],
                today=date(2026, 10, 11),
                provider_window={},
                default_name="Workout",
                zone_configurations=configurations,
            )
            (row,) = projection["planned"]
            return row["workout_profile"]["segments"][0]["zone"]

        local = local_configuration(LOCAL_POWER)
        # An Intervals.icu configuration gives no threshold, so only the local one
        # colors the step.
        self.assertIsNone(zone(provider_configurations()))
        self.assertEqual(zone((*provider_configurations(), local)), 4)

    def test_a_missing_power_list_keeps_the_canonical_ride_ftp(self) -> None:
        heart_rate_only = {"types": ["Ride"], "lthr": 168, "hr_zones": RIDE["hr_zones"]}
        _, thresholds = canonical_sport_inputs(
            {"sportSettings": [{**RIDE, "types": ["Ride"]}]}
        )
        planned = {
            "id": "p1",
            "date": "2026-10-12",
            "type": "Ride",
            "name": "Threshold",
            "description": "- 10m 280w",
        }
        projection = calendar_read_model.project_planning_calendar(
            [planned],
            [],
            {},
            [],
            [],
            today=date(2026, 10, 11),
            provider_window={},
            default_name="Workout",
            sport_thresholds=thresholds,
            zone_configurations=provider_configurations(
                {"sportSettings": [heart_rate_only]}
            ),
        )
        (row,) = projection["planned"]
        self.assertEqual(row["workout_profile"]["segments"][0]["zone"], 5)


class CoachZoneTests(unittest.TestCase):
    def test_the_coach_sees_the_zones_in_effect_with_their_source(self) -> None:
        local = local_configuration(LOCAL_POWER)
        future = local_configuration(
            {
                **LOCAL_POWER,
                "metric": "heart_rate",
                "threshold": 160,
                "valid_from": "2026-12-01",
                "percent_limits": None,
                "limits": [120, 140, 150, 160, 170, 190],
            }
        )
        zones = coach_training_zones(
            (*provider_configurations(), local, future), date(2026, 10, 12)
        )
        ride = {
            (z["metric"], z.get("environment")): z
            for z in zones
            if z["sport"] == "ride"
        }
        # The local power zones apply indoors too, so no indoor entry is listed.
        self.assertEqual(set(ride), {("power", None), ("heart_rate", None)})
        self.assertEqual(
            (ride["power", None]["source"], ride["power", None]["threshold"]),
            ("local", 280),
        )
        self.assertEqual(ride["heart_rate", None]["source"], "intervals")

    def test_current_performance_carries_the_training_zones(self) -> None:
        performance = Mock()
        performance.current_performance.return_value = {"ftp": 260}
        service = CoachStructuredContextService(
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            performance,
            zone_configurations=provider_configurations,
            today=lambda: date(2026, 10, 12),
        )
        current = service._current_performance(None)
        self.assertEqual(current["ftp"], 260)
        self.assertIn(
            {"sport": "run", "metric": "pace", "source": "intervals"},
            [
                {k: z[k] for k in ("sport", "metric", "source")}
                for z in current["training_zones"]
            ],
        )

    def test_current_performance_carries_the_threshold_warning(self) -> None:
        performance = Mock()
        performance.current_performance.return_value = {"ftp": 260}
        warning: dict[str, Any] = {
            "stale_after_days": 56,
            "sdk_failure": None,
            "items": [{}],
        }

        def service(read):
            return CoachStructuredContextService(
                Mock(), Mock(), Mock(), Mock(), performance, threshold_warnings=read
            )

        self.assertEqual(
            service(lambda: warning)._current_performance(None)["threshold_warnings"],
            warning,
        )
        self.assertNotIn(
            "threshold_warnings", service(lambda: None)._current_performance(None)
        )


class LocalZoneEditTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "zones.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            self.refresh(db)
        self.zone_changes: list[bool] = []
        self.service = ZoneConfigurationService(
            self.manager,
            CanonicalTableReader(),
            lambda: NOW,
            on_change=lambda: self.zone_changes.append(True),
        )
        unused: Any = None
        self.undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, unused, self.service),
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            zone_service=self.service,
            profile_mutation_coordinator=threading.RLock(),
        )

    @staticmethod
    def refresh(db: Any, athlete: dict[str, Any] = ATHLETE) -> None:
        canonical_domain_store.replace_zone_configurations(
            db,
            provider=ProviderId.INTERVALS,
            source_record_id="athlete",
            configurations=provider_configurations(athlete),
            mapper_version=1,
            now=NOW,
        )

    def local(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.service.read()["configurations"]
            if row["source"] == "local"
        ]

    def history_rows(self) -> int:
        with self.manager.reader() as db:
            return db.execute("SELECT COUNT(*) AS n FROM change_history").fetchone()[
                "n"
            ]

    def test_save_keeps_provider_alternatives_and_survives_a_refresh(self) -> None:
        receipt = self.service.save(LOCAL_POWER)
        self.assertEqual(receipt["change"]["action"], "create")
        with self.manager.unit_of_work() as db:
            self.refresh(db, {"sportSettings": [{**RIDE, "ftp": 300}]})
        (local,) = self.local()
        self.assertEqual(local["threshold"], 280)
        sources = {row["source"] for row in self.service.read()["configurations"]}
        self.assertEqual(sources, {"local", "intervals"})
        settings = ZoneSettings.from_configurations(
            self.service.configurations(), Sport.RIDE
        )
        self.assertEqual(settings.ftp, 280)

    def test_undo_restores_the_previous_local_state_after_a_refresh(self) -> None:
        self.service.save(LOCAL_POWER)
        update = self.service.save({**LOCAL_POWER, "threshold": 290})["change"]
        with self.manager.unit_of_work() as db:
            self.refresh(db)
        self.undo.apply(
            {"change_id": update["id"], "expected_current_hash": update["after_hash"]}
        )
        (local,) = self.local()
        self.assertEqual(local["threshold"], 280)
        self.assertTrue(
            any(
                row["source"] == "intervals"
                for row in self.service.read()["configurations"]
            )
        )

    def test_read_carries_the_threshold_warning_only_when_present(self) -> None:
        self.assertNotIn("threshold_warnings", self.service.read())
        warning: dict[str, Any] = {
            "stale_after_days": 56,
            "sdk_failure": None,
            "items": [{}],
        }
        service = ZoneConfigurationService(
            self.manager,
            CanonicalTableReader(),
            lambda: NOW,
            threshold_warnings=lambda: warning,
        )
        self.assertEqual(service.read()["threshold_warnings"], warning)

    def test_committed_save_and_removal_notify_the_change_hook(self) -> None:
        calls: list[bool] = []
        service = ZoneConfigurationService(
            self.manager,
            CanonicalTableReader(),
            lambda: NOW,
            on_change=lambda: calls.append(True),
        )
        key = service.save(LOCAL_POWER)["configuration"]["key"]
        self.assertEqual(calls, [True])
        with self.assertRaises(AppError):
            service.remove({"key": key})
        self.assertEqual(calls, [True])
        service.remove({"key": key, "confirmed": True})
        self.assertEqual(calls, [True, True])

    def test_undo_of_a_zone_change_requests_a_local_load_pass(self) -> None:
        change = self.service.save(LOCAL_POWER)["change"]
        self.assertEqual(self.zone_changes, [True])
        self.undo.apply(
            {"change_id": change["id"], "expected_current_hash": change["after_hash"]}
        )
        self.assertEqual(self.zone_changes, [True, True])

    def _clocked(self) -> tuple[ZoneConfigurationService, list[str]]:
        clock = ["2026-08-01T06:00:00+00:00"]
        service = ZoneConfigurationService(
            self.manager, CanonicalTableReader(), lambda: clock[0]
        )
        unused: Any = None
        self.undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, unused, service),
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            zone_service=service,
            profile_mutation_coordinator=threading.RLock(),
        )
        return service, clock

    def _saved_day(self, key: str) -> date:
        with self.manager.reader() as db:
            return canonical_domain_store.local_zone_saved_days(db)[key]

    def _undo(self, change: dict[str, Any]) -> None:
        self.undo.apply(
            {"change_id": change["id"], "expected_current_hash": change["after_hash"]}
        )

    def test_undo_restores_the_save_date_of_the_restored_value(self) -> None:
        service, clock = self._clocked()
        key = service.save(LOCAL_POWER)["configuration"]["key"]
        clock[0] = "2026-11-07T06:00:00+00:00"
        self._undo(service.save({**LOCAL_POWER, "threshold": 300})["change"])
        self.assertEqual(self._saved_day(key), date(2026, 8, 1))

    def test_undo_keeps_a_re_confirmation_date(self) -> None:
        service, clock = self._clocked()
        key = service.save(LOCAL_POWER)["configuration"]["key"]
        clock[0] = "2026-11-01T06:00:00+00:00"
        service.save(LOCAL_POWER)
        self.assertEqual(self._saved_day(key), date(2026, 11, 1))
        clock[0] = "2026-11-07T06:00:00+00:00"
        self._undo(service.save({**LOCAL_POWER, "threshold": 300})["change"])
        self.assertEqual(self._saved_day(key), date(2026, 11, 1))

    def test_re_confirming_a_changed_value_keeps_the_replaced_date(self) -> None:
        service, clock = self._clocked()
        key = service.save(LOCAL_POWER)["configuration"]["key"]
        clock[0] = "2026-11-01T06:00:00+00:00"
        change = service.save({**LOCAL_POWER, "threshold": 300})["change"]
        for day in ("2026-11-02", "2026-11-03"):
            clock[0] = f"{day}T06:00:00+00:00"
            service.save({**LOCAL_POWER, "threshold": 300})
        self.assertEqual(self._saved_day(key), date(2026, 11, 3))
        self._undo(change)
        self.assertEqual(self._saved_day(key), date(2026, 8, 1))

    def test_undoing_a_removal_restores_the_removed_save_date(self) -> None:
        service, clock = self._clocked()
        key = service.save(LOCAL_POWER)["configuration"]["key"]
        clock[0] = "2026-11-07T06:00:00+00:00"
        self._undo(service.remove({"key": key, "confirmed": True})["change"])
        self.assertEqual(self._saved_day(key), date(2026, 8, 1))

    def test_removal_needs_confirmation_and_can_be_undone(self) -> None:
        key = self.service.save(LOCAL_POWER)["configuration"]["key"]
        with self.assertRaises(AppError):
            self.service.remove({"key": key})
        removal = self.service.remove({"key": key, "confirmed": True})["change"]
        self.assertEqual(self.local(), [])
        self.undo.apply(
            {"change_id": removal["id"], "expected_current_hash": removal["after_hash"]}
        )
        (local,) = self.local()
        self.assertEqual(local["percent_limits"], LOCAL_POWER["percent_limits"])

    def test_an_invalid_edit_changes_nothing(self) -> None:
        self.service.save(LOCAL_POWER)
        before = (self.local(), self.history_rows())
        for payload in (
            {**LOCAL_POWER, "percent_limits": [50, 40, 85, 100]},
            {**LOCAL_POWER, "percent_limits": [50, 70]},
            {**LOCAL_POWER, "metric": "speed"},
            {**LOCAL_POWER, "limits": [100, 200, 300]},
            {**LOCAL_POWER, "threshold": "280"},
            {**LOCAL_POWER, "threshold": None},
            {**LOCAL_POWER, "threshold": 10**400},
            {
                "sport": "run",
                "metric": "heart_rate",
                "limits": [120, 140, 152, 160, 168, 190],
            },
        ):
            with self.subTest(payload=payload), self.assertRaises(AppError):
                self.service.save(payload)
        self.assertEqual((self.local(), self.history_rows()), before)

    def test_history_shows_no_zone_values(self) -> None:
        self.service.save(LOCAL_POWER)
        (row,) = self._history()
        self.assertEqual(row["entity_type"], "zone_configuration")
        self.assertNotIn("280", str(row["diff"]))

    def _history(self) -> list[dict[str, Any]]:
        with self.manager.reader() as db:
            rows = db.execute("SELECT * FROM change_history").fetchall()
        return [change_history.public_view(dict(row)) for row in rows]


if __name__ == "__main__":
    unittest.main()
