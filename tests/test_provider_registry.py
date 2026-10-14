"""Parity and contract tests for provider descriptors and the sync registry.

The literal tables below are the values synchronization used before provider
data moved into descriptors. They pin the derived output byte-for-byte.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import unittest
from datetime import UTC, datetime
from typing import Any

from backend.config import Config
from backend.http_api.sync_commands import PROVIDER_NOT_CONFIGURED_MESSAGES
from backend.providers.descriptors import (
    DEFAULT_PROVIDER_DESCRIPTORS,
    Capability,
    FreshnessArea,
    ManualSyncRoute,
    ProviderDescriptor,
    SchedulePolicy,
)
from backend.sync.freshness import (
    PROVIDER_REFRESH_LABELS,
    PROVIDER_REFRESH_STALE_SECONDS,
    provider_freshness_state,
)
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS
from backend.sync.jobs import JOB_TYPES, PROVIDERS
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
TWO_DAYS = 48 * 60 * 60
THREE_HOURS = 3 * 60 * 60

PREVIOUS_STALE_SECONDS: dict[tuple[str, str], int] = {
    ("intervals", "activities"): TWO_DAYS,
    ("intervals", "competitions"): TWO_DAYS,
    ("intervals", "performance"): TWO_DAYS,
    ("garmin", "data"): TWO_DAYS,
    ("weather", "forecast"): THREE_HOURS,
    ("calendar", "events"): TWO_DAYS,
    ("wahoo", "activities"): TWO_DAYS,
}
PREVIOUS_LABELS: dict[tuple[str, str], str] = {
    ("intervals", "activities"): "Intervals.icu · Training",
    ("intervals", "competitions"): "Intervals.icu · Wettkämpfe",
    ("intervals", "performance"): "Intervals.icu · Leistung",
    ("garmin", "data"): "Garmin",
    ("weather", "forecast"): "Open-Meteo",
    ("calendar", "events"): "Gemeinsamer Kalender",
    ("wahoo", "activities"): "Wahoo",
}
PREVIOUS_PROJECTION: list[tuple[str, str, str, bool]] = [
    ("intervals", "activities", "Intervals.icu · Training", True),
    ("intervals", "competitions", "Intervals.icu · Wettkämpfe", False),
    ("intervals", "performance", "Intervals.icu · Leistung", True),
    ("garmin", "data", "Garmin", True),
    ("weather", "forecast", "Open-Meteo", True),
    ("calendar", "events", "Gemeinsamer Kalender", True),
    ("wahoo", "activities", "Wahoo", True),
]


def _config() -> Config:
    return Config(
        port=8090,
        openai_api_key="",
        openai_base_url="https://api.openai.com/v1",
        openai_model="model",
        intervals_api_key="",
        intervals_athlete_id="0",
        garmin_email="",
        garmin_password="",
        garmin_tokenstore="unused",
        garmin_fixture_path="",
        calendar_ical_url="",
        app_password="",
        secure_cookies=False,
        data_retention_days=-1,
    )


def _empty_database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE provider_refresh_history (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, area TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, phase TEXT,
            status TEXT NOT NULL, error_code TEXT
        );
        CREATE TABLE sync_jobs (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, type TEXT NOT NULL,
            status TEXT NOT NULL, available_at TEXT
        );
        """
    )
    return db


def _area(area: str = "activities", label: str = "Mock") -> FreshnessArea:
    return FreshnessArea(area=area, label=label, stale_after_s=TWO_DAYS, read_only=True)


def _descriptor(
    provider_id: str = "wahoo-mock",
    *,
    areas: tuple[FreshnessArea, ...] | None = None,
    max_sync_days: int = 30,
    capabilities: frozenset[Capability] = frozenset({Capability.ACTIVITIES}),
    resync_keys: tuple[str, ...] = (),
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        label="Mock provider",
        capabilities=capabilities,
        freshness_areas=(_area(),) if areas is None else areas,
        max_sync_days=max_sync_days,
        resync_keys=resync_keys,
    )


