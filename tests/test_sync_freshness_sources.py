from __future__ import annotations

import dataclasses
import json
import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any
from unittest.mock import Mock

from provider_runtime_fakes import (
    ACME_AREA,
    ACME_ID,
    acme_descriptor,
    acme_freshness_source,
    fake_binding,
)
from support import make_config

from backend.config import Config
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.providers.descriptors import (
    CALENDAR_ID,
    DEFAULT_PROVIDER_DESCRIPTORS,
    GARMIN_ID,
    INTERVALS_ID,
    WEATHER_ID,
)
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.freshness import ProviderFreshnessService, provider_freshness_state
from backend.sync.freshness_sources import (
    DEFAULT_FRESHNESS_SOURCES,
    GARMIN_CORE_ERROR_SIGNAL,
    GARMIN_TOKENSTORE_SIGNAL,
    WEATHER_CACHE_KEY,
    WEATHER_FAILURE_KEY,
    default_running_probes,
    intervals_running_probe,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import FreshnessInputs, ProviderRuntimeRegistry
from backend.sync.status import SyncPublicStateService

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
ACME_REGISTRY = ProviderRegistry((*DEFAULT_PROVIDER_DESCRIPTORS, acme_descriptor()))
ACME_AT_KEY = "acme_last_sync_at"
ACME_ERROR_KEY = "acme_last_sync_error"


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

    def test_intervals_sources_read_stored_timestamp_and_error_settings(self) -> None:
        pairs = {
            "activities": ("last_sync_at", "last_sync_error"),
            "competitions": ("last_competition_sync_at", "last_competition_sync_error"),
            "performance": ("last_performance_refresh_at", "last_performance_error"),
        }
        sources = DEFAULT_FRESHNESS_SOURCES[INTERVALS_ID]
        self.assertEqual(set(sources), set(pairs))
        for area, (at_key, error_key) in pairs.items():
            with self.subTest(area=area):
                source = sources[area]
                inputs = _inputs(
                    config=make_config(intervals_api_key="configured"),
                    values={at_key: "stored-at", error_key: "stored-error"},
                )
                self.assertEqual(source.fallback_at(inputs), "stored-at")
                self.assertEqual(source.fallback_error(inputs), "stored-error")
                self.assertTrue(source.configured(inputs))
                self.assertFalse(source.configured(_inputs()))

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
            config=make_config(calendar_ical_url="https://calendar.example.test/feed.ics"),
            values={
                "last_external_calendar_sync_at": "calendar-at",
                "last_external_calendar_sync_error": "calendar-error",
            },
        )
        self.assertEqual(source.fallback_at(inputs), "calendar-at")
        self.assertEqual(source.fallback_error(inputs), "calendar-error")
        self.assertTrue(source.configured(inputs))
        self.assertFalse(source.configured(_inputs()))


def _getter(values: dict[str, Any]) -> Callable[[str], Any]:
    return lambda key: values.get(key)


class RunningProbeTests(unittest.TestCase):
    def test_intervals_probe_is_true_while_its_sync_lock_is_held(self) -> None:
        lock = threading.Lock()
        probe = intervals_running_probe(lock, _getter({}))
        self.assertFalse(probe())
        lock.acquire()
        try:
            self.assertTrue(probe())
        finally:
            lock.release()

    def test_intervals_probe_treats_only_the_exact_stored_flag_as_running(self) -> None:
        lock = threading.Lock()
        cases = (("1", True), ("0", False), ("true", False), (None, False))
        for value, expected in cases:
            with self.subTest(value=value):
                probe = intervals_running_probe(lock, _getter({"sync_running": value}))
                self.assertIs(probe(), expected)

    def test_default_probes_name_only_intervals_and_are_read_only(self) -> None:
        lock = threading.Lock()
        probes = default_running_probes(
            intervals_sync_lock=lock,
            get_value=_getter({"sync_running": "1"}),
        )
        self.assertIsInstance(probes, MappingProxyType)
        self.assertEqual(list(probes), [INTERVALS_ID])
        self.assertTrue(probes[INTERVALS_ID]())


def _acme_runtime(*, running: Any = None) -> ProviderRuntimeRegistry:
    """Bind the test-only acme-mock provider with its default freshness source."""
    binding = fake_binding()
    if running is not None:
        binding = dataclasses.replace(binding, running_probe=running)
    return ProviderRuntimeRegistry(ACME_REGISTRY, [binding])


class _DatabaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "freshness-sources.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW.isoformat())

    def set_values(self, **values: str) -> None:
        with self.manager.unit_of_work() as db:
            for key, value in values.items():
                self.key_values.set(db, key, value)


