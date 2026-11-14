"""The Garmin watch heart-rate zones as zone configurations (#1851)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from canonical_detail_support import open_manager
from canonical_domain_support import local_zone_configuration
from support import load_provider_fixture

from backend.activities.zone_settings import (
    ZONE_STAND_IN_MAX_DAYS,
    ZoneSettings,
    effective_zone_configuration,
    percent_zone,
    zone_source_name,
)
from backend.canonical.garmin_payload import MERGE_SECTIONS, REPLACE_SECTIONS
from backend.canonical.vocabulary import (
    Environment,
    ProviderId,
    Sport,
    ZoneConfigurationMetric,
)
from backend.db import canonical_domain_store, garmin_store
from backend.db.repositories import KeyValueRepository
from backend.performance.garmin_canonical import read_garmin_state
from backend.performance.local_tss import LATER_STAND_IN_MAX_DAYS
from backend.providers.canonical_plans import garmin_ingest_plan
from backend.providers.garmin_health_mapping import MAPPER_VERSION
from backend.providers.garmin_zone_mapping import map_garmin_heart_rate_zones
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.garmin import _stamp_changed_zone_sets
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter

BERLIN = ZoneInfo("Europe/Berlin")
HEART = ZoneConfigurationMetric.HEART_RATE
FETCHED = datetime(2026, 11, 8, 21, 30, tzinfo=UTC)  # 22:30 in Berlin, same day
# The watch set on 2026-11-08: zones in percent of the lactate threshold HR (166).
LTHR_SET = {
    "sport": "DEFAULT",
    "trainingMethod": "LACTATE_THRESHOLD",
    "lactateThresholdHeartRateUsed": 166,
    "maxHeartRateUsed": 189,
    "restingHeartRateUsed": 48,
    "zone1Floor": 100,
    "zone2Floor": 122,
    "zone3Floor": 141,
    "zone4Floor": 152,
    "zone5Floor": 163,
}
# A set on the maximum-HR basis carries no threshold HR.
MAX_HR_SET = load_provider_fixture("garmin/heart_rate_zones.json")[0]


def garmin(
    node: object = None,
    *,
    retrieved_at: datetime = FETCHED,
    record: str = "heart_rate_zones/~a",
):
    return map_garmin_heart_rate_zones(
        LTHR_SET if node is None else node,
        source_record_id=record,
        retrieved_at=retrieved_at,
        zone=BERLIN,
    )


def settings_for(configurations, day: date, *, lthr: float | None = 166.0):
    return ZoneSettings.from_configurations(
        configurations,
        Sport.RUN,
        Environment.OUTDOOR,
        day,
        fallback=ZoneSettings(lthr=lthr, max_hr=189.0),
    )


class GarminZoneMappingTests(unittest.TestCase):
    def test_a_threshold_basis_set_keeps_its_bpm_limits_as_they_are(self) -> None:
        (zones,) = garmin()
        self.assertEqual(
            (HEART, None, None, date(2026, 11, 8)),
            (zones.metric, zones.sport, zones.environment, zones.valid_from),
        )
        # Zone N ends one bpm below the floor of zone N + 1; the top ends at max HR.
        self.assertEqual((121.0, 140.0, 151.0, 162.0, 189.0), zones.limits)
        self.assertEqual(
            (166.0, 189.0, 48.0), (zones.threshold, zones.maximum, zones.resting)
        )
        self.assertEqual("lactate_threshold", zones.model)
        self.assertEqual(ProviderId.GARMIN, zones.provenance.provider)
        self.assertIsNone(zones.percent_limits)

    def test_a_maximum_basis_set_without_threshold_maps_too(self) -> None:
        (zones,) = garmin(MAX_HR_SET)
        self.assertEqual((113.0, 132.0, 151.0, 170.0, 190.0), zones.limits)
        self.assertEqual(
            (None, 190.0, None), (zones.threshold, zones.maximum, zones.resting)
        )
        self.assertIsNone(zones.model)

    def test_the_personal_api_payload_maps(self) -> None:
        payload = load_provider_fixture("garmin/personal/heart_rate_zones.json")
        (zones,) = garmin(payload)
        self.assertEqual((112.0, 130.0, 151.0, 169.0, 189.0), zones.limits)
        self.assertEqual("custom", zones.model)

    def test_each_sport_gets_its_own_set_and_default_has_none(self) -> None:
        sets = [
            {**LTHR_SET, "sport": "RUNNING"},
            {**LTHR_SET, "sport": "CYCLING"},
            {**LTHR_SET, "sport": "DEFAULT"},
        ]
        self.assertEqual(
            [Sport.RUN, Sport.RIDE, None], [item.sport for item in garmin(sets)]
        )

    def test_unknown_sports_and_broken_sets_are_left_out(self) -> None:
        self.assertEqual((), garmin({**LTHR_SET, "sport": "LAP_SWIMMING"}))
        self.assertEqual((), garmin({**LTHR_SET, "maxHeartRateUsed": None}))
        self.assertEqual((), garmin({**LTHR_SET, "zone3Floor": "x"}))
        self.assertEqual((), garmin({**LTHR_SET, "zone3Floor": 100}))  # not ascending
        self.assertEqual((), garmin({**LTHR_SET, "zone5Floor": 200}))  # above max HR
        self.assertEqual((), garmin("nonsense"))

    def test_the_set_is_valid_from_the_local_day_it_was_fetched(self) -> None:
        late = datetime(2026, 11, 8, 23, 30, tzinfo=UTC)  # 00:30 on the 9th in Berlin
        (zones,) = garmin(retrieved_at=late)
        self.assertEqual(date(2026, 11, 9), zones.valid_from)


class GarminZoneSettingsTests(unittest.TestCase):
    def test_a_run_at_139_bpm_is_in_the_garmin_zone_not_the_coggan_zone(self) -> None:
        coggan = settings_for([], date(2026, 11, 8))
        garmin_zones = settings_for(garmin(), date(2026, 11, 8))
        # Coggan: 139 of 166 is 83.7 % of LTHR, above 83 %, zone 3. Garmin: zone 2.
        self.assertEqual(3, coggan.absolute_zone("bpm", 139))
        self.assertEqual(2, garmin_zones.absolute_zone("bpm", 139))
        self.assertEqual("Garmin-Zonen", garmin_zones.hr_source)
        self.assertEqual("Standardzonen", coggan.hr_source)

    def test_the_watch_limits_hold_for_every_bpm_including_the_boundaries(self) -> None:
        zones = settings_for(garmin(), date(2026, 11, 8))
        for bpm, zone in ((121, 1), (122, 2), (140, 2), (141, 3), (151, 3), (152, 4)):
            with self.subTest(bpm=bpm):
                self.assertEqual(zone, zones.absolute_zone("bpm", bpm))
        # The watch zones follow the threshold the settings carry.
        for threshold in (160.0, 166.0, 171.3):
            carried = settings_for(garmin(), date(2026, 11, 8), lthr=threshold)
            for bpm in range(60, 200):
                expected = percent_zone(bpm, (121, 140, 151, 162))
                self.assertEqual(expected, carried.absolute_zone("bpm", bpm))

    def test_a_maximum_basis_set_applies_over_a_known_threshold(self) -> None:
        zones = settings_for(garmin(MAX_HR_SET), date(2026, 11, 8))
        for bpm, zone in ((113, 1), (114, 2), (132, 2), (133, 3), (170, 4), (171, 5)):
            with self.subTest(bpm=bpm):
                self.assertEqual(zone, zones.absolute_zone("bpm", bpm))
        self.assertEqual("Garmin-Zonen", zones.hr_source)

    def test_without_any_threshold_the_watch_limits_use_the_max_hr_basis(self) -> None:
        zones = settings_for(garmin(MAX_HR_SET), date(2026, 11, 8), lthr=None)
        # No LTHR is invented; the limits convert via 90 % of the max HR (#1892).
        self.assertIsNone(zones.lthr)
        self.assertEqual("Garmin-Zonen (Bezug 90 % der Max-HF)", zones.hr_source)
        for bpm, zone in ((113, 1), (114, 2), (132, 2), (133, 3), (170, 4), (171, 5)):
            with self.subTest(bpm=bpm):
                self.assertEqual(zone, zones.absolute_zone("bpm", bpm))

    def test_a_confirmed_local_configuration_still_wins(self) -> None:
        local = local_zone_configuration(
            sport=Sport.RUN, threshold=170.0, limits=(130.0, 145.0, 160.0, 170.0, 190.0)
        )
        zones = settings_for([*garmin(), local], date(2026, 11, 8))
        self.assertEqual("lokale Zonen", zones.hr_source)
        self.assertEqual(170.0, zones.lthr)
        self.assertEqual(2, zones.absolute_zone("bpm", 145))

    def test_a_sport_set_wins_over_the_default_set(self) -> None:
        sets = [
            {**LTHR_SET, "sport": "DEFAULT"},
            {**LTHR_SET, "sport": "RUNNING", "zone2Floor": 110},
        ]
        run = effective_zone_configuration(garmin(sets), HEART, Sport.RUN)
        walk = effective_zone_configuration(garmin(sets), HEART, Sport.SWIM)
        assert run is not None and walk is not None
        self.assertEqual(Sport.RUN, run.sport)
        self.assertIsNone(walk.sport)

    def test_the_zones_valid_on_the_session_day_apply(self) -> None:
        first = garmin({**LTHR_SET, **MAX_HR_SET, "trainingMethod": "HR_RESERVE"})
        later = garmin(
            retrieved_at=datetime(2026, 11, 20, 8, 0, tzinfo=UTC),
            record="heart_rate_zones/~b",
        )
        both = [*first, *later]
        bpm = (
            140  # zone 3 on the earlier set (133..151), zone 2 on the later (122..140)
        )
        self.assertEqual(
            3, settings_for(both, date(2026, 11, 10)).absolute_zone("bpm", bpm)
        )
        self.assertEqual(
            2, settings_for(both, date(2026, 11, 21)).absolute_zone("bpm", bpm)
        )

    def test_a_day_before_the_first_fetch_takes_the_earliest_later_set(self) -> None:
        both = garmin()
        valid_from = both[0].valid_from
        assert valid_from is not None
        within = valid_from - timedelta(days=ZONE_STAND_IN_MAX_DAYS)
        self.assertEqual(2, settings_for(both, within).absolute_zone("bpm", 139))
        beyond = within - timedelta(days=1)
        self.assertEqual("Standardzonen", settings_for(both, beyond).hr_source)

    def test_the_stand_in_cap_is_the_threshold_cap(self) -> None:
        self.assertEqual(LATER_STAND_IN_MAX_DAYS, ZONE_STAND_IN_MAX_DAYS)

    def test_the_zone_source_names(self) -> None:
        self.assertEqual("Garmin-Zonen", zone_source_name(garmin()[0]))
        self.assertEqual("lokale Zonen", zone_source_name(local_zone_configuration()))
        self.assertEqual("Standardzonen", zone_source_name(None))


class GarminZonePlanTests(unittest.TestCase):
    def test_the_ingest_plan_projects_the_watch_zones(self) -> None:
        payload = {
            "synced_at": "2026-11-08T21:30:00+00:00",
            "heart_rate_zones": [dict(LTHR_SET)],
        }
        plan = garmin_ingest_plan(payload, zone=BERLIN)
        (batch,) = (item for item in plan.domain_batches if item.zones)
        (zones,) = batch.zones
        self.assertEqual(MAPPER_VERSION, batch.mapper_version)
        self.assertEqual(date(2026, 11, 8), zones.valid_from)
        self.assertEqual(batch.source_record_id, zones.provenance.source_record_id)
        self.assertIn(
            batch.source_record_id, {raw.source_record_id for raw in plan.raw_records}
        )


def stamped(incoming, stored, day="2026-11-08"):
    payload = {"heart_rate_zones": incoming}
    _stamp_changed_zone_sets(payload, stored, day)
    return payload.get("heart_rate_zones")


def of(sport, **overrides):
    return {**LTHR_SET, "sport": sport, **overrides}


class GarminZoneSyncTests(unittest.TestCase):
    def test_the_first_answer_is_stored_with_its_day(self) -> None:
        (item,) = stamped([of("DEFAULT")], None)
        self.assertEqual(
            ("2026-11-08-default", "2026-11-08"), (item["id"], item["fetchedOn"])
        )
        self.assertEqual(LTHR_SET, {k: v for k, v in item.items() if k in LTHR_SET})

    def test_an_unchanged_answer_leaves_the_stored_sets_alone(self) -> None:
        stored = [of("DEFAULT", id="2026-11-01-default", fetchedOn="2026-11-01")]
        self.assertIsNone(
            stamped([dict(reversed(list(of("DEFAULT").items())))], stored)
        )
        # A set stored before the sets were dated counts too.
        self.assertIsNone(stamped([of("DEFAULT")], [of("DEFAULT")]))

    def test_only_the_changed_sport_is_stored_again(self) -> None:
        stored = [
            of("DEFAULT", id="a", fetchedOn="2026-11-01"),
            of("RUNNING", id="b", fetchedOn="2026-11-01"),
        ]
        incoming = [of("DEFAULT"), of("RUNNING", zone2Floor=118)]
        (item,) = stamped(incoming, stored)
        self.assertEqual(
            ("RUNNING", 118, "2026-11-08-running"),
            (item["sport"], item["zone2Floor"], item["id"]),
        )

    def test_a_set_that_returns_to_an_earlier_value_is_a_new_set(self) -> None:
        stored = [
            of("DEFAULT", id="a", fetchedOn="2026-11-01"),
            of("DEFAULT", id="b", fetchedOn="2026-11-05", zone2Floor=118),
        ]
        (item,) = stamped([of("DEFAULT")], stored, "2026-11-09")
        self.assertEqual("2026-11-09", item["fetchedOn"])

    def test_an_empty_answer_changes_nothing(self) -> None:
        payload: dict[str, Any] = {"heart_rate_zones": []}
        _stamp_changed_zone_sets(payload, None, "2026-11-08")
        self.assertNotIn("heart_rate_zones", payload)

    def test_a_dated_set_maps_from_its_own_day(self) -> None:
        (zones,) = garmin(of("DEFAULT", fetchedOn="2026-10-01"))
        self.assertEqual(date(2026, 10, 1), zones.valid_from)


class GarminZoneHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.writer = GarminSnapshotWriter(
            KeyValueRepository(lambda: "2026-11-08T22:00:00+00:00"), lambda: BERLIN
        )

    def _write(self, synced_at: str, *sets: dict[str, Any]) -> None:
        with self.manager.unit_of_work() as db:
            self.writer.write(
                db, {"synced_at": synced_at, "heart_rate_zones": list(sets)}
            )

    def _active(self) -> list[str]:
        with self.manager.reader() as db:
            return sorted(
                row["config_key"]
                for row in canonical_domain_store.active_zone_configuration_rows(db)
            )

    def test_every_changed_set_keeps_the_zones_of_the_earlier_days(self) -> None:
        first = {**of("DEFAULT"), "id": "2026-11-01-default", "fetchedOn": "2026-11-01"}
        second = {
            **of("DEFAULT", zone2Floor=118),
            "id": "2026-11-08-default",
            "fetchedOn": "2026-11-08",
        }
        self._write("2026-11-01T08:00:00+00:00", first)
        self._write("2026-11-08T08:00:00+00:00", second)
        self.assertEqual(
            ["garmin|heart_rate|||2026-11-01", "garmin|heart_rate|||2026-11-08"],
            self._active(),
        )
        with self.manager.reader() as db:
            stored = garmin_store.read_sections(db, ["heart_rate_zones"])
        self.assertEqual(2, len(stored["heart_rate_zones"]))

    def test_the_profile_max_hr_follows_the_newest_set(self) -> None:
        first = {**of("DEFAULT", maxHeartRateUsed=195), "id": "2026-11-01-default"}
        second = {**of("DEFAULT", maxHeartRateUsed=189), "id": "2026-11-05-default"}
        self._write("2026-11-01T08:00:00+00:00", {**first, "fetchedOn": "2026-11-01"})
        self._write("2026-11-05T08:00:00+00:00", {**second, "fetchedOn": "2026-11-05"})
        with self.manager.reader() as db:
            state = read_garmin_state(CanonicalTableReader(), db)
        self.assertEqual({"generic": 189}, state.metrics.profile_max_hr)

    def test_the_zone_sets_are_a_merge_section(self) -> None:
        self.assertIn("heart_rate_zones", MERGE_SECTIONS)
        self.assertNotIn("heart_rate_zones", REPLACE_SECTIONS)


if __name__ == "__main__":
    unittest.main()