class DefaultDescriptorParityTests(unittest.TestCase):
    def test_stale_seconds_match_previous_literal_table(self) -> None:
        self.assertEqual(PREVIOUS_STALE_SECONDS, PROVIDER_REFRESH_STALE_SECONDS)
        self.assertEqual(
            list(PREVIOUS_STALE_SECONDS), list(PROVIDER_REFRESH_STALE_SECONDS)
        )

    def test_labels_match_previous_literal_table(self) -> None:
        self.assertEqual(PREVIOUS_LABELS, PROVIDER_REFRESH_LABELS)
        self.assertEqual(list(PREVIOUS_LABELS), list(PROVIDER_REFRESH_LABELS))

    def test_provider_order_is_intervals_garmin_weather_calendar_wahoo(self) -> None:
        self.assertEqual(
            ("intervals", "garmin", "weather", "calendar", "wahoo"),
            DEFAULT_PROVIDER_REGISTRY.ids(),
        )
        self.assertEqual(
            tuple(
                (provider_id, area.area)
                for provider_id, area in DEFAULT_PROVIDER_REGISTRY.freshness_areas()
            ),
            tuple(PREVIOUS_LABELS),
        )

    def test_projection_order_labels_and_read_only_match_previous_contract(
        self,
    ) -> None:
        db = _empty_database()
        self.addCleanup(db.close)
        result = provider_freshness_state(
            db,
            config=_config(),
            get_value=lambda key: None,
            profile={},
            garmin_has_core_error=False,
            garmin_tokenstore_exists=False,
            now=NOW,
        )
        self.assertEqual(
            PREVIOUS_PROJECTION,
            [
                (row["provider"], row["area"], row["label"], row["read_only"])
                for row in result
            ],
        )

    def test_only_intervals_competitions_is_writable(self) -> None:
        writable = [
            (provider_id, area.area)
            for provider_id, area in DEFAULT_PROVIDER_REGISTRY.freshness_areas()
            if not area.read_only
        ]
        self.assertEqual([("intervals", "competitions")], writable)

    def test_max_sync_days_match_previous_window_rule(self) -> None:
        for provider_id in ("intervals", "garmin", "weather", "calendar", "unknown"):
            with self.subTest(provider_id=provider_id):
                expected = 365 if provider_id == "intervals" else 90
                self.assertEqual(
                    expected, DEFAULT_PROVIDER_REGISTRY.max_sync_days(provider_id)
                )

    def test_accepts_sync_days_within_limit_or_whole_history(self) -> None:
        cases = {
            ("garmin", 1): True,
            ("garmin", 90): True,
            ("garmin", 91): False,
            ("garmin", 0): False,
            ("garmin", -2): False,
            ("garmin", -1): True,
            ("intervals", 365): True,
            ("intervals", 366): False,
        }
        for (provider_id, days), expected in cases.items():
            with self.subTest(provider_id=provider_id, days=days):
                self.assertEqual(
                    expected,
                    DEFAULT_PROVIDER_REGISTRY.accepts_sync_days(provider_id, days, -1),
                )

    def test_resync_keys_match_full_resync_table(self) -> None:
        for provider_id in ("intervals", "garmin", "wahoo"):
            with self.subTest(provider_id=provider_id):
                keys = PROVIDER_RESYNC_KEYS[provider_id]
                self.assertEqual(
                    (
                        keys["running"],
                        keys["status"],
                        keys["last_at"],
                        keys["error"],
                    ),
                    DEFAULT_PROVIDER_REGISTRY.get(provider_id).resync_keys,
                )
        self.assertEqual((), DEFAULT_PROVIDER_REGISTRY.get("weather").resync_keys)
        self.assertEqual((), DEFAULT_PROVIDER_REGISTRY.get("calendar").resync_keys)

    def test_capabilities_are_assigned_per_provider(self) -> None:
        registry = DEFAULT_PROVIDER_REGISTRY
        self.assertEqual(
            ("intervals", "garmin", "wahoo"), registry.ids_with(Capability.ACTIVITIES)
        )
        self.assertEqual(
            ("intervals", "wahoo"), registry.ids_with(Capability.WORKOUT_EXPORT)
        )
        self.assertEqual(("intervals",), registry.ids_with(Capability.COMPETITIONS))
        self.assertEqual(("weather",), registry.ids_with(Capability.WEATHER_FORECAST))
        self.assertEqual(("calendar",), registry.ids_with(Capability.PUBLIC_CALENDAR))
        self.assertEqual(("intervals",), registry.ids_with(Capability.PLANNED_EVENTS))
        # Wahoo reads body and threshold values only as lowest-priority fallbacks.
        self.assertEqual(
            ("intervals", "garmin", "wahoo"), registry.ids_with(Capability.BODY)
        )
        self.assertEqual(
            ("intervals", "garmin", "wahoo"), registry.ids_with(Capability.THRESHOLDS)
        )

    def test_registry_exposes_default_descriptors_unchanged(self) -> None:
        self.assertEqual(DEFAULT_PROVIDER_DESCRIPTORS, DEFAULT_PROVIDER_REGISTRY.all())

    def test_default_descriptors_are_frozen(self) -> None:
        descriptor = DEFAULT_PROVIDER_REGISTRY.get("garmin")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            descriptor.max_sync_days = 1  # type: ignore[misc]