class AcmeMockProjectionTests(_DatabaseCase):
    def _project(
        self,
        runtime: ProviderRuntimeRegistry,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        with self.manager.unit_of_work() as db:
            return provider_freshness_state(
                db,
                config=make_config(),
                get_value=lambda key: self.key_values.get(db, key),
                profile=profile,
                garmin_has_core_error=False,
                garmin_tokenstore_exists=False,
                now=NOW,
                freshness_sources=runtime.freshness_sources(),
                registry=ACME_REGISTRY,
            )

    def test_acme_area_carries_label_read_only_flag_and_its_stale_threshold(
        self,
    ) -> None:
        runtime = _acme_runtime()
        threshold = timedelta(hours=48)
        cases = (
            (NOW - threshold + timedelta(hours=1), "fresh", False),
            (NOW - threshold, "fresh", False),
            (NOW - threshold - timedelta(hours=1), "stale", True),
        )
        for last_sync, state, stale in cases:
            with self.subTest(state=state):
                self.set_values(**{ACME_AT_KEY: last_sync.isoformat()})
                [item] = self._project(runtime, {"acme_enabled": True})
                self.assertEqual(item["provider"], ACME_ID)
                self.assertEqual(item["area"], ACME_AREA)
                self.assertEqual(item["label"], "Acme mock · Training")
                self.assertTrue(item["read_only"])
                self.assertTrue(item["configured"])
                self.assertEqual(item["state"], state)
                self.assertIs(item["stale"], stale)
                self.assertEqual(item["last_success_at"], last_sync.isoformat())
                self.assertEqual(item["last_attempt_at"], last_sync.isoformat())
                self.assertTrue(item["has_last_good"])

    def test_acme_unconfigured_and_error_states_use_its_own_settings(self) -> None:
        runtime = _acme_runtime()
        self.set_values(**{ACME_ERROR_KEY: "upstream failed"})

        [unconfigured] = self._project(runtime, {})
        self.assertFalse(unconfigured["configured"])
        self.assertEqual(unconfigured["state"], "not_configured")
        self.assertEqual(unconfigured["error_code"], "provider_error")

        [failed] = self._project(runtime, {"acme_enabled": True})
        self.assertEqual(failed["state"], "error")
        self.assertEqual(failed["error_code"], "provider_error")
        self.assertIsNone(failed["last_success_at"])
        self.assertFalse(failed["has_last_good"])

    def test_provider_without_sources_is_absent_from_projection(self) -> None:
        with self.manager.unit_of_work() as db:
            result = provider_freshness_state(
                db,
                config=make_config(),
                get_value=lambda key: None,
                profile={},
                garmin_has_core_error=False,
                garmin_tokenstore_exists=False,
                now=NOW,
                freshness_sources={},
                registry=ACME_REGISTRY,
            )
        self.assertEqual(result, [])

    def test_bound_provider_must_supply_exactly_its_declared_areas(self) -> None:
        with (
            self.manager.unit_of_work() as db,
            self.assertRaisesRegex(ValueError, "must cover exactly"),
        ):
            provider_freshness_state(
                db,
                config=make_config(),
                get_value=lambda key: None,
                profile={},
                garmin_has_core_error=False,
                garmin_tokenstore_exists=False,
                now=NOW,
                freshness_sources={ACME_ID: {}},
                registry=ACME_REGISTRY,
            )

    def test_source_for_undeclared_provider_is_rejected(self) -> None:
        with (
            self.manager.unit_of_work() as db,
            self.assertRaisesRegex(ValueError, "undeclared provider"),
        ):
            provider_freshness_state(
                db,
                config=make_config(),
                get_value=lambda key: None,
                profile={},
                garmin_has_core_error=False,
                garmin_tokenstore_exists=False,
                now=NOW,
                freshness_sources={"undeclared": {ACME_AREA: acme_freshness_source()}},
                registry=ACME_REGISTRY,
            )


class AcmeMockStatusTests(_DatabaseCase):
    def test_status_carries_acme_freshness_and_its_running_probe(self) -> None:
        active = {"running": False}
        runtime = _acme_runtime(running=lambda: active["running"])
        self.set_values(**{ACME_AT_KEY: (NOW - timedelta(hours=3)).isoformat()})
        freshness = ProviderFreshnessService(
            make_config(),
            self.manager,
            self.key_values,
            lambda: NOW,
            freshness_sources=runtime.freshness_sources(),
            registry=ACME_REGISTRY,
        )
        profile = Mock()
        profile.get.return_value = {"acme_enabled": True}
        garmin = Mock()
        garmin.core_error_entries.return_value = []
        versions = Mock()
        versions.versions.return_value = {}
        jobs = Mock()
        jobs.list.return_value = []
        status = SyncPublicStateService(
            make_config(garmin_tokenstore=str(Path(self.temporary_directory.name) / "t")),
            self.manager,
            self.key_values,
            freshness,
            profile,
            garmin,
            MaintenanceGate(),
            jobs,
            versions,
            threading.Lock(),
            running_probes=runtime.running_probes(),
        )

        idle = status.state()
        self.assertFalse(idle["running"])
        [item] = idle["provider_freshness"]
        self.assertEqual(item["provider"], ACME_ID)
        self.assertEqual(item["label"], "Acme mock · Training")
        self.assertEqual(item["state"], "fresh")
        self.assertFalse(item["stale"])
        self.assertEqual(
            item["last_success_at"], (NOW - timedelta(hours=3)).isoformat()
        )

        active["running"] = True
        self.assertTrue(status.state()["running"])


if __name__ == "__main__":
    unittest.main()
