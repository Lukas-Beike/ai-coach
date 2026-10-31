"""Plan zones read canonical thresholds, not the snapshot sport settings (#1416).

Over the shared populated fixture the canonical zone configurations plus the
latest sync's sport-scoped FTP, threshold HR and maximum HR give the zone
settings the stored snapshot's ``sport_settings`` gave, for every sport and
environment. Before the first backfill the tables serve no thresholds. All
storage is temporary and providers are mocked.
"""

from __future__ import annotations

import unittest
from datetime import date

from canonical_read_support import CanonicalReadFixture, make_selector, populate
from zone_settings_reference import legacy_zone_settings

from backend.activities.zone_settings import ZoneSettings
from backend.canonical.vocabulary import Environment, MetricKind, Sport
from backend.performance.canonical_inputs import (
    CanonicalPerformanceSource,
    sport_thresholds,
)
from backend.planning.calendar_read_model import project_planning_calendar

SPORTS = (Sport.RIDE, Sport.RUN, Sport.SWIM)


class PlanZoneParityTests(CanonicalReadFixture):
    def _thresholds(self) -> tuple:
        selector = make_selector(self)
        return sport_thresholds(
            CanonicalPerformanceSource(lambda: self.manager, lambda: selector)
        )

    def test_canonical_thresholds_give_the_snapshot_zone_settings(self) -> None:
        populate(self)
        thresholds = self._thresholds()
        configurations = self.read(self.table.zone_configurations)
        settings = self.intervals["athlete"]["sport_settings"]
        self.assertTrue(thresholds)
        for sport in SPORTS:
            for environment in Environment:
                with self.subTest(sport=sport, environment=environment):
                    self.assertEqual(
                        ZoneSettings.from_configurations(
                            configurations,
                            sport,
                            environment,
                            fallback=ZoneSettings.from_thresholds(thresholds, sport),
                        ),
                        legacy_zone_settings(
                            settings, configurations, sport, environment
                        ),
                    )
        ride = ZoneSettings.from_thresholds(thresholds, Sport.RIDE)
        self.assertEqual((ride.ftp, ride.lthr, ride.max_hr), (260, 168, 190))

    def test_the_calendar_colors_plan_steps_from_canonical_thresholds(self) -> None:
        populate(self)
        planned = {
            "id": "p1",
            "date": "2026-10-12",
            "type": "Ride",
            "name": "Threshold",
            "description": "- 10m 280w",
        }

        def zone(thresholds: tuple) -> int | None:
            projection = project_planning_calendar(
                [planned],
                [],
                {},
                [],
                [],
                today=date(2026, 10, 11),
                provider_window={},
                default_name="Workout",
                sport_thresholds=thresholds,
            )
            (row,) = projection["planned"]
            return row["workout_profile"]["segments"][0]["zone"]

        # 280 W is 108 % of the 260 W fixture FTP: zone 5, as the snapshot gave.
        self.assertEqual(zone(self._thresholds()), 5)
        self.assertIsNone(zone(()))

    def test_only_sport_scoped_athlete_settings_are_thresholds(self) -> None:
        populate(self)
        thresholds = self._thresholds()
        self.assertTrue(all(item.sport is not None for item in thresholds))
        self.assertEqual(
            {item.kind for item in thresholds},
            {MetricKind.FTP, MetricKind.THRESHOLD_HR, MetricKind.MAX_HR},
        )

    def test_pending_tables_serve_no_thresholds(self) -> None:
        # The backfill has not run, so the selector serves nothing yet.
        self.assertEqual(self._thresholds(), ())


if __name__ == "__main__":
    unittest.main()