class RegistryContractTests(unittest.TestCase):
    def test_mock_provider_flows_through_every_lookup(self) -> None:
        mock = _descriptor(
            "wahoo-mock",
            areas=(_area("activities", "Wahoo mock · Training"),),
            max_sync_days=30,
        )
        registry = ProviderRegistry((*DEFAULT_PROVIDER_DESCRIPTORS, mock))

        self.assertEqual(
            ("intervals", "garmin", "weather", "calendar", "wahoo", "wahoo-mock"),
            registry.ids(),
        )
        self.assertIn("wahoo-mock", registry.ids_with(Capability.ACTIVITIES))
        self.assertEqual(
            ("wahoo-mock", _area("activities", "Wahoo mock · Training")),
            registry.freshness_areas()[-1],
        )
        self.assertEqual(30, registry.max_sync_days("wahoo-mock"))
        self.assertIs(mock, registry.get("wahoo-mock"))

    def test_mock_provider_does_not_leak_into_default_registry(self) -> None:
        self.assertNotIn("wahoo-mock", DEFAULT_PROVIDER_REGISTRY.ids())
        self.assertNotIn(
            "wahoo-mock", DEFAULT_PROVIDER_REGISTRY.ids_with(Capability.ACTIVITIES)
        )
        self.assertNotIn("wahoo-mock", PROVIDER_REFRESH_LABELS)

    def test_duplicate_provider_id_is_rejected(self) -> None:
        descriptor = DEFAULT_PROVIDER_DESCRIPTORS[0]
        with self.assertRaisesRegex(ValueError, "duplicate provider descriptor"):
            ProviderRegistry((descriptor, descriptor))

    def test_duplicate_provider_area_is_rejected(self) -> None:
        duplicated = _descriptor(
            areas=(_area("activities", "First"), _area("activities", "Second"))
        )
        with self.assertRaisesRegex(ValueError, "duplicate freshness area"):
            ProviderRegistry((duplicated,))

    def test_unknown_provider_lookup_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            DEFAULT_PROVIDER_REGISTRY.get("unknown")

    def test_unknown_provider_uses_sync_window_default(self) -> None:
        self.assertEqual(90, DEFAULT_PROVIDER_REGISTRY.max_sync_days("unknown"))
        self.assertEqual(7, DEFAULT_PROVIDER_REGISTRY.max_sync_days("unknown", 7))

    def test_non_text_provider_identifier_uses_default_instead_of_raising(self) -> None:
        self.assertEqual(
            90,
            DEFAULT_PROVIDER_REGISTRY.max_sync_days(["intervals"]),  # type: ignore[arg-type]
        )

    def test_empty_registry_returns_empty_views(self) -> None:
        registry = ProviderRegistry(())
        self.assertEqual((), registry.all())
        self.assertEqual((), registry.ids())
        self.assertEqual((), registry.freshness_areas())
        self.assertEqual((), registry.ids_with(Capability.ACTIVITIES))


