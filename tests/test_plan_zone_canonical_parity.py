"""Plan zones read canonical thresholds, not the snapshot sport settings (#1416).

Over the shared populated fixture the canonical zone configurations give the zone
limits the stored snapshot's ``sport_settings`` gave, and the source-policy
winners (Garmin; Intervals.icu is never a source) give the thresholds, for every
sport and environment. Before the first backfill the tables serve no thresholds.
All storage is temporary and providers are mocked.
"""

from __future__ import annotations

import unittest
from datetime import date

from canonical_read_support import CanonicalReadFixture, make_selector, populate
from zone_settings_reference import (
    canonical_zone_settings,
    legacy_sport_settings,
    legacy_zone_settings,
)

from backend.activities.zone_settings import ZoneSettings
from backend.canonical.vocabulary import Environment, MetricKind, ProviderId, Sport
from backend.performance.canonical_current import read_zone_thresholds
from backend.performance.canonical_inputs import (
    CanonicalPerformanceSource,
    inputs_for_snapshot,
    resolve_reader,
)
from backend.planning.calendar_read_model import project_planning_calendar

SPORTS = (Sport.RIDE, Sport.RUN, Sport.SWIM)
# Sport settings whose canonical form must choose the snapshot rule's zones.
SETTING_VARIANTS = (
    # Indoor FTP without a power zone list (ignored).
    [{"types": ["Ride", "VirtualRide"], "ftp": 250, "indoor_ftp": 200}],
    # Indoor FTP with a power zone list (ignored).
    [
        {
            "types": ["Ride", "VirtualRide"],
            "ftp": 250,
            "indoor_ftp": 200,
            "power_zones": [55, 75, 90, 105, 120, 150, 999],
        }
    ],
    [{"types": ["Ride"], "ftp": 250, "lthr": 160, "max_hr": 190}],
    [{"types": ["Run"], "lthr": 170, "hr_zones": [120, 140, 155, 170, 180, 195]}],
)


class SettingVariantParityTests(unittest.TestCase):
    def test_canonical_settings_choose_the_snapshot_zones(self) -> None:
        for settings in SETTING_VARIANTS:
            for sport in SPORTS:
                for environment in Environment:
                    with self.subTest(
                        settings=settings, sport=sport, environment=environment
                    ):
                        # The Intervals.icu indoor FTP is never read, so the
                        # snapshot rule is compared without it.
                        without_indoor = [
                            {
                                key: value
                                for key, value in item.items()
                                if key != "indoor_ftp"
                            }
                            for item in settings
                        ]
                        self.assertEqual(
                            canonical_zone_settings(settings, sport, environment),
                            legacy_sport_settings(without_indoor, sport, environment),
                        )


# The fixture's Garmin lactate-threshold heart rates per sport.
GARMIN_LTHR = {Sport.RIDE: 160.0, Sport.RUN: 168.0}


class PlanZoneParityTests(CanonicalReadFixture):
    def _thresholds(self) -> tuple:
        """The thresholds the state prelude's canonical current inputs carry."""
        selector = make_selector(self)
        source = CanonicalPerformanceSource(
            lambda: self.manager, lambda: selector, activity_summaries=lambda: selector
        )
        with self.manager.reader() as db:
            inputs = inputs_for_snapshot(source, db, as_of=date(2026, 10, 11))
            direct = read_zone_thresholds(
                resolve_reader(selector, db), db, as_of=date(2026, 10, 11)
            )
        thresholds = () if inputs is None else inputs.current.zone_thresholds
        # The plan read takes the same thresholds without the other inputs.
        self.assertEqual(direct, thresholds)
        return thresholds

    def test_canonical_thresholds_are_garmins_and_the_limits_follow_the_snapshot(
        self,
    ) -> None:
        populate(self)
        thresholds = self._thresholds()
        configurations = self.read(self.table.zone_configurations)
        settings = self.intervals["athlete"]["sport_settings"]
        self.assertTrue(thresholds)
        self.assertEqual(
            {item.provenance.provider for item in thresholds}, {ProviderId.GARMIN}
        )
        for sport in SPORTS:
            for environment in Environment:
                legacy = legacy_zone_settings(
                    settings, configurations, sport, environment
                )
                with self.subTest(sport=sport, environment=environment):
                    chosen = ZoneSettings.from_configurations(
                        configurations,
                        sport,
                        environment,
                        fallback=ZoneSettings.from_thresholds(thresholds, sport),
                    )
                    # The zone limits stay the stored configurations'; the
                    # Intervals.icu thresholds are replaced by Garmin's.
                    self.assertEqual(chosen.power_limits, legacy.power_limits)
                    self.assertEqual(chosen.hr_limits, legacy.hr_limits)
                    self.assertEqual(chosen.pace_limits, legacy.pace_limits)
                    self.assertEqual(chosen.lthr, GARMIN_LTHR.get(sport, legacy.lthr))
        ride = ZoneSettings.from_thresholds(thresholds, Sport.RIDE)
        run = ZoneSettings.from_thresholds(thresholds, Sport.RUN)
        self.assertEqual((ride.ftp, ride.lthr, ride.max_hr), (260, 160, None))
        self.assertEqual((run.ftp, run.lthr, run.max_hr), (290, 168, None))

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
                default_name="Workout",
                sport_thresholds=thresholds,
            )
            (row,) = projection["planned"]
            return row["workout_profile"]["segments"][0]["zone"]

        # 280 W is 108 % of the 260 W fixture FTP: zone 5, as the snapshot gave.
        self.assertEqual(zone(self._thresholds()), 5)
        self.assertIsNone(zone(()))

    def test_only_sport_scoped_garmin_values_are_thresholds(self) -> None:
        populate(self)
        thresholds = self._thresholds()
        self.assertTrue(all(item.sport is not None for item in thresholds))
        self.assertEqual(
            {item.kind for item in thresholds},
            {
                MetricKind.FTP,
                MetricKind.THRESHOLD_HR,
                MetricKind.THRESHOLD_PACE,
            },
        )

    def test_pending_tables_serve_no_thresholds(self) -> None:
        # The backfill has not run, so the selector serves nothing yet.
        self.assertEqual(self._thresholds(), ())


if __name__ == "__main__":
    unittest.main()
