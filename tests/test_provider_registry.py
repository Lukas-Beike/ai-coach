"""Parity and contract tests for provider descriptors and the sync registry.

The literal tables below are the values synchronization used before provider
data moved into descriptors. They pin the derived output byte-for-byte.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import unittest
from datetime import UTC, datetime

from backend.config import Config
from backend.providers.descriptors import (
    DEFAULT_PROVIDER_DESCRIPTORS,
    Capability,
    FreshnessArea,
    ProviderDescriptor,
)
from backend.sync.freshness import (
    PROVIDER_REFRESH_LABELS,
    PROVIDER_REFRESH_STALE_SECONDS,
    provider_freshness_state,
)
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS
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
}
PREVIOUS_LABELS: dict[tuple[str, str], str] = {
    ("intervals", "activities"): "Intervals.icu · Training",
    ("intervals", "competitions"): "Intervals.icu · Wettkämpfe",
    ("intervals", "performance"): "Intervals.icu · Leistung",
    ("garmin", "data"): "Garmin",
    ("weather", "forecast"): "Open-Meteo",
    ("calendar", "events"): "Gemeinsamer Kalender",
}
PREVIOUS_PROJECTION: list[tuple[str, str, str, bool]] = [
    ("intervals", "activities", "Intervals.icu · Training", True),
    ("intervals", "competitions", "Intervals.icu · Wettkämpfe", False),
    ("intervals", "performance", "Intervals.icu · Leistung", True),
    ("garmin", "data", "Garmin", True),
    ("weather", "forecast", "Open-Meteo", True),
    ("calendar", "events", "Gemeinsamer Kalender", True),
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

    def test_provider_order_is_intervals_garmin_weather_calendar(self) -> None:
        self.assertEqual(
            ("intervals", "garmin", "weather", "calendar"),
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

    def test_resync_keys_match_full_resync_table(self) -> None:
        for provider_id in ("intervals", "garmin"):
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
            ("intervals", "garmin"), registry.ids_with(Capability.ACTIVITIES)
        )
        self.assertEqual(("intervals",), registry.ids_with(Capability.WORKOUT_EXPORT))
        self.assertEqual(("intervals",), registry.ids_with(Capability.COMPETITIONS))
        self.assertEqual(("weather",), registry.ids_with(Capability.WEATHER_FORECAST))
        self.assertEqual(("calendar",), registry.ids_with(Capability.PUBLIC_CALENDAR))
        self.assertEqual(("intervals",), registry.ids_with(Capability.PLANNED_EVENTS))

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
            ("intervals", "garmin", "weather", "calendar", "wahoo-mock"),
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


if __name__ == "__main__":
    unittest.main()