class DescriptorValidationTests(unittest.TestCase):
    def test_freshness_area_requires_text_and_positive_window(self) -> None:
        cases: list[dict[str, object]] = [
            {"area": ""},
            {"area": "   "},
            {"label": ""},
            {"stale_after_s": 0},
            {"stale_after_s": True},
            {"stale_after_s": "3600"},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                values: dict[str, object] = {
                    "area": "activities",
                    "label": "Mock",
                    "stale_after_s": TWO_DAYS,
                    "read_only": True,
                }
                values.update(overrides)
                with self.assertRaises(ValueError):
                    FreshnessArea(**values)  # type: ignore[arg-type]

    def test_freshness_area_requires_boolean_read_only(self) -> None:
        with self.assertRaisesRegex(TypeError, "read_only must be a boolean"):
            FreshnessArea(
                area="activities",
                label="Mock",
                stale_after_s=TWO_DAYS,
                read_only="yes",  # type: ignore[arg-type]
            )

    def test_freshness_area_is_frozen(self) -> None:
        area = _area()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            area.label = "Changed"  # type: ignore[misc]

    def test_descriptor_rejects_blank_identity(self) -> None:
        with self.assertRaises(ValueError):
            _descriptor(provider_id=" ")
        with self.assertRaises(ValueError):
            ProviderDescriptor(
                provider_id="wahoo-mock",
                label="",
                capabilities=frozenset(),
                freshness_areas=(),
                max_sync_days=90,
                resync_keys=(),
            )

    def test_descriptor_requires_capability_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "capabilities"):
            _descriptor(capabilities=["activities"])  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "capabilities"):
            _descriptor(capabilities=frozenset({"activities"}))  # type: ignore[arg-type]

    def test_descriptor_requires_freshness_area_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "freshness_areas"):
            _descriptor(areas=[_area()])  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "freshness_areas"):
            _descriptor(areas=("activities",))  # type: ignore[arg-type]

    def test_descriptor_requires_positive_sync_window(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_sync_days"):
            _descriptor(max_sync_days=0)
        with self.assertRaisesRegex(ValueError, "max_sync_days"):
            _descriptor(max_sync_days=True)

    def test_descriptor_requires_unique_text_resync_keys(self) -> None:
        with self.assertRaisesRegex(TypeError, "resync_keys must be a tuple"):
            _descriptor(resync_keys=["mock_full_resync_running"])  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "resync key"):
            _descriptor(resync_keys=("",))
        with self.assertRaisesRegex(ValueError, "must be unique"):
            _descriptor(resync_keys=("mock_key", "mock_key"))

    def test_valid_descriptor_is_accepted(self) -> None:
        descriptor = _descriptor(resync_keys=("mock_running", "mock_status"))
        self.assertEqual("wahoo-mock", descriptor.provider_id)
        self.assertEqual(("mock_running", "mock_status"), descriptor.resync_keys)


INTERVALS_JOB_TYPES = frozenset(
    {
        "refresh",
        "performance_refresh",
        "activity_details",
        "plan_push",
        "competition_push",
        "nutrition_sync",
        "historical_backfill",
    }
)
PREVIOUS_JOB_SUPPORT: dict[str, frozenset[str]] = {
    "intervals": INTERVALS_JOB_TYPES,
    "garmin": frozenset({"refresh", "historical_backfill"}),
    "calendar": frozenset({"refresh"}),
    "weather": frozenset({"refresh"}),
    "wahoo": frozenset({"refresh", "plan_push"}),
}
PREVIOUS_REFRESH_FIELDS: dict[str, frozenset[str]] = {
    "intervals": frozenset({"days", "reason", "end_date"}),
    "garmin": frozenset({"days", "reason", "end_date"}),
    "calendar": frozenset({"reason"}),
    "weather": frozenset({"force", "reason"}),
}
PREVIOUS_MANUAL_ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/sync", "intervals"),
    ("/api/garmin/sync", "garmin"),
    ("/api/weather/sync", "weather"),
    ("/api/external-calendar/sync", "calendar"),
    ("/api/wahoo/sync", "wahoo"),
)
PREVIOUS_FULL_RESYNC_ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/intervals/full-resync", "intervals"),
    ("/api/garmin/full-resync", "garmin"),
    ("/api/wahoo/full-resync", "wahoo"),
)
PREVIOUS_PERIOD_MESSAGES = {
    "intervals": (
        "Der Zeitraum für intervals muss -1 oder zwischen 1 und 365 Tagen liegen."
    ),
    "garmin": "Der Zeitraum für garmin muss -1 oder zwischen 1 und 90 Tagen liegen.",
}
PREVIOUS_NOT_CONFIGURED_MESSAGES = {
    "intervals": (
        "Intervals.icu ist nicht konfiguriert. Bitte INTERVALS_API_KEY in der "
        "Serverkonfiguration hinterlegen."
    ),
    "garmin": (
        "Garmin ist nicht konfiguriert. Bitte GARMIN_EMAIL oder einen vorhandenen "
        "Garmin-Tokenstore einrichten."
    ),
}


