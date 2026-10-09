"""Focused contracts for the disposable standard demo fixture data shapes."""

import json
import threading
import os
import unittest
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from backend.calendar.ical_mapping import calendar_event_constraints
from backend.coach.response_transport import raise_if_chat_cancelled
from backend.db.manager import DATABASE_MANAGER_CACHE
from backend.errors import AppError
from backend.performance.body import body_history
from backend.performance.daily_health import garmin_daily_expenditure
from backend.providers.calendar import parse_ical_calendar
from e2e import fixture_runtime

V6_UNIT_NAMES = {
    "Fixture swim intervals",
    "Fixture hard intervals",
    "Fixture short-only ride",
}


class StandardFixtureDataTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 6)

    def test_standard_dataset_covers_sparse_body_history_and_both_ftp_sources(self):
        wellness = fixture_runtime._fixture_demo_wellness(self.today)
        garmin = fixture_runtime._fixture_demo_garmin(
            self.today, fixture_runtime.demo_performance_history(self.today)
        )
        snapshot = {
            "synced_at": "synthetic",
            "recent_wellness": wellness,
            "raw_provider_data": {"wellness": wellness},
        }

        result = body_history(snapshot, garmin, self.today)
        window = result["windows"]["12w"]
        self.assertEqual(window["days"], 84)
        self.assertEqual(len(window["metrics"]["weight_kg"][0]["points"]), 84)
        self.assertTrue(
            any(
                point["value"] is None
                for point in window["metrics"]["weight_kg"][0]["points"]
            )
        )
        self.assertTrue(
            any(
                point["value"] is not None
                for point in window["metrics"]["body_fat_pct"][0]["points"]
            )
        )
        ftp_series = window["metrics"]["cycling_w_per_kg"]
        self.assertTrue(
            any(
                series["source"] == "Garmin Connect"
                and any(point.get("ftp_watts") for point in series["points"])
                for series in ftp_series
            )
        )
        self.assertTrue(
            any(
                series["source"] == "Intervals.icu"
                and any(point.get("ftp_watts") for point in series["points"])
                for series in ftp_series
            )
        )

    def test_daily_calories_have_measured_zero_values_and_today_provisional(self):
        garmin = fixture_runtime._fixture_demo_garmin(
            self.today, fixture_runtime.demo_performance_history(self.today)
        )
        today = garmin_daily_expenditure(garmin, self.today.isoformat(), self.today)
        zero_day = garmin_daily_expenditure(
            garmin, (self.today - timedelta(days=12)).isoformat(), self.today
        )

        self.assertTrue(today["provisional"])
        self.assertIsNotNone(today["active_kcal"])
        self.assertIsNotNone(today["resting_kcal"])
        self.assertIsNotNone(today["total_kcal"])
        self.assertEqual(
            (zero_day["active_kcal"], zero_day["resting_kcal"], zero_day["total_kcal"]),
            (0, 0, 0),
        )

    def test_calendar_feed_parses_titles_descriptions_and_event_examples(self):
        events = parse_ical_calendar(
            fixture_runtime._fixture_calendar_payload(self.today),
            local_zone=ZoneInfo("Europe/Berlin"),
            today=self.today,
            window_start=self.today,
            window_end=self.today + timedelta(days=56),
        )
        events = [calendar_event_constraints(event) for event in events]
        self.assertTrue(all("description" not in event for event in events))
        by_uid = {}
        for event in events:
            by_uid.setdefault(event["uid"], []).append(event)

        self.assertEqual(
            by_uid["fixture-title-description"][0]["name"], "Fixture title example"
        )
        self.assertTrue(by_uid["fixture-no-training"][0]["no_training"])
        self.assertTrue(by_uid["fixture-no-intensity"][0]["no_intensity"])
        self.assertTrue(by_uid["fixture-both"][0]["no_training"])
        self.assertTrue(by_uid["fixture-both"][0]["no_intensity"])
        self.assertTrue(by_uid["fixture-multiday"][0]["all_day"])
        self.assertTrue(by_uid["fixture-multiday"][0]["no_intensity"])
        self.assertEqual(by_uid["fixture-multiday"][0]["duration_minutes"], 2880)
        self.assertEqual(len(by_uid["fixture-series"]), 2)
        self.assertTrue(all(event["short_only"] for event in by_uid["fixture-series"]))

    def test_equipment_seed_definitions_cover_lifecycle_and_counter_boundaries(self):
        definitions = fixture_runtime._fixture_equipment_definitions(
            "00000000-0000-4000-8000-000000000001"
        )
        component_rows = [row for row in definitions if row[3] == "component"]

        self.assertIn("archived", {row[4] for row in component_rows})
        self.assertIn("active", {row[4] for row in component_rows})
        self.assertIn(None, {row[6] for row in definitions})
        self.assertIn(250, {row[6] for row in definitions})
        garmin = fixture_runtime._fixture_demo_garmin(
            self.today, fixture_runtime.demo_performance_history(self.today)
        )
        shoes = next(
            item for item in garmin["gear"] if item["gearTypeName"] == "Laufschuhe"
        )
        self.assertGreater(shoes["stats"]["totalDistance"], shoes["maximumMeters"])

    def test_v1_demo_upgrades_once_to_current_seed_version(self):
        values = {"preview_demo_seeded": "1"}
        snapshot = {
            "synced_at": "synthetic-before-upgrade",
            "recent_wellness": [
                {
                    "id": (self.today - timedelta(days=offset)).isoformat(),
                    "eftp": 260 + offset / 4,
                }
                for offset in range(90)
            ],
        }
        unit_of_work = Mock()
        database = object()
        unit_of_work.return_value.__enter__ = Mock(return_value=database)
        unit_of_work.return_value.__exit__ = Mock(return_value=False)
        manager = Mock(unit_of_work=unit_of_work)
        repository = fixture_runtime.server.KEY_VALUE_REPOSITORY
        snapshots = fixture_runtime.server.SNAPSHOT_REPOSITORY

        def get_value(_db, key):
            return values.get(key)

        def set_value(_db, key, value):
            values[key] = value

        with (
            patch.object(
                fixture_runtime.server, "database_manager", return_value=manager
            ),
            patch.object(
                fixture_runtime.server.ATHLETE_CLOCK,
                "now",
                return_value=datetime.combine(self.today, time()),
            ),
            patch.object(
                fixture_runtime.server.runtime_clock,
                "utc_now",
                return_value="synthetic-upgrade",
            ),
            patch.object(
                snapshots,
                "latest_payload",
                side_effect=lambda _db: json.dumps(snapshot),
            ),
            patch.object(
                snapshots,
                "save",
                side_effect=lambda _db, value, _created_at: snapshot.update(value),
            ) as save_snapshot_mock,
            patch.object(
                fixture_runtime,
                "_fixture_seed_equipment",
                return_value={},
            ) as seed_equipment_mock,
            patch.object(
                fixture_runtime,
                "_fixture_seed_calendar",
                return_value=8,
            ) as seed_calendar_mock,
            patch.object(repository, "get", side_effect=get_value),
            patch.object(repository, "set", side_effect=set_value),
        ):
            first = fixture_runtime.seed_preview_demo()
            second = fixture_runtime.seed_preview_demo()

        self.assertEqual(
            first["seed_version"], fixture_runtime.FIXTURE_DEMO_SEED_VERSION
        )
        self.assertEqual(second, {"ready": True})
        save_snapshot_mock.assert_called_once()
        seeded_garmin = json.loads(values["garmin_snapshot"])
        seed_equipment_mock.assert_called_once_with(self.today, seeded_garmin)
        seed_calendar_mock.assert_called_once_with(self.today)
        self.assertEqual(len(snapshot["recent_wellness"]), 90)
        self.assertEqual(len(snapshot["raw_provider_data"]["wellness"]), 90)
        self.assertTrue(
            all(row.get("sport_info") for row in snapshot["recent_wellness"])
        )
        self.assertTrue(
            any(row.get("weight") is None for row in snapshot["recent_wellness"])
        )
        self.assertEqual(
            values["preview_demo_seed_version"],
            fixture_runtime.FIXTURE_DEMO_SEED_VERSION,
        )
        garmin = json.loads(values["garmin_snapshot"])
        self.assertEqual(len(garmin["daily_stats"]), 90)
        self.assertIn("weight", garmin)

    def test_demo_seed_populates_and_repeats_in_temporary_database(self):
        server = fixture_runtime.server
        original = (server.CONFIG, server.DATA_DIR, server.DB_PATH, server.LOG_PATH)
        with TemporaryDirectory(prefix="fixture-demo-test-") as directory:
            root = Path(directory)
            try:
                DATABASE_MANAGER_CACHE.reset()
                server.CONFIG = replace(server.CONFIG, app_password="")
                server.DATA_DIR = root
                server.DB_PATH = root / "fixture.db"
                server.LOG_PATH = root / "fixture.log"
                fixture_runtime.initialise_fixture()

                first = fixture_runtime.seed_preview_demo()
                with server.database_manager().unit_of_work() as db:
                    calendar_count = db.execute(
                        "SELECT COUNT(*) AS count FROM external_calendar_events WHERE uid LIKE 'fixture-%'"
                    ).fetchone()["count"]
                    nutrition_count = db.execute(
                        "SELECT COUNT(*) AS count FROM nutrition_logs"
                    ).fetchone()["count"]
                    equipment_count = db.execute(
                        "SELECT COUNT(*) AS count FROM kv WHERE key LIKE 'equipment:%'"
                    ).fetchone()["count"]
                    old_snapshot = json.loads(
                        server.SNAPSHOT_REPOSITORY.latest_payload(db)
                    )
                    detail_rows = db.execute(
                        "SELECT value FROM kv WHERE key LIKE 'activity_detail:%'"
                    ).fetchall()
                    detail_values = [json.loads(row["value"]) for row in detail_rows]
                    for row in old_snapshot["recent_wellness"]:
                        row.pop("weight", None)
                        row.pop("bodyFat", None)
                        row.pop("sport_info", None)
                    old_snapshot["raw_provider_data"].pop("wellness", None)
                    server.SNAPSHOT_REPOSITORY.save(
                        db, old_snapshot, "synthetic-v1-demo"
                    )
                    server.KEY_VALUE_REPOSITORY.set(
                        db, "preview_demo_seed_version", "1"
                    )

                upgraded = fixture_runtime.seed_preview_demo()
                with server.database_manager().unit_of_work() as db:
                    stored_garmin = json.loads(
                        server.KEY_VALUE_REPOSITORY.get(db, "garmin_snapshot")
                    )
                    seed_version = server.KEY_VALUE_REPOSITORY.get(
                        db, "preview_demo_seed_version"
                    )
                    snapshot = json.loads(server.SNAPSHOT_REPOSITORY.latest_payload(db))
                    upgraded_nutrition_count = db.execute(
                        "SELECT COUNT(*) AS count FROM nutrition_logs"
                    ).fetchone()["count"]
                    upgraded_equipment_count = db.execute(
                        "SELECT COUNT(*) AS count FROM kv WHERE key LIKE 'equipment:%'"
                    ).fetchone()["count"]
                    upgraded_calendar_count = db.execute(
                        "SELECT COUNT(*) AS count FROM external_calendar_events WHERE uid LIKE 'fixture-%'"
                    ).fetchone()["count"]
                equipment = server.ATHLETE_DATA.equipment().read()["items"]

                repeated = fixture_runtime.seed_preview_demo()
                with server.database_manager().unit_of_work() as db:
                    repeated_nutrition_count = db.execute(
                        "SELECT COUNT(*) AS count FROM nutrition_logs"
                    ).fetchone()["count"]
                    repeated_equipment_count = db.execute(
                        "SELECT COUNT(*) AS count FROM kv WHERE key LIKE 'equipment:%'"
                    ).fetchone()["count"]
                    repeated_calendar_count = db.execute(
                        "SELECT COUNT(*) AS count FROM external_calendar_events WHERE uid LIKE 'fixture-%'"
                    ).fetchone()["count"]
            finally:
                DATABASE_MANAGER_CACHE.reset()
                server.CONFIG, server.DATA_DIR, server.DB_PATH, server.LOG_PATH = (
                    original
                )

        self.assertEqual(first, {"ready": True})
        self.assertEqual(
            upgraded["seed_version"], fixture_runtime.FIXTURE_DEMO_SEED_VERSION
        )
        self.assertEqual(repeated, {"ready": True})
        self.assertEqual(seed_version, fixture_runtime.FIXTURE_DEMO_SEED_VERSION)
        self.assertEqual(len(snapshot["recent_wellness"]), 90)
        self.assertEqual(len(snapshot["raw_provider_data"]["wellness"]), 90)
        self.assertTrue(
            {"VirtualRide", "Ride", "Run"}.issubset(
                {row.get("type") for row in snapshot["recent_activities"]}
            )
        )
        profiles_by_sport = {}
        for item in detail_values:
            sport = (item.get("activity") or {}).get("type")
            profiles_by_sport.setdefault(sport, []).append(
                item.get("session_analysis") or {}
            )
        self.assertTrue({"VirtualRide", "Ride", "Run"}.issubset(profiles_by_sport))
        for sport in ("Ride", "VirtualRide"):
            self.assertTrue(
                any(
                    (analysis.get("power_profile") or {}).get("status") == "ok"
                    and any(
                        point.get("duration_seconds") == 3600
                        and point.get("watts") is not None
                        for point in (analysis.get("power_profile") or {}).get(
                            "duration_curve", []
                        )
                    )
                    for analysis in profiles_by_sport[sport]
                )
            )
        running_profile = next(
            analysis.get("running_profile") or {}
            for analysis in profiles_by_sport["Run"]
            if (analysis.get("running_profile") or {}).get("status") == "ok"
        )
        self.assertEqual("ok", running_profile.get("status"))
        self.assertTrue(
            any(
                point.get("distance_meters") == 5000
                and point.get("seconds") is not None
                for point in running_profile.get("distance", [])
            )
        )
        run_detail = next(
            item
            for item in detail_values
            if (item.get("activity") or {}).get("type") == "Run"
        )
        for detail in detail_values:
            activity = detail["activity"]
            streams = activity["streams"]
            self.assertEqual(activity["moving_time"], streams["time"][-1])
            self.assertEqual(activity["moving_time"] + 1, len(streams["time"]))
        self.assertGreater(len(run_detail["activity"]["streams"]["distance"]), 1000)
        self.assertIn("velocity_smooth", run_detail["activity"]["streams"])
        self.assertAlmostEqual(
            run_detail["activity"]["distance"],
            run_detail["activity"]["streams"]["distance"][-1],
            places=6,
        )
        self.assertTrue(
            any(
                len((item.get("activity") or {}).get("streams", {}).get("time", []))
                >= 3601
                and (item.get("activity") or {}).get("type") in {"Ride", "VirtualRide"}
                for item in detail_values
            )
        )
        self.assertEqual(len(stored_garmin["daily_stats"]), 90)
        self.assertEqual(calendar_count, 7)
        self.assertEqual(upgraded_calendar_count, calendar_count)
        self.assertEqual(upgraded_nutrition_count, nutrition_count)
        self.assertEqual(upgraded_equipment_count, equipment_count)
        self.assertEqual(repeated_calendar_count, upgraded_calendar_count)
        self.assertEqual(repeated_nutrition_count, upgraded_nutrition_count)
        self.assertEqual(repeated_equipment_count, upgraded_equipment_count)
        self.assertTrue(any(item.get("kind") == "component" for item in equipment))
        chain = next(
            item for item in equipment if item["name"] == "Fixture Garmin-linked chain"
        )
        bike = next(
            item for item in equipment if item["name"] == "Fixture Garmin linked bike"
        )
        shoes = next(
            item
            for item in equipment
            if item["name"] == "Fixture Garmin archived shoes"
        )
        self.assertEqual(chain["lifetime_target_km"], 200)
        self.assertEqual(chain["lifetime_target_source"], "local")
        self.assertEqual(chain["usage"]["distance_km"], 0)
        self.assertEqual(bike["usage"]["distance_km"], 425)
        self.assertEqual(shoes["usage"]["distance_km"], 410)
        self.assertEqual(shoes["lifetime_target_source"], "garmin")
        self.assertEqual(shoes["lifetime"]["target_km"], 300)
        self.assertGreater(shoes["lifetime"]["percent"], 100)

    def test_slow_stream_cancel_stops_emission_and_matches_real_transport_error(self):
        cancel_event = threading.Event()
        emitted = []

        def on_text_delta(chunk):
            emitted.append(chunk)
            if len(emitted) == 1:
                cancel_event.set()

        payload = {"input": json.dumps({"current_message": "E2E fixture: slow stream"})}
        with self.assertRaises(AppError) as fixture_error:
            fixture_runtime.FixtureResponseTransport().stream_request(
                payload, on_text_delta, cancel_event=cancel_event
            )
        with self.assertRaises(AppError) as transport_error:
            raise_if_chat_cancelled(cancel_event)

        self.assertEqual(emitted, [fixture_runtime.SLOW_STREAM_CHUNKS[0]])
        self.assertEqual(fixture_error.exception.status, 499)
        self.assertEqual(fixture_error.exception.reason, "chat_cancelled")
        self.assertEqual(
            (
                fixture_error.exception.status,
                fixture_error.exception.message,
                fixture_error.exception.reason,
            ),
            (
                transport_error.exception.status,
                transport_error.exception.message,
                transport_error.exception.reason,
            ),
        )

    def test_slow_stream_pre_cancelled_request_emits_nothing(self):
        cancel_event = threading.Event()
        cancel_event.set()
        emitted = []
        payload = {"input": json.dumps({"current_message": "E2E fixture: slow stream"})}

        with self.assertRaises(AppError) as raised:
            fixture_runtime.FixtureResponseTransport().stream_request(
                payload, emitted.append, cancel_event=cancel_event
            )

        self.assertEqual(emitted, [])
        self.assertEqual(raised.exception.status, 499)
        self.assertEqual(raised.exception.reason, "chat_cancelled")

    def test_auto_seeded_restarts_and_explicit_seeds_keep_data_stable(self):
        server = fixture_runtime.server
        original = (server.CONFIG, server.DATA_DIR, server.DB_PATH, server.LOG_PATH)

        def counts():
            with server.database_manager().unit_of_work() as db:
                snapshot = json.loads(server.SNAPSHOT_REPOSITORY.latest_payload(db))
                equipment_keys = db.execute(
                    "SELECT COUNT(*) AS count FROM kv WHERE key LIKE 'equipment%'"
                ).fetchone()["count"]
            competitions = server.PLANNING_DATA.competition().list(100)
            units = server.PLANNING_DATA.planned_unit().list(500)
            return {
                "activities": len(snapshot["recent_activities"]),
                "swim_activities": sum(
                    str(item.get("id", "")).startswith("fixture-v6-swim-")
                    for item in snapshot["recent_activities"]
                ),
                "competitions": len(competitions),
                "cycling_targets": sum(
                    item["name"] == "Fixture cycling target" for item in competitions
                ),
                "units": len(units),
                "scenario_units": sum(
                    item.get("name") in V6_UNIT_NAMES for item in units
                ),
                "equipment_keys": equipment_keys,
            }

        with TemporaryDirectory(prefix="fixture-restart-test-") as directory:
            root = Path(directory)
            try:
                DATABASE_MANAGER_CACHE.reset()
                server.CONFIG = replace(server.CONFIG, app_password="")
                server.DATA_DIR = root
                server.DB_PATH = root / "fixture.db"
                server.LOG_PATH = root / "fixture.log"
                with patch.dict("os.environ", {"FIXTURE_AUTO_SEED": "1"}):
                    fixture_runtime.initialise_fixture()
                    first = counts()
                    fixture_runtime.initialise_fixture()
                    restarted = counts()
                demo_ids = self._snapshot_activity_ids(server)

                fixture_runtime.seed_training_features()
                fixture_runtime.seed_training_features()
                features = counts()
                feature_ids = self._snapshot_activity_ids(server)
            finally:
                DATABASE_MANAGER_CACHE.reset()
                server.CONFIG, server.DATA_DIR, server.DB_PATH, server.LOG_PATH = (
                    original
                )

        self.assertEqual(restarted, first)
        self.assertEqual(first["scenario_units"], 3)
        self.assertEqual(first["swim_activities"], 2)
        self.assertEqual(first["cycling_targets"], 1)
        self.assertEqual(features["cycling_targets"], 1)
        self.assertEqual(features["competitions"], first["competitions"])
        self.assertEqual(features["units"], first["units"])
        self.assertEqual(feature_ids, demo_ids)

    @contextmanager
    def _temporary_fixture_database(self, prefix):
        server = fixture_runtime.server
        original = (server.CONFIG, server.DATA_DIR, server.DB_PATH, server.LOG_PATH)
        with TemporaryDirectory(prefix=prefix) as directory:
            root = Path(directory)
            try:
                DATABASE_MANAGER_CACHE.reset()
                server.CONFIG = replace(server.CONFIG, app_password="")
                server.DATA_DIR = root
                server.DB_PATH = root / "fixture.db"
                server.LOG_PATH = root / "fixture.log"
                yield server
            finally:
                DATABASE_MANAGER_CACHE.reset()
                server.CONFIG, server.DATA_DIR, server.DB_PATH, server.LOG_PATH = (
                    original
                )

    def test_reseeding_on_a_later_date_moves_the_single_cycling_target(self):
        seed_day = self.today
        reseed_day = self.today + timedelta(days=3)

        with self._temporary_fixture_database("fixture-reseed-test-") as server:

            def cycling_targets():
                return [
                    item
                    for item in server.PLANNING_DATA.competition().list(100)
                    if item["name"] == "Fixture cycling target"
                ]

            fixture_runtime.initialise_fixture()
            with patch.object(
                server.ATHLETE_CLOCK,
                "now",
                return_value=datetime.combine(seed_day, time()),
            ):
                fixture_runtime.seed_training_features()
            first_targets = cycling_targets()
            competitions_before = len(server.PLANNING_DATA.competition().list(100))
            with patch.object(
                server.ATHLETE_CLOCK,
                "now",
                return_value=datetime.combine(reseed_day, time()),
            ):
                fixture_runtime.seed_training_features()
            reseeded_targets = cycling_targets()
            competitions_after = len(server.PLANNING_DATA.competition().list(100))

        self.assertEqual(len(first_targets), 1)
        self.assertEqual(len(reseeded_targets), 1)
        self.assertEqual(reseeded_targets[0]["id"], first_targets[0]["id"])
        self.assertEqual(
            reseeded_targets[0]["event_date"],
            (reseed_day + timedelta(days=30)).isoformat(),
        )
        self.assertNotEqual(
            first_targets[0]["event_date"], reseeded_targets[0]["event_date"]
        )
        self.assertEqual(competitions_after, competitions_before)

    def _v6_scenarios(self, server, today):
        """Read back every v6 scenario through the public services and snapshot."""
        with server.database_manager().unit_of_work() as db:
            snapshot = json.loads(server.SNAPSHOT_REPOSITORY.latest_payload(db))
            version = server.KEY_VALUE_REPOSITORY.get(db, "preview_demo_seed_version")
        checkins = {
            item["checkin_date"]: item
            for item in server.ATHLETE_DATA.checkin().list(100)
        }
        units = server.PLANNING_DATA.planned_unit().list(500)
        names = Counter(item.get("name") for item in units)
        swim_day = (
            today - timedelta(days=fixture_runtime.FIXTURE_V6_SWIM_OFFSET)
        ).isoformat()
        sick_day = (
            today - timedelta(days=fixture_runtime.FIXTURE_V6_SICK_OFFSET)
        ).isoformat()
        rest_day = (
            today - timedelta(days=fixture_runtime.FIXTURE_V6_REST_OFFSET)
        ).isoformat()
        return {
            "version": version,
            "rest_day": checkins.get(rest_day, {}).get("day_status"),
            "sick_day_status": checkins.get(sick_day, {}).get("day_status"),
            "sick_illness": checkins.get(sick_day, {}).get("illness"),
            "swims": sorted(
                (item["id"], item["start_date_local"], item["type"])
                for item in snapshot["recent_activities"]
                if str(item.get("id", "")).startswith("fixture-v6-swim-")
            ),
            "swim_unit": [
                item for item in units if item.get("name") == "Fixture swim intervals"
            ],
            "swim_day": swim_day,
            "camp_units": [
                item for item in units if item.get("name") == "Fixture hard intervals"
            ],
            "short_units": [
                item for item in units if item.get("name") == "Fixture short-only ride"
            ],
            "unit_name_counts": {
                name: count for name, count in names.items() if name in V6_UNIT_NAMES
            },
        }

    def test_v6_fresh_seed_contains_each_scenario(self):
        with self._temporary_fixture_database("fixture-v6-fresh-") as server:
            fixture_runtime.initialise_fixture()
            result = fixture_runtime.seed_preview_demo()
            today = server.ATHLETE_CLOCK.now().date()
            scenarios = self._v6_scenarios(server, today)

        self.assertEqual(result, {"ready": True})
        self.assertEqual(
            scenarios["version"], fixture_runtime.FIXTURE_DEMO_SEED_VERSION
        )
        self.assertEqual(scenarios["rest_day"], "rest")
        self.assertEqual(scenarios["sick_day_status"], "pause")
        self.assertEqual(scenarios["sick_illness"], "Erkältung, synthetisch")
        self.assertEqual(
            scenarios["swims"],
            [
                ("fixture-v6-swim-a", f"{scenarios['swim_day']}T11:00:00", "Swim"),
                ("fixture-v6-swim-b", f"{scenarios['swim_day']}T18:00:00", "Swim"),
            ],
        )
        self.assertEqual(len(scenarios["swim_unit"]), 1)
        self.assertEqual(scenarios["swim_unit"][0]["sport"], "Swim")
        self.assertEqual(scenarios["swim_unit"][0]["date"], scenarios["swim_day"])
        self.assertEqual(scenarios["swim_unit"][0]["icu_training_load"], 40)
        self.assertEqual(len(scenarios["camp_units"]), 1)
        self.assertEqual(scenarios["camp_units"][0]["icu_training_load"], 75)
        self.assertEqual(len(scenarios["short_units"]), 1)
        self.assertEqual(scenarios["short_units"][0]["duration_minutes"], 90)
        self.assertEqual(scenarios["short_units"][0]["icu_training_load"], 85)
        self.assertEqual(
            scenarios["unit_name_counts"],
            {name: 1 for name in V6_UNIT_NAMES},
        )

    def test_v5_database_upgrades_to_v6_scenarios_without_duplicates(self):
        with self._temporary_fixture_database("fixture-v6-upgrade-") as server:
            fixture_runtime.initialise_fixture()
            today = server.ATHLETE_CLOCK.now().date()
            with (
                patch.object(fixture_runtime, "FIXTURE_DEMO_SEED_VERSION", "5"),
                patch.object(fixture_runtime, "_fixture_seed_v6", return_value=True),
            ):
                fixture_runtime.seed_preview_demo()
            before = self._v6_scenarios(server, today)

            upgraded = fixture_runtime.seed_preview_demo()
            after = self._v6_scenarios(server, today)

            # Repeating every v6 helper directly must not add rows.
            fixture_runtime._fixture_seed_v6(today)
            repeated = self._v6_scenarios(server, today)

        self.assertEqual(before["version"], "5")
        self.assertEqual(before["swims"], [])
        self.assertEqual(before["camp_units"], [])
        self.assertEqual(upgraded, {"ready": True, "seed_version": "6"})
        self.assertEqual(after["version"], "6")
        self.assertEqual(after["sick_illness"], "Erkältung, synthetisch")
        self.assertEqual(len(after["swims"]), 2)
        self.assertEqual(after["unit_name_counts"], {name: 1 for name in V6_UNIT_NAMES})
        self.assertEqual(repeated, after)

    def test_offline_openai_mode_records_network_failure_without_canned_reply(self):
        server = fixture_runtime.server
        transport = fixture_runtime.FixtureResponseTransport()
        state = Mock()
        calls = [
            lambda: transport.request({"input": "{}"}),
            lambda: transport.background_request({"input": "{}"}),
            lambda: transport.stream_request({"input": "{}"}, lambda _delta: None),
        ]
        with (
            patch.dict(os.environ, {"FIXTURE_OPENAI_MODE": "offline"}),
            patch.object(server, "provider_state_service", return_value=state),
            patch.object(fixture_runtime, "fixture_coach_response") as canned,
        ):
            for call in calls:
                with self.assertRaises(server.AppError) as raised:
                    call()
                self.assertEqual(raised.exception.status, 502)
                self.assertEqual(raised.exception.reason, "network_error")

        canned.assert_not_called()
        self.assertEqual(state.record_status.call_count, len(calls))
        state.record_status.assert_called_with(
            "openai",
            state="error",
            reason="network_error",
            message=unittest.mock.ANY,
        )

    def test_default_openai_mode_keeps_canned_coach_replies(self):
        transport = fixture_runtime.FixtureResponseTransport()
        with (
            patch.dict(os.environ),
            patch.object(
                fixture_runtime,
                "fixture_coach_response",
                return_value={"output_text": "canned"},
            ) as canned,
        ):
            os.environ.pop("FIXTURE_OPENAI_MODE", None)
            result = transport.request({"input": "{}"})

        self.assertEqual(result, {"output_text": "canned"})
        canned.assert_called_once()

    def test_unknown_openai_mode_is_rejected_at_startup(self):
        with (
            patch.dict(os.environ, {"FIXTURE_OPENAI_MODE": "chat"}),
            self.assertRaises(ValueError),
        ):
            fixture_runtime.fixture_openai_mode()

    def test_explicit_activity_seed_merges_into_existing_snapshot(self):
        server = fixture_runtime.server
        existing = {
            "id": "existing-1",
            "name": "Existing ride",
            "start_date_local": "2026-10-01T08:00:00",
        }
        snapshot = {
            "synced_at": "synthetic",
            "athlete": {},
            "recent_wellness": [{"id": "2026-10-01"}],
            "recent_activities": [existing, {"id": "feature-ride-1", "name": "Old"}],
            "raw_provider_data": {"activities": [existing]},
        }
        saved = []
        unit_of_work = Mock()
        unit_of_work.return_value.__enter__ = Mock(return_value=object())
        unit_of_work.return_value.__exit__ = Mock(return_value=False)
        with (
            patch.object(
                server,
                "database_manager",
                return_value=Mock(unit_of_work=unit_of_work),
            ),
            patch.object(
                server.runtime_clock, "utc_now", return_value="synthetic-merge"
            ),
            patch.object(
                server.SNAPSHOT_REPOSITORY,
                "latest_payload",
                return_value=json.dumps(snapshot),
            ),
            patch.object(
                server.SNAPSHOT_REPOSITORY,
                "save",
                side_effect=lambda _db, value, _at: saved.append(value),
            ),
        ):
            fixture_runtime._merge_snapshot_activities(
                [
                    {
                        "id": "feature-ride-1",
                        "name": "New",
                        "start_date_local": "2026-10-06T08:00:00",
                    }
                ]
            )

        merged = saved[0]
        self.assertEqual(
            [item["id"] for item in merged["recent_activities"]],
            ["feature-ride-1", "existing-1"],
        )
        self.assertEqual(merged["recent_activities"][0]["name"], "New")
        self.assertEqual(
            merged["raw_provider_data"]["activities"], merged["recent_activities"]
        )
        self.assertEqual(merged["recent_wellness"], [{"id": "2026-10-01"}])
        self.assertEqual(merged["synced_at"], "synthetic-merge")

    @staticmethod
    def _snapshot_activity_ids(server):
        with server.database_manager().unit_of_work() as db:
            snapshot = json.loads(server.SNAPSHOT_REPOSITORY.latest_payload(db))
        return sorted(str(item["id"]) for item in snapshot["recent_activities"])


if __name__ == "__main__":
    unittest.main()
