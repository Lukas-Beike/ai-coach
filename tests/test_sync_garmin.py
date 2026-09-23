from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.observability import Redactor
from backend.sync.daily import DailySyncMarkerService
from backend.sync.garmin import (
    GarminFixtureLoader,
    GarminSyncStateService,
    collection_complete,
    merge_sources,
    normalize_fixture_sleep_dates,
)
from backend.sync.state import SyncStateRepository

TODAY = date(2026, 9, 20)
UTC_NOW = "2026-09-20T10:30:00+00:00"
EARLIEST_DATE = date(2000, 1, 1)
ALL_SYNC_DAYS = -1
BASE_CONFIG = Config(
    port=8090,
    openai_api_key="",
    openai_base_url="https://api.openai.com/v1",
    openai_model="gpt-5.6-luna",
    gemini_api_key="",
    gemini_model="gemini-3.8-flash",
    ai_provider="",
    intervals_api_key="",
    intervals_athlete_id="0",
    garmin_email="",
    garmin_password="",
    garmin_tokenstore="",
    garmin_fixture_path="",
    calendar_ical_url="",
    app_password="",
    secure_cookies=False,
    data_retention_days=-1,
)


def _loader(root: Path, fixture_path: str = "") -> GarminFixtureLoader:
    return GarminFixtureLoader(
        replace(BASE_CONFIG, garmin_fixture_path=fixture_path),
        root,
        lambda: datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
        lambda: UTC_NOW,
        EARLIEST_DATE,
        ALL_SYNC_DAYS,
    )