class OrchestrationParityTests(unittest.TestCase):
    def test_registry_provider_set_matches_job_provider_set(self) -> None:
        self.assertEqual(PROVIDERS, frozenset(DEFAULT_PROVIDER_REGISTRY.ids()))

    def test_job_types_match_previous_job_validation_per_provider(self) -> None:
        self.assertEqual(JOB_TYPES, frozenset().union(*PREVIOUS_JOB_SUPPORT.values()))
        for provider_id, expected in PREVIOUS_JOB_SUPPORT.items():
            for job_type in sorted(JOB_TYPES):
                with self.subTest(provider_id=provider_id, job_type=job_type):
                    self.assertIs(
                        job_type in expected,
                        DEFAULT_PROVIDER_REGISTRY.supports_job(provider_id, job_type),
                    )

    def test_unknown_provider_or_job_type_is_not_supported(self) -> None:
        self.assertFalse(DEFAULT_PROVIDER_REGISTRY.supports_job("unknown", "refresh"))
        self.assertFalse(DEFAULT_PROVIDER_REGISTRY.supports_job("intervals", "nope"))
        non_text_id: Any = ["intervals"]
        self.assertFalse(DEFAULT_PROVIDER_REGISTRY.supports_job(non_text_id, "refresh"))
        non_text_job: Any = ["refresh"]
        self.assertFalse(
            DEFAULT_PROVIDER_REGISTRY.supports_job("intervals", non_text_job)
        )

    def test_duplicate_manual_route_paths_are_rejected(self) -> None:
        route = ManualSyncRoute(path="/api/dup", uses_sync_period=False)
        first = dataclasses.replace(_descriptor("first-mock"), manual_sync=route)
        second = dataclasses.replace(_descriptor("second-mock"), manual_sync=route)
        with self.assertRaisesRegex(ValueError, "duplicate manual sync route"):
            ProviderRegistry((first, second))

    def test_duplicate_full_resync_paths_are_rejected(self) -> None:
        first = dataclasses.replace(
            _descriptor("first-mock"), full_resync_path="/api/dup/full"
        )
        second = dataclasses.replace(
            _descriptor("second-mock"), full_resync_path="/api/dup/full"
        )
        with self.assertRaisesRegex(ValueError, "duplicate full resync route"):
            ProviderRegistry((first, second))

    def test_refresh_fields_match_previous_refresh_job_fields(self) -> None:
        for provider_id, expected in PREVIOUS_REFRESH_FIELDS.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    expected, DEFAULT_PROVIDER_REGISTRY.refresh_fields(provider_id)
                )
        with self.assertRaises(KeyError):
            DEFAULT_PROVIDER_REGISTRY.refresh_fields("unknown")

    def test_sync_period_defaults_match_server_table(self) -> None:
        self.assertEqual(
            {"intervals": 84, "garmin": 84, "wahoo": 84},
            DEFAULT_PROVIDER_REGISTRY.sync_period_defaults(),
        )

    def test_daily_order_matches_scheduler_ranks(self) -> None:
        self.assertEqual(
            ("weather", "calendar", "garmin", "intervals", "wahoo"),
            DEFAULT_PROVIDER_REGISTRY.daily_order(),
        )

    def test_startup_order_matches_scheduler_ranks(self) -> None:
        self.assertEqual(
            ("calendar", "intervals", "garmin", "weather", "wahoo"),
            DEFAULT_PROVIDER_REGISTRY.startup_order(),
        )

    def test_daily_marker_ids_match_daily_marker_providers(self) -> None:
        self.assertEqual(
            frozenset({"intervals", "garmin", "calendar", "wahoo"}),
            DEFAULT_PROVIDER_REGISTRY.daily_marker_ids(),
        )

    def test_coach_refresh_targets_match_authorization_order(self) -> None:
        self.assertEqual(
            ("intervals", "garmin", "calendar", "weather", "wahoo"),
            DEFAULT_PROVIDER_REGISTRY.coach_refresh_targets(),
        )

    def test_only_athlete_data_providers_wait_for_coach_completion(self) -> None:
        waiting = [
            descriptor.provider_id
            for descriptor in DEFAULT_PROVIDER_REGISTRY.all()
            if descriptor.coach_waits_for_completion
        ]
        self.assertEqual(["intervals", "garmin"], waiting)

    def test_resync_key_map_matches_full_resync_table_in_order(self) -> None:
        mapping = DEFAULT_PROVIDER_REGISTRY.resync_key_map()
        self.assertEqual(list(PROVIDER_RESYNC_KEYS), list(mapping))
        for provider_id, keys in PROVIDER_RESYNC_KEYS.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    (
                        keys["running"],
                        keys["status"],
                        keys["last_at"],
                        keys["error"],
                    ),
                    mapping[provider_id],
                )

    def test_manual_routes_match_sync_command_table(self) -> None:
        self.assertEqual(
            PREVIOUS_MANUAL_ROUTES, DEFAULT_PROVIDER_REGISTRY.manual_routes()
        )

    def test_manual_route_payloads_match_sync_command_builders(self) -> None:
        expected = {
            "intervals": (True, (("reason", "manual"),)),
            "garmin": (True, (("reason", "manual"),)),
            "calendar": (False, (("reason", "manuell"),)),
            "weather": (False, (("reason", "manuell"), ("force", True))),
            "wahoo": (False, (("reason", "manual"),)),
        }
        for provider_id, (uses_period, payload) in expected.items():
            with self.subTest(provider_id=provider_id):
                route = DEFAULT_PROVIDER_REGISTRY.get(provider_id).manual_sync
                self.assertIsNotNone(route)
                assert route is not None
                self.assertEqual(uses_period, route.uses_sync_period)
                self.assertEqual(payload, route.payload)

    def test_full_resync_routes_match_sync_command_table(self) -> None:
        self.assertEqual(
            PREVIOUS_FULL_RESYNC_ROUTES, DEFAULT_PROVIDER_REGISTRY.full_resync_routes()
        )

    def test_not_configured_messages_match_previous_text(self) -> None:
        for provider_id, expected in PREVIOUS_NOT_CONFIGURED_MESSAGES.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    expected,
                    DEFAULT_PROVIDER_REGISTRY.get(provider_id).not_configured_message,
                )
                self.assertEqual(
                    expected, PROVIDER_NOT_CONFIGURED_MESSAGES[provider_id]
                )
        for provider_id in ("calendar", "weather"):
            self.assertIsNone(
                DEFAULT_PROVIDER_REGISTRY.get(provider_id).not_configured_message
            )

    def test_each_provider_rejects_with_its_own_not_configured_message(self) -> None:
        messages = {
            descriptor.provider_id: descriptor.not_configured_message
            for descriptor in DEFAULT_PROVIDER_REGISTRY.all()
            if descriptor.not_configured_message is not None
        }
        self.assertEqual(len(set(messages.values())), len(messages))
        for provider_id, message in messages.items():
            with self.subTest(provider_id=provider_id):
                self.assertIn(DEFAULT_PROVIDER_REGISTRY.get(provider_id).label, message)
                for other_id in messages:
                    if other_id != provider_id:
                        other_label = DEFAULT_PROVIDER_REGISTRY.get(other_id).label
                        self.assertNotIn(other_label, message)

    def test_period_error_messages_match_previous_text(self) -> None:
        for provider_id, expected in PREVIOUS_PERIOD_MESSAGES.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(
                    expected,
                    DEFAULT_PROVIDER_REGISTRY.period_error_message(provider_id),
                )


class CustomOrchestrationDescriptorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mock = _descriptor(
            "wahoo-mock",
            areas=(_area("activities", "Wahoo mock · Training"),),
            max_sync_days=30,
            resync_keys=(
                "wahoo_mock_full_resync_running",
                "wahoo_mock_full_resync_status",
                "wahoo_mock_full_resync_at",
                "wahoo_mock_full_resync_error",
            ),
        )
        self.mock = dataclasses.replace(
            self.mock,
            job_types=frozenset({"refresh"}),
            refresh_fields=frozenset({"days", "reason"}),
            default_sync_days=30,
            schedule=SchedulePolicy(daily_rank=5, startup_rank=0, daily_marker=True),
            coach_rank=10,
            manual_sync=ManualSyncRoute(
                path="/api/wahoo-mock/sync",
                uses_sync_period=True,
                payload=(("reason", "manual"),),
            ),
            full_resync_path="/api/wahoo-mock/full-resync",
        )
        self.plain = _descriptor("plain-mock")
        self.registry = ProviderRegistry(
            (*DEFAULT_PROVIDER_DESCRIPTORS, self.mock, self.plain)
        )

    def test_custom_descriptor_flows_through_every_orchestration_helper(self) -> None:
        registry = self.registry
        self.assertTrue(registry.supports_job("wahoo-mock", "refresh"))
        self.assertFalse(registry.supports_job("wahoo-mock", "historical_backfill"))
        self.assertEqual(
            frozenset({"days", "reason"}), registry.refresh_fields("wahoo-mock")
        )
        self.assertEqual(
            {"intervals": 84, "garmin": 84, "wahoo": 84, "wahoo-mock": 30},
            registry.sync_period_defaults(),
        )
        self.assertEqual(
            ("weather", "calendar", "garmin", "intervals", "wahoo", "wahoo-mock"),
            registry.daily_order(),
        )
        self.assertEqual(
            ("calendar", "wahoo-mock", "intervals", "garmin", "weather", "wahoo"),
            registry.startup_order(),
        )
        self.assertIn("wahoo-mock", registry.daily_marker_ids())
        self.assertEqual(
            ("intervals", "garmin", "calendar", "weather", "wahoo", "wahoo-mock"),
            registry.coach_refresh_targets(),
        )
        self.assertEqual(
            (
                "wahoo_mock_full_resync_running",
                "wahoo_mock_full_resync_status",
                "wahoo_mock_full_resync_at",
                "wahoo_mock_full_resync_error",
            ),
            registry.resync_key_map()["wahoo-mock"],
        )
        self.assertEqual(
            ("/api/wahoo-mock/sync", "wahoo-mock"),
            registry.manual_routes()[-1],
        )
        self.assertEqual(
            ("/api/wahoo-mock/full-resync", "wahoo-mock"),
            registry.full_resync_routes()[-1],
        )
        self.assertEqual(
            "Der Zeitraum für wahoo-mock muss -1 oder zwischen 1 und 30 Tagen liegen.",
            registry.period_error_message("wahoo-mock"),
        )

    def test_unranked_descriptor_is_skipped_by_ordering_helpers(self) -> None:
        self.assertNotIn("plain-mock", self.registry.daily_order())
        self.assertNotIn("plain-mock", self.registry.startup_order())
        self.assertNotIn("plain-mock", self.registry.coach_refresh_targets())
        self.assertNotIn("plain-mock", self.registry.daily_marker_ids())
        self.assertNotIn("plain-mock", self.registry.sync_period_defaults())
        self.assertNotIn("plain-mock", self.registry.resync_key_map())
        self.assertFalse(
            self.registry.supports_job("plain-mock", "historical_backfill")
        )
        self.assertEqual(
            frozenset({"reason"}), self.registry.refresh_fields("plain-mock")
        )

    def test_custom_descriptor_does_not_leak_into_default_registry(self) -> None:
        self.assertFalse(
            DEFAULT_PROVIDER_REGISTRY.supports_job("wahoo-mock", "refresh")
        )
        self.assertNotIn(
            "wahoo-mock", DEFAULT_PROVIDER_REGISTRY.coach_refresh_targets()
        )
        self.assertNotIn(
            "/api/wahoo-mock/sync",
            [path for path, _ in DEFAULT_PROVIDER_REGISTRY.manual_routes()],
        )

    def test_period_message_for_unknown_provider_uses_default_window(self) -> None:
        self.assertEqual(
            "Der Zeitraum für unknown muss -1 oder zwischen 1 und 90 Tagen liegen.",
            DEFAULT_PROVIDER_REGISTRY.period_error_message("unknown"),
        )


