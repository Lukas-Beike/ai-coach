"""Focused contracts for the disposable standard demo fixture data shapes."""

import json
import unittest
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from backend.db.manager import DATABASE_MANAGER_CACHE
from backend.performance.body import body_history
from backend.performance.daily_health import garmin_daily_expenditure
from backend.providers.calendar import parse_ical_calendar
from e2e import fixture_runtime


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
        seed_equipment_mock.assert_called_once_with(self.today)
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
                server.CONFIG, server.DATA_DIR, server.DB_PATH, server.LOG_PATH = original

        self.assertEqual(first, {"ready": True})
        self.assertEqual(upgraded["seed_version"], fixture_runtime.FIXTURE_DEMO_SEED_VERSION)
        self.assertEqual(repeated, {"ready": True})
        self.assertEqual(seed_version, fixture_runtime.FIXTURE_DEMO_SEED_VERSION)
        self.assertEqual(len(snapshot["recent_wellness"]), 90)
        self.assertEqual(len(snapshot["raw_provider_data"]["wellness"]), 90)
        self.assertEqual(len(stored_garmin["daily_stats"]), 90)
        self.assertEqual(calendar_count, 7)
        self.assertEqual(upgraded_calendar_count, calendar_count)
        self.assertEqual(upgraded_nutrition_count, nutrition_count)
        self.assertEqual(upgraded_equipment_count, equipment_count)
        self.assertEqual(repeated_calendar_count, upgraded_calendar_count)
        self.assertEqual(repeated_nutrition_count, upgraded_nutrition_count)
        self.assertEqual(repeated_equipment_count, upgraded_equipment_count)
        self.assertTrue(any(item.get("kind") == "component" for item in equipment))
        chain = next(item for item in equipment if item["name"] == "Fixture Garmin-linked chain")
        bike = next(item for item in equipment if item["name"] == "Fixture road bike")
        self.assertEqual(chain["lifetime_target_km"], 200)
        self.assertEqual(chain["usage"]["distance_km"], 0)
        self.assertGreater(bike["fixture_usage_km"], bike["lifetime_target_km"])


if __name__ == "__main__":
    unittest.main()