def _write_fixture(root: Path, path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class GarminFixtureLoaderTests(unittest.TestCase):
    def test_relative_absolute_and_unconfigured_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = _loader(root, "fixtures/garmin.json")
            absolute_path = root / "absolute.json"
            absolute = _loader(root, str(absolute_path))

            self.assertEqual(relative.path(), root / "fixtures/garmin.json")
            self.assertEqual(absolute.path(), absolute_path)
            self.assertIsNone(_loader(root).path())

    def test_unconfigured_missing_malformed_and_non_object_fixtures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(AppError) as unconfigured:
                _loader(root).load(2)
            self.assertEqual(unconfigured.exception.status, 503)
            self.assertEqual(
                unconfigured.exception.message,
                "GARMIN_FIXTURE_PATH ist nicht konfiguriert.",
            )

            missing = _loader(root, "missing.json")
            with self.assertRaises(AppError) as not_found:
                missing.load(2)
            self.assertEqual(not_found.exception.status, 503)
            self.assertEqual(
                not_found.exception.message,
                f"Garmin-Testdatei nicht gefunden: {root / 'missing.json'}",
            )

            malformed_path = root / "malformed.json"
            malformed_path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(AppError) as malformed:
                _loader(root, "malformed.json").load(2)
            self.assertEqual(malformed.exception.status, 503)
            self.assertTrue(
                malformed.exception.message.startswith(
                    "Garmin-Testdatei konnte nicht gelesen werden: "
                )
            )

            _write_fixture(root, root / "array.json", [1, 2])
            with self.assertRaises(AppError) as non_object:
                _loader(root, "array.json").load(2)
            self.assertEqual(non_object.exception.status, 503)
            self.assertEqual(
                non_object.exception.message,
                "Die Garmin-Testdatei muss ein JSON-Objekt enthalten.",
            )

    def test_load_defaults_ranges_existing_values_and_source_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = {
                "sleep": [{"calendarDate": "2026-09-18", "sleepScore": 80}],
                "source": "original",
                "synced_at": "old",
            }
            _write_fixture(root, root / "garmin.json", fixture)
            loader = _loader(root, "garmin.json")

            with patch("backend.sync.garmin.json.loads", return_value=fixture):
                copied = loader.load(2)
            self.assertEqual(fixture["source"], "original")
            self.assertEqual(fixture["synced_at"], "old")
            self.assertEqual(fixture["sleep"][0]["calendarDate"], "2026-09-18")
            copied["source"] = "changed"
            self.assertEqual(fixture["source"], "original")

            all_days = loader.load(ALL_SYNC_DAYS)
            self.assertEqual(all_days["start"], EARLIEST_DATE.isoformat())
            self.assertEqual(all_days["end"], TODAY.isoformat())
            self.assertEqual(all_days["synced_at"], UTC_NOW)
            self.assertEqual(all_days["errors"], [])
            self.assertEqual(all_days["source"], "fixture")
            self.assertEqual(all_days["sleep"][0]["calendarDate"], TODAY.isoformat())

            one_day = loader.load(0)
            self.assertEqual(one_day["start"], TODAY.isoformat())
            ninety_days = loader.load(91)
            self.assertEqual(ninety_days["start"], date(2026, 6, 23).isoformat())
            thirty_days = loader.load(30)
            self.assertEqual(thirty_days["start"], date(2026, 8, 22).isoformat())

            preserved_fixture = {
                "start": "2026-08-01",
                "end": "2026-08-31",
                "errors": [{"source": "fixture", "message": "synthetic"}],
                "source": "original",
                "synced_at": "old",
            }
            _write_fixture(root, root / "preserved.json", preserved_fixture)
            preserved = _loader(root, "preserved.json").load(2)
            self.assertEqual(preserved["start"], "2026-08-01")
            self.assertEqual(preserved["end"], "2026-08-31")
            self.assertEqual(preserved["errors"], preserved_fixture["errors"])
            self.assertEqual(preserved["source"], "fixture")
            self.assertEqual(preserved["synced_at"], UTC_NOW)
            self.assertEqual(
                json.loads((root / "preserved.json").read_text(encoding="utf-8")),
                preserved_fixture,
            )


class GarminSleepDateNormalizationTests(unittest.TestCase):
    def test_recursive_latest_date_shift_and_invalid_dates(self):
        fixture = {
            "nested": [
                {"calendarDate": "2026-09-18T00:00:00", "summaryDate": "not-a-date"},
                {"child": {"summaryDate": "2026-09-19", "calendarDate": "2026-02-30"}},
            ]
        }
        normalized = normalize_fixture_sleep_dates(fixture, TODAY)

        self.assertEqual(normalized["nested"][0]["calendarDate"], "2026-09-19")
        self.assertEqual(normalized["nested"][0]["summaryDate"], "not-a-date")
        self.assertEqual(normalized["nested"][1]["child"]["summaryDate"], "2026-09-20")
        self.assertEqual(normalized["nested"][1]["child"]["calendarDate"], "2026-02-30")
        self.assertEqual(fixture["nested"][0]["calendarDate"], "2026-09-18T00:00:00")

    def test_no_valid_dates_returns_original_value(self):
        fixture = [{"calendarDate": "invalid", "nested": [{"summaryDate": None}]}]
        self.assertIs(normalize_fixture_sleep_dates(fixture, TODAY), fixture)


class GarminMergeTests(unittest.TestCase):
    def test_merge_freshness_collections_metrics_morning_and_start(self):
        previous = {
            "source_freshness": {
                "sleep": {
                    "freshness": "current",
                    "fetched_at": "old",
                    "observed_at": "2026-09-18",
                    "extra": "kept only when stale",
                },
                "hrv": {
                    "freshness": "current",
                    "fetched_at": "old",
                    "observed_at": "2026-09-17",
                    "extra": "retained",
                },
                "body_battery": {"freshness": "current", "fetched_at": "old"},
                "weight": {
                    "freshness": "current",
                    "fetched_at": "old",
                    "observed_at": "2026-09-16",
                },
            },
            "sleep": [{"id": 1, "calendarDate": "2026-09-18"}],
            "hrv": [{"id": 2, "calendarDate": "2026-09-17"}],
            "body_battery": [{"id": 3, "calendarDate": "2026-09-16"}],
            "activities": [{"activityId": 10, "startTimeLocal": "2026-09-10T10:00:00"}],
            "daily_stats": [{"calendarDate": "2026-09-15"}],
            "readiness": {"calendarDate": "2026-09-18", "score": 60},
            "cycling_ftp": {"calendarDate": "2026-09-16", "watts": 280},
            "weight": {"calendarDate": "2026-09-16", "kg": 70},
            "max_metrics": {"watts": 400},
            "morning_body_battery": {"date": "2026-09-19", "value": 72},
            "start": "2026-08-01",
        }
        payload = {
            "synced_at": UTC_NOW,
            "errors": [
                {"source": "daily_stats", "message": "synthetic"},
                {"source": "cycling_ftp", "message": "synthetic"},
            ],
            "provider_sync": {
                "pagination": {
                    "sleep": {"complete": False},
                    "activities": {"complete": True},
                    "daily_stats": {"complete": True},
                    "readiness": {"complete": True},
                    "cycling_ftp": {"complete": True},
                }
            },
            "sleep": [{"id": 2, "calendarDate": "2026-09-20"}],
            "body_battery": [],
            "activities": [{"activityId": 11, "startTimeLocal": "2026-09-19T10:00:00"}],
            "daily_stats": [{"calendarDate": "2026-09-20"}],
            "heart_rate_zones": {"calendarDate": "2026-09-20", "zones": [1, 2]},
            "readiness": {"calendarDate": "2026-09-20", "score": 80},
            "cycling_ftp": {"calendarDate": "2026-09-20", "watts": 300},
            "start": "2026-09-01",
        }

        merge_sources(payload, previous)

        self.assertEqual([item["id"] for item in payload["sleep"]], [2, 1])
        self.assertEqual(payload["source_freshness"]["sleep"]["freshness"], "partial")
        self.assertEqual(payload["source_freshness"]["sleep"]["fetched_at"], UTC_NOW)
        self.assertEqual(
            payload["source_freshness"]["sleep"]["observed_at"], "2026-09-20"
        )
        self.assertEqual(payload["hrv"], previous["hrv"])
        self.assertEqual(payload["source_freshness"]["hrv"]["freshness"], "stale")
        self.assertEqual(payload["source_freshness"]["hrv"]["extra"], "retained")
        self.assertEqual(payload["body_battery"], previous["body_battery"])
        self.assertEqual(
            payload["source_freshness"]["body_battery"]["freshness"], "stale"
        )
        self.assertEqual(len(payload["activities"]), 2)
        self.assertEqual(
            payload["source_freshness"]["activities"]["freshness"], "current"
        )
        self.assertEqual(payload["daily_stats"][0]["calendarDate"], "2026-09-20")
        self.assertEqual(
            payload["source_freshness"]["daily_stats"]["freshness"], "partial"
        )
        self.assertEqual(
            payload["heart_rate_zones"], {"calendarDate": "2026-09-20", "zones": [1, 2]}
        )
        self.assertEqual(
            payload["source_freshness"]["readiness"]["freshness"], "current"
        )
        self.assertEqual(payload["cycling_ftp"]["watts"], 300)
        self.assertEqual(
            payload["source_freshness"]["cycling_ftp"]["freshness"], "partial"
        )
        self.assertEqual(payload["weight"], previous["weight"])
        self.assertEqual(payload["source_freshness"]["weight"]["freshness"], "stale")
        self.assertEqual(payload["max_metrics"], previous["max_metrics"])
        self.assertEqual(
            payload["source_freshness"]["max_metrics"]["freshness"], "stale"
        )
        self.assertEqual(
            payload["morning_body_battery"], previous["morning_body_battery"]
        )
        self.assertEqual(payload["start"], "2026-08-01")

    def test_collection_completion_truth_table(self):
        self.assertTrue(
            collection_complete(
                {"provider_sync": {"pagination": {"sleep": {"complete": True}}}}
            )
        )
        for payload in (
            {},
            {"provider_sync": {"pagination": {}}},
            {"provider_sync": {"pagination": {"sleep": {"complete": False}}}},
            {"provider_sync": {"pagination": {"sleep": {"complete": 1}}}},
            {
                "errors": [{"source": "sleep"}],
                "provider_sync": {"pagination": {"sleep": {"complete": True}}},
            },
        ):
            with self.subTest(payload=payload):
                self.assertFalse(collection_complete(payload))


class GarminSyncStateServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database_path = Path(self.temp_directory.name) / "garmin-state.db"
        self.manager = DatabaseManager(
            self.database_path, sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.now = datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc)
        self.local_now = datetime(
            2026, 9, 20, 12, 30, tzinfo=timezone(timedelta(hours=2))
        )
        self.key_values = KeyValueRepository(lambda: UTC_NOW)
        self.sync_state = SyncStateRepository(
            self.manager, self.key_values, SnapshotRepository(), lambda: UTC_NOW
        )
        self.daily_markers = DailySyncMarkerService(
            self.manager, self.key_values, lambda: self.local_now
        )
        self.redactor = Redactor(
            lambda: replace(BASE_CONFIG, garmin_password="synthetic-password")
        )
        self.service = self._service()

    def _service(self, key_values=None, daily_markers=None):
        key_values = key_values or self.key_values
        return GarminSyncStateService(
            self.manager,
            key_values,
            SyncStateRepository(
                self.manager, key_values, SnapshotRepository(), lambda: UTC_NOW
            ),
            daily_markers
            or DailySyncMarkerService(self.manager, key_values, lambda: self.local_now),
            self.redactor,
            lambda: UTC_NOW,
            lambda: self.now,
        )

    def _get(self, key):
        with self.manager.unit_of_work() as db:
            return self.key_values.get(db, key)

    def _set(self, key, value):
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, key, value)

    def test_persist_error_redacts_secrets_and_truncates_to_1000_characters(self):
        self.service.persist_error("synthetic-password " + "x" * 1100)

        raw = self._get("last_garmin_error")
        error = json.loads(raw)[0]
        self.assertEqual(error["source"], "sync")
        self.assertEqual(len(error["message"]), 1000)
        self.assertTrue(error["message"].startswith("[REDACTED]"))
        self.assertNotIn("synthetic-password", raw)
        self.assertEqual(
            raw,
            json.dumps(
                [{"source": "sync", "message": error["message"]}], ensure_ascii=False
            ),
        )

    def test_malformed_capability_state_and_pause_values_are_allowed(self):
        self._set("garmin_capability_sleep", "{not json")
        self.assertEqual(self.service.capability_state("sleep"), {})
        self.assertTrue(self.service.capability_allowed("sleep"))
        self._set("garmin_capability_sleep", "[]")
        self.assertEqual(self.service.capability_state("sleep"), {})

        for value in ("", "not-a-time", "2026-09-20T10:30:00"):
            with self.subTest(value=value):
                self._set(
                    "garmin_capability_sleep",
                    json.dumps({"paused_until": value}),
                )
                self.assertTrue(self.service.capability_allowed("sleep"))

        self._set(
            "garmin_capability_sleep",
            json.dumps({"paused_until": "2026-09-20T10:30:01Z"}),
        )
        self.assertFalse(self.service.capability_allowed("sleep"))
        self._set(
            "garmin_capability_sleep",
            json.dumps({"paused_until": "2026-09-20T10:30:00Z"}),
        )
        self.assertTrue(self.service.capability_allowed("sleep"))

    def test_failure_class_changes_reset_count_and_success_clears_existing_state(self):
        self.service.record_capability_failure("sleep", TimeoutError("network"))
        self.service.record_capability_failure("sleep", TimeoutError("network"))
        state = self.service.capability_state("sleep")
        self.assertEqual(state["error_class"], "network_error")
        self.assertEqual(state["count"], 2)

        self.service.record_capability_failure("sleep", TimeoutError("network"))
        state = self.service.capability_state("sleep")
        self.assertEqual(state["count"], 3)
        self.assertEqual(state["last_failed_at"], UTC_NOW)
        self.assertEqual(
            state["paused_until"],
            (self.now + timedelta(hours=24)).isoformat(),
        )
        self.assertFalse(self.service.capability_allowed("sleep"))

        self.service.record_capability_failure("sleep", RuntimeError("provider"))
        state = self.service.capability_state("sleep")
        self.assertEqual(state["error_class"], "temporary_error")
        self.assertEqual(state["count"], 1)
        self.assertNotIn("paused_until", state)
        self.service.record_capability_success("sleep")
        self.assertEqual(self._get("garmin_capability_sleep"), "")

    def test_error_entries_filter_non_dicts_and_preserve_compact_unicode_json(self):
        raw_errors = [
            {"source": "body_battery", "message": "morgens"},
            "malformed",
            {"source": "sleep", "message": "Fehler ä"},
        ]
        self.service.set_error_entries(raw_errors)

        self.assertEqual(self.service.error_entries(), [raw_errors[0], raw_errors[2]])
        self.assertEqual(self.service.core_error_entries(), [raw_errors[2]])
        self.assertEqual(
            self._get("last_garmin_error"),
            '[{"source":"body_battery","message":"morgens"},"malformed",'
            '{"source":"sleep","message":"Fehler ä"}]',
        )
        self._set("last_garmin_error", "[not json")
        self.assertEqual(self.service.error_entries(), [])
        self._set("last_garmin_error", "{}")
        self.assertEqual(self.service.error_entries(), [])

    def test_complete_payload_updates_snapshot_markers_errors_and_cursors(self):
        payload = {
            "synced_at": UTC_NOW,
            "end": "2026-09-19T22:00:00Z",
            "errors": [],
            "activities": [{"name": "synthetic ride ä"}],
            "provider_sync": {"pagination": {"activities": {"complete": True}}},
        }

        result = self.service.persist_payload(
            payload,
            date(2026, 8, 1),
            date(2026, 9, 20),
            source="fixture",
            historical_cursor="2026-07-31",
        )

        self.assertEqual(
            result,
            {
                "status": "ok",
                "synced_at": UTC_NOW,
                "errors": 0,
                "activities": 1,
                "pagination": payload["provider_sync"]["pagination"],
                "source": "fixture",
            },
        )
        self.assertEqual(
            self._get("garmin_snapshot"),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        self.assertEqual(self._get("last_garmin_sync_at"), UTC_NOW)
        self.assertEqual(self._get("last_garmin_error"), "")
        self.assertIsNone(self._get("sync_garmin_last_success_at"))
        self.assertEqual(
            self.sync_state.cursor("garmin", "data")["cursor"], "2026-09-19"
        )
        self.assertEqual(
            self.sync_state.cursor("garmin", "historical")["cursor"],
            "2026-07-31",
        )

    def test_partial_payload_keeps_cursors_and_serializes_errors_and_source(self):
        self.sync_state.update_cursor(
            "garmin", "data", "2026-09-10", "2026-09-10T12:00:00+00:00"
        )
        self.sync_state.update_cursor(
            "garmin", "historical", "2026-08-01", "2026-09-10T12:00:00+00:00"
        )
        payload = {
            "synced_at": UTC_NOW,
            "errors": [{"source": "sleep", "message": "Teilweise ä"}],
            "activities": [],
            "provider_sync": {"pagination": {"sleep": {"complete": False}}},
        }

        result = self.service.persist_payload(
            payload,
            date(2026, 8, 1),
            date(2026, 9, 20),
            source="fixture",
            historical_cursor="2026-07-01",
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["activities"], 0)
        self.assertEqual(result["source"], "fixture")
        self.assertEqual(
            self._get("last_garmin_error"),
            json.dumps(payload["errors"], ensure_ascii=False),
        )
        self.assertEqual(
            self.sync_state.cursor("garmin", "data")["cursor"], "2026-09-10"
        )
        self.assertEqual(
            self.sync_state.cursor("garmin", "historical")["cursor"], "2026-08-01"
        )
        self.assertIsNone(self._get("sync_garmin_last_success_at"))

    def test_current_refresh_marks_success_timestamp(self):
        payload = {
            "synced_at": UTC_NOW,
            "end": "2026-09-20",
            "errors": [],
            "activities": [],
            "provider_sync": {"pagination": {"activities": {"complete": True}}},
        }

        self.service.persist_payload(payload, None, date(2026, 9, 20))

        self.assertEqual(self._get("sync_garmin_last_success_at"), self.local_now.isoformat())

    def test_payload_failure_keeps_prior_writes_and_stops_before_cursors(self):
        class FailingKeyValueRepository(KeyValueRepository):
            def __init__(self, events):
                super().__init__(lambda: UTC_NOW)
                self.events = events

            def set(self, db, key, value):
                self.events.append(key)
                super().set(db, key, value)
                if key == "last_garmin_error":
                    raise RuntimeError("synthetic write failure")

        events = []
        repository = FailingKeyValueRepository(events)
        markers = DailySyncMarkerService(
            self.manager, repository, lambda: self.local_now
        )
        service = self._service(repository, markers)
        payload = {
            "synced_at": UTC_NOW,
            "end": "2026-09-19",
            "errors": [],
            "activities": [],
            "provider_sync": {"pagination": {"activities": {"complete": True}}},
        }

        with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
            service.persist_payload(
                payload,
                date(2026, 8, 1),
                date(2026, 9, 20),
                historical_cursor="2026-07-01",
            )

        self.assertEqual(
            events,
            [
                "garmin_snapshot",
                "last_garmin_sync_at",
                "last_garmin_error",
            ],
        )
        self.assertEqual(json.loads(self._get("garmin_snapshot")), payload)
        self.assertEqual(self._get("last_garmin_sync_at"), UTC_NOW)
        self.assertIsNone(self._get("sync_garmin_last_success_at"))
        self.assertIsNone(self.sync_state.cursor("garmin", "data")["cursor"])
        self.assertIsNone(self.sync_state.cursor("garmin", "historical")["cursor"])


if __name__ == "__main__":
    unittest.main()