class OrchestrationDescriptorValidationTests(unittest.TestCase):
    def test_default_sync_window_must_not_exceed_max(self) -> None:
        base = _descriptor("window-mock", max_sync_days=30)
        self.assertEqual(
            30, dataclasses.replace(base, default_sync_days=30).default_sync_days
        )
        with self.assertRaisesRegex(ValueError, "must not exceed max_sync_days"):
            dataclasses.replace(base, default_sync_days=31)

    def test_default_orchestration_fields_are_generic(self) -> None:
        descriptor = _descriptor()
        self.assertEqual(frozenset({"refresh"}), descriptor.job_types)
        self.assertEqual(frozenset({"reason"}), descriptor.refresh_fields)
        self.assertIsNone(descriptor.default_sync_days)
        self.assertEqual(SchedulePolicy(), descriptor.schedule)
        self.assertIsNone(descriptor.coach_rank)
        self.assertFalse(descriptor.coach_waits_for_completion)
        self.assertIsNone(descriptor.not_configured_message)
        self.assertIsNone(descriptor.manual_sync)
        self.assertIsNone(descriptor.full_resync_path)

    def test_schedule_policy_validates_ranks_and_marker(self) -> None:
        self.assertIsNone(SchedulePolicy().daily_rank)
        with self.assertRaisesRegex(ValueError, "daily_rank"):
            SchedulePolicy(daily_rank=-1)
        with self.assertRaisesRegex(ValueError, "startup_rank"):
            SchedulePolicy(startup_rank=True)
        with self.assertRaisesRegex(TypeError, "daily_marker"):
            SchedulePolicy(daily_marker="yes")  # type: ignore[arg-type]

    def test_manual_sync_route_validates_path_flags_and_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "path"):
            ManualSyncRoute(path="", uses_sync_period=False)
        with self.assertRaisesRegex(ValueError, "absolute path"):
            ManualSyncRoute(path="api/sync", uses_sync_period=False)
        with self.assertRaisesRegex(TypeError, "uses_sync_period"):
            ManualSyncRoute(path="/api/x", uses_sync_period="yes")  # type: ignore[arg-type]
        for payload in (
            [("reason", "manual")],
            (("reason",),),
            ((1, "manual"),),
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaisesRegex(ValueError, "payload"),
            ):
                ManualSyncRoute(
                    path="/api/x",
                    uses_sync_period=False,
                    payload=payload,  # type: ignore[arg-type]
                )

    def test_descriptor_rejects_invalid_orchestration_fields(self) -> None:
        base = _descriptor()
        cases: list[tuple[dict[str, object], type[Exception], str]] = [
            ({"job_types": ["refresh"]}, TypeError, "job_types"),
            ({"job_types": frozenset({""})}, ValueError, "job_types"),
            ({"refresh_fields": {"reason"}}, TypeError, "refresh_fields"),
            ({"default_sync_days": 0}, ValueError, "default_sync_days"),
            ({"schedule": "daily"}, TypeError, "schedule"),
            ({"coach_rank": -1}, ValueError, "coach_rank"),
            ({"coach_waits_for_completion": "yes"}, TypeError, "coach_waits"),
            ({"not_configured_message": ""}, ValueError, "not_configured_message"),
            ({"manual_sync": ("/api/x", False)}, ValueError, "manual_sync"),
            ({"full_resync_path": "api/x"}, ValueError, "absolute path"),
            ({"full_resync_path": ""}, ValueError, "full_resync_path"),
        ]
        for overrides, error, pattern in cases:
            with (
                self.subTest(overrides=overrides),
                self.assertRaisesRegex(error, pattern),
            ):
                dataclasses.replace(base, **overrides)  # type: ignore[arg-type]

    def test_descriptor_accepts_valid_orchestration_fields(self) -> None:
        descriptor = dataclasses.replace(
            _descriptor(),
            job_types=frozenset({"refresh"}),
            default_sync_days=7,
            schedule=SchedulePolicy(daily_rank=0, startup_rank=0, daily_marker=True),
            coach_rank=0,
            coach_waits_for_completion=True,
            not_configured_message="Nicht konfiguriert.",
            manual_sync=ManualSyncRoute(path="/api/x", uses_sync_period=False),
            full_resync_path="/api/x/full-resync",
        )
        self.assertEqual(7, descriptor.default_sync_days)
        self.assertEqual("/api/x/full-resync", descriptor.full_resync_path)


if __name__ == "__main__":
    unittest.main()
