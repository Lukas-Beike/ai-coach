from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any
from unittest.mock import Mock

from support import make_config, temp_database

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID
from backend.config import Config
from backend.db import row_factory
from backend.db.repositories import KeyValueRepository
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.freshness import ProviderFreshnessService, provider_freshness_state
from backend.sync.freshness_sources import (
    DEFAULT_FRESHNESS_SOURCES,
    GARMIN_CORE_ERROR_SIGNAL,
    GARMIN_TOKENSTORE_SIGNAL,
    WEATHER_CACHE_KEY,
    WEATHER_FAILURE_KEY,
    FreshnessInputs,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_table import CALENDAR_ID, WEATHER_ID
from backend.sync.status import SyncPublicStateService

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
CALENDAR_URL = "https://calendar.example.test/feed.ics"
CALENDAR_AT_KEY = "last_external_calendar_sync_at"
CALENDAR_ERROR_KEY = "last_external_calendar_sync_error"
TABLE_AREAS = DEFAULT_PROVIDER_REGISTRY.freshness_areas()


def _inputs(
    *,
    config: Config | None = None,
    values: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
) -> FreshnessInputs:
    merged_signals: dict[str, Any] = {
        GARMIN_CORE_ERROR_SIGNAL: False,
        GARMIN_TOKENSTORE_SIGNAL: False,
    }
    merged_signals.update(signals or {})
    stored = dict(values or {})
    return FreshnessInputs(
        config=make_config() if config is None else config,
        get_value=stored.get,
        profile=dict(profile or {}),
        signals=merged_signals,
    )


class DefaultFreshnessSourceTests(unittest.TestCase):
    def test_sources_cover_exactly_the_registry_freshness_areas(self) -> None:
        declared = {
            (provider_id, area.area)
            for provider_id, area in DEFAULT_PROVIDER_REGISTRY.freshness_areas()
        }
        bound = {
            (provider_id, area)
            for provider_id, areas in DEFAULT_FRESHNESS_SOURCES.items()
            for area in areas
        }
        self.assertEqual(bound, declared)
        self.assertIsInstance(DEFAULT_FRESHNESS_SOURCES, MappingProxyType)

    def test_garmin_is_configured_by_any_single_credential_source(self) -> None:
        source = DEFAULT_FRESHNESS_SOURCES[GARMIN_ID]["data"]
        cases: tuple[tuple[Config, dict[str, bool], bool], ...] = (
            (make_config(garmin_fixture_path="fixture"), {}, True),
            (make_config(garmin_email="athlete@example.test"), {}, True),
            (make_config(), {GARMIN_TOKENSTORE_SIGNAL: True}, True),
            (make_config(), {}, False),
        )
        for config, signals, expected in cases:
            with self.subTest(config=config, signals=signals):
                self.assertIs(
                    source.configured(_inputs(config=config, signals=signals)),
                    expected,
                )

    def test_garmin_fallbacks_read_last_sync_and_core_error_signal(self) -> None:
        source = DEFAULT_FRESHNESS_SOURCES[GARMIN_ID]["data"]
        inputs = _inputs(
            values={
                "last_garmin_sync_at": "2026-09-15T10:00:00+00:00",
                "last_garmin_error": "not-the-fallback",
            },
            signals={GARMIN_CORE_ERROR_SIGNAL: True},
        )
        self.assertEqual(source.fallback_at(inputs), "2026-09-15T10:00:00+00:00")
        self.assertIs(source.fallback_error(inputs), True)

    def test_garmin_reads_missing_signals_as_absent_instead_of_raising(self) -> None:
        source = DEFAULT_FRESHNESS_SOURCES[GARMIN_ID]["data"]
        bare = FreshnessInputs(
            config=make_config(),
            get_value=lambda key: None,
            profile={},
            signals={},
        )
        self.assertFalse(source.configured(bare))
        self.assertIs(source.fallback_error(bare), False)

    def test_weather_is_configured_only_by_a_profile_location(self) -> None:
        source = DEFAULT_FRESHNESS_SOURCES[WEATHER_ID]["forecast"]
        self.assertTrue(
            source.configured(_inputs(profile={"weather_location": "Berlin"}))
        )
        self.assertFalse(source.configured(_inputs(profile={"weather_location": ""})))
        self.assertFalse(source.configured(_inputs()))

    def test_weather_fallbacks_read_cache_timestamp_and_failure_marker(self) -> None:
        source = DEFAULT_FRESHNESS_SOURCES[WEATHER_ID]["forecast"]
        cached = _inputs(
            values={
                WEATHER_CACHE_KEY: json.dumps({"fetched_at": "2026-09-15T11:30:00Z"})
            }
        )
        self.assertEqual(source.fallback_at(cached), "2026-09-15T11:30:00Z")
        failed = _inputs(values={WEATHER_FAILURE_KEY: "weather_down"})
        self.assertEqual(source.fallback_error(failed), "weather_down")

    def test_weather_cache_yields_no_timestamp_when_unreadable_or_not_an_object(
        self,
    ) -> None:
        source = DEFAULT_FRESHNESS_SOURCES[WEATHER_ID]["forecast"]
        cases: dict[str, Any] = {
            "missing": None,
            "empty text": "",
            "malformed JSON": "{not json",
            "non-object JSON": json.dumps(["2026-09-15T11:30:00Z"]),
            "object without timestamp": json.dumps({"other": 1}),
            "non-text value": 5,
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                inputs = _inputs(values={WEATHER_CACHE_KEY: value})
                self.assertIsNone(source.fallback_at(inputs))

    def test_calendar_reads_stored_settings_and_configured_url(self) -> None:
        source = DEFAULT_FRESHNESS_SOURCES[CALENDAR_ID]["events"]
        inputs = _inputs(
            config=make_config(
                calendar_ical_url="https://calendar.example.test/feed.ics"
            ),
            values={
                "last_external_calendar_sync_at": "calendar-at",
                "last_external_calendar_sync_error": "calendar-error",
            },
        )
        self.assertEqual(source.fallback_at(inputs), "calendar-at")
        self.assertEqual(source.fallback_error(inputs), "calendar-error")
        self.assertTrue(source.configured(inputs))
        self.assertFalse(source.configured(_inputs()))


class _DatabaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(
            self, "freshness-sources.sqlite", row_factory=row_factory, schema=True
        )
        self.key_values = KeyValueRepository(lambda: NOW.isoformat())

    def set_values(self, **values: str) -> None:
        with self.manager.unit_of_work() as db:
            for key, value in values.items():
                self.key_values.set(db, key, value)


class FreshnessProjectionTests(_DatabaseCase):
    def _project(self, **config: str) -> dict[tuple[str, str], dict[str, Any]]:
        with self.manager.unit_of_work() as db:
            items = provider_freshness_state(
                db,
                config=make_config(**config),
                get_value=lambda key: self.key_values.get(db, key),
                profile={},
                garmin_has_core_error=False,
                garmin_tokenstore_exists=False,
                now=NOW,
            )
        return {(item["provider"], item["area"]): item for item in items}

    def _calendar(self, *, configured: bool = True) -> dict[str, Any]:
        url = CALENDAR_URL if configured else ""
        return self._project(calendar_ical_url=url)[CALENDAR_ID, "events"]

    def test_projection_lists_every_table_area_in_table_order(self) -> None:
        self.assertEqual(
            [(provider, area.area) for provider, area in TABLE_AREAS],
            list(self._project()),
        )

    def test_calendar_area_carries_label_read_only_flag_and_its_stale_threshold(
        self,
    ) -> None:
        threshold = timedelta(hours=48)
        cases = (
            (NOW - threshold + timedelta(hours=1), "fresh", False),
            (NOW - threshold, "fresh", False),
            (NOW - threshold - timedelta(hours=1), "stale", True),
        )
        for last_sync, state, stale in cases:
            with self.subTest(state=state):
                self.set_values(**{CALENDAR_AT_KEY: last_sync.isoformat()})
                item = self._calendar()
                self.assertEqual(item["label"], "Gemeinsamer Kalender")
                self.assertTrue(item["read_only"])
                self.assertTrue(item["configured"])
                self.assertEqual(item["state"], state)
                self.assertIs(item["stale"], stale)
                self.assertEqual(item["last_success_at"], last_sync.isoformat())
                self.assertEqual(item["last_attempt_at"], last_sync.isoformat())
                self.assertTrue(item["has_last_good"])

    def test_a_skipped_row_is_neither_a_success_nor_the_latest_attempt(self) -> None:
        rows = (
            ("ok", NOW - timedelta(hours=3), "success", None),
            ("failed", NOW - timedelta(hours=2), "error", "provider_error"),
            # Lock contention: a newer row that must not hide the failure above.
            ("busy", NOW - timedelta(hours=1), "skipped", None),
        )
        with self.manager.unit_of_work() as db:
            for row_id, started, status, error_code in rows:
                db.execute(
                    "INSERT INTO provider_refresh_history(id, provider, area, "
                    "operation_id, trigger, started_at, finished_at, phase, status, "
                    "error_code) VALUES (?, ?, ?, 'op', 'test', ?, ?, 'complete', ?, ?)",
                    (
                        row_id,
                        CALENDAR_ID,
                        "events",
                        started.isoformat(),
                        (started + timedelta(minutes=1)).isoformat(),
                        status,
                        error_code,
                    ),
                )

        item = self._calendar()

        self.assertEqual(item["state"], "stale")
        self.assertEqual(item["error_code"], "provider_error")
        self.assertEqual(
            item["last_attempt_at"], (NOW - timedelta(hours=2)).isoformat()
        )
        self.assertEqual(
            item["last_success_at"],
            (NOW - timedelta(hours=3) + timedelta(minutes=1)).isoformat(),
        )

    def test_output_only_area_never_ages_into_stale(self) -> None:
        last_push = NOW - timedelta(days=30)
        self.set_values(last_competition_sync_at=last_push.isoformat())

        item = self._project(intervals_api_key="key")[INTERVALS_ID, "competitions"]

        self.assertFalse(item["read_only"])
        self.assertEqual(item["state"], "fresh")
        self.assertIs(item["stale"], False)

        # A stored push error without a history row must still need attention.
        self.set_values(last_competition_sync_error="push failed")
        failed = self._project(intervals_api_key="key")[INTERVALS_ID, "competitions"]
        self.assertEqual(failed["state"], "stale")
        self.assertEqual(failed["error_code"], "provider_error")

    def test_unconfigured_and_error_states_use_the_providers_own_settings(
        self,
    ) -> None:
        self.set_values(**{CALENDAR_ERROR_KEY: "upstream failed"})

        unconfigured = self._calendar(configured=False)
        self.assertFalse(unconfigured["configured"])
        self.assertEqual(unconfigured["state"], "not_configured")
        self.assertEqual(unconfigured["error_code"], "provider_error")

        failed = self._calendar()
        self.assertEqual(failed["state"], "error")
        self.assertEqual(failed["error_code"], "provider_error")
        self.assertIsNone(failed["last_success_at"])
        self.assertFalse(failed["has_last_good"])


class StatusFreshnessTests(_DatabaseCase):
    def test_status_carries_provider_freshness_and_the_running_probe(self) -> None:
        active = {"running": False}
        self.set_values(**{CALENDAR_AT_KEY: (NOW - timedelta(hours=3)).isoformat()})
        freshness = ProviderFreshnessService(
            make_config(calendar_ical_url=CALENDAR_URL),
            self.manager,
            self.key_values,
            lambda: NOW,
        )
        profile = Mock()
        profile.get.return_value = {}
        garmin = Mock()
        garmin.core_error_entries.return_value = []
        versions = Mock()
        versions.versions.return_value = {}
        jobs = Mock()
        jobs.list.return_value = []
        status = SyncPublicStateService(
            make_config(
                calendar_ical_url=CALENDAR_URL,
                garmin_tokenstore=str(Path(self.manager.path).parent / "t"),
            ),
            self.manager,
            self.key_values,
            freshness,
            profile,
            garmin,
            MaintenanceGate(),
            jobs,
            versions,
            running_probes={WAHOO_ID: lambda: active["running"]},
        )

        idle = status.state()
        self.assertFalse(idle["running"])
        [item] = [
            entry
            for entry in idle["provider_freshness"]
            if entry["provider"] == CALENDAR_ID
        ]
        self.assertEqual(item["label"], "Gemeinsamer Kalender")
        self.assertEqual(item["state"], "fresh")
        self.assertFalse(item["stale"])
        self.assertEqual(
            item["last_success_at"], (NOW - timedelta(hours=3)).isoformat()
        )

        active["running"] = True
        self.assertTrue(status.state()["running"])


if __name__ == "__main__":
    unittest.main()
