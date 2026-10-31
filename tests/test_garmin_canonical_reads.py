"""Garmin readers on the canonical selector: the tables against the payload readers.

The Garmin sections that have canonical observations are read through the injected
selector. These tests run the real backfill over the wire fixtures, then compare the
migrated readers with the payload readers, also after the canonical sections were
removed from the stored Garmin snapshot. Before the first completed backfill the
selector serves nothing. All storage is temporary.
"""

from __future__ import annotations

import copy
import logging
import unittest
from datetime import UTC, date, datetime
from typing import Any

from canonical_read_support import (
    CanonicalReadFixture,
    make_selector,
    populate,
    store_garmin,
)
from performance_day_support import snapshot_metrics
from support import make_config

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.coach.morning import GarminSleepObservations, ManualMorningCheckinService
from backend.db.garmin_store import prune_section
from backend.errors import AppError
from backend.observability import Redactor
from backend.performance import garmin_metrics, garmin_observations
from backend.performance.garmin_canonical import (
    GarminCanonicalMetrics,
    read_garmin_sleep_day,
    read_garmin_state,
)
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.sync.garmin import GarminPayloadService
from backend.sync.garmin_projection_service import (
    GarminCanonicalSources,
    GarminProjectionService,
)

TODAY = date(2026, 10, 11)
LOCAL_NOW = datetime(2026, 10, 11, 8, tzinfo=UTC)
CANONICAL_SECTIONS = (
    "sleep",
    "hrv",
    "resting_hr",
    "readiness",
    "weight",
    "max_metrics",
    "cycling_ftp",
    "cycling_ftp_history",
)
# The running threshold section stays: its power has no canonical form and is still
# read from the snapshot (its pace and heart rate come from the observations).
BODY_BATTERY = {"status": "ready", "morning": {"value": 78}}


class _Flag:
    def __init__(self, value: bool) -> None:
        self.value = value

    def available(self) -> bool:
        return self.value


class _CoreErrors:
    def core_error_entries(self) -> list[Any]:
        return []


class _LegacyActivities:
    def __init__(self, fixture: CanonicalReadFixture) -> None:
        self._fixture = fixture

    def latest_snapshot(self) -> dict[str, Any]:
        return self._fixture.intervals


class _Battery:
    def current(self, snapshot: Any = None) -> dict[str, Any]:
        return BODY_BATTERY


class _Observations:
    """A fixed list of observations behind the reader port."""

    def __init__(self, items: list[Observation]) -> None:
        self.items = items

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        return tuple(item for item in self.items if item.kind == kind)


class GarminReadFixture(CanonicalReadFixture):
    """Garmin services over the temporary database and the fixture selector."""

    def _payload_service(self, *, canonical: bool) -> GarminPayloadService:
        selector = make_selector(self)
        return GarminPayloadService(
            self.manager,
            self.key_values,
            _LegacyActivities(self),  # type: ignore[arg-type]
            lambda: TODAY,
            activity_rows=(lambda: selector) if canonical else None,
        )

    def _projection_service(self) -> GarminProjectionService:
        selector = make_selector(self)
        config = make_config(
            openai_base_url="",
            openai_model="",
            intervals_athlete_id="",
            garmin_password="synthetic-garmin-password",
            garmin_tokenstore="synthetic-tokenstore",
            garmin_fixture_path="synthetic-fixture.json",
            app_password="synthetic-app-password",
            data_retention_days=30,
        )
        return GarminProjectionService(
            config=config,
            garmin_payload_service=self._payload_service(canonical=True),
            garmin_sync_service=_Flag(True),  # type: ignore[arg-type]
            garmin_sync_state_service=_CoreErrors(),  # type: ignore[arg-type]
            morning_body_battery_service=_Battery(),  # type: ignore[arg-type]
            garmin_client_factory=_Flag(False),  # type: ignore[arg-type]
            database_manager=self.manager,
            key_value_repository=self.key_values,
            redactor=Redactor(lambda: config),
            local_now=lambda: LOCAL_NOW,
            canonical=GarminCanonicalSources(
                activity_rows=lambda: selector, observations=lambda: selector
            ),
        )

    def _store_snapshot(self) -> None:
        """Store the Garmin payload without a backfill, so the selector serves nothing."""
        self.write(lambda db: store_garmin(self, db, self.garmin))

    def _strip_canonical_sections(self) -> None:
        """Remove the canonical Garmin sections from the stored and in-memory snapshot."""
        stripped = {
            key: value
            for key, value in self.garmin.items()
            if key not in CANONICAL_SECTIONS
        }
        self.garmin = stripped
        for section in CANONICAL_SECTIONS:
            self.write(lambda db, name=section: prune_section(db, name, set()))


class GarminStateEqualityTests(GarminReadFixture):
    def test_table_observations_give_the_payload_state(self) -> None:
        populate(self)
        table = self.read(lambda db: read_garmin_state(self.table, db))
        payload = garmin_metrics.garmin_payload_performance_metrics(self.garmin, TODAY)

        self.assertTrue(table.has_sleep)
        self.assertIsNotNone(table.metrics.weight_kg)
        self.assertEqual(table.metrics.weight_kg, payload["weight_kg"]["value"])

    def test_state_has_the_flags_and_values_of_the_snapshot_sections(self) -> None:
        populate(self)
        state = self.read(lambda db: read_garmin_state(self.table, db))
        legacy = garmin_metrics.garmin_payload_performance_metrics(self.garmin, TODAY)
        overlay = garmin_metrics.garmin_performance_metrics(
            self.garmin, TODAY, state.metrics
        )

        for section, flag in (
            ("sleep", state.has_sleep),
            ("hrv", state.has_hrv),
            ("resting_hr", state.has_resting_hr),
            ("readiness", state.has_readiness),
        ):
            self.assertEqual(bool(self.garmin.get(section)), flag, section)
        self.assertEqual(overlay, legacy)

    def test_activity_max_hr_skips_deleted_sessions(self) -> None:
        populate(self)

        def read(db: Any) -> dict[Sport, float]:
            return {
                sport: value
                for sport, value, _day in self.table.activity_max_hr(
                    db, ProviderId.GARMIN, low=80, high=260
                )
            }

        before = self.read(read)
        self.assertIn(Sport.RIDE, before)
        self.write(
            lambda db: db.execute(
                "UPDATE activity_sessions SET state = 'deleted', merged_into = NULL "
                "WHERE activity_id IN "
                "(SELECT activity_id FROM activity_records "
                "WHERE provider = 'garmin' AND sport = 'ride')"
            )
        )

        self.assertNotIn(Sport.RIDE, self.read(read))

    def test_sleep_day_matches_the_payload_section(self) -> None:
        populate(self)
        table = self.read(lambda db: read_garmin_sleep_day(self.table, db))

        self.assertIsNotNone(table)
        self.assertEqual(
            garmin_observations.garmin_source_observed_at(self.garmin["sleep"]),
            None if table is None else table.isoformat(),
        )

    def test_selector_is_resolved_once_per_state_read(self) -> None:
        populate(self)
        selector = make_selector(self)
        calls: list[Any] = []
        original = selector.reader_for

        def counting(db: Any) -> Any:
            calls.append(db)
            return original(db)

        selector.reader_for = counting  # type: ignore[method-assign]
        self.read(lambda db: read_garmin_state(selector, db))

        self.assertEqual(len(calls), 1)


class GarminServiceEqualityTests(GarminReadFixture):
    def test_services_read_no_table_values_until_the_backfill_completes(
        self,
    ) -> None:
        self._store_snapshot()
        pending = self._projection_service().public_state()
        # No Intervals.icu activity is served yet, so no Garmin copy is a duplicate.
        self.assertEqual(pending["duplicate_activities_skipped"], 0)

        populate(self)
        state = self._projection_service().public_state()

        self.assertEqual(state["duplicate_activities_skipped"], 1)
        for key in ("has_sleep", "has_hrv", "has_resting_hr", "has_readiness"):
            self.assertTrue(state[key], key)

    def test_services_are_unchanged_once_tables_serve_without_the_sections(
        self,
    ) -> None:
        populate(self)
        with_sections = self._projection_service()
        expected_state = with_sections.public_state()
        expected_context = with_sections.coach_context(include_performance=True)

        self._strip_canonical_sections()
        migrated = self._projection_service()
        state = migrated.public_state()
        context = migrated.coach_context(include_performance=True)

        self.assertEqual(state, expected_state)
        self.assertEqual(context["performance"], expected_context["performance"])
        for key in ("has_sleep", "has_hrv", "has_resting_hr", "has_readiness"):
            self.assertTrue(state[key], key)
        self.assertTrue(state["has_weight"])

    def test_sections_without_observations_are_reported_missing(self) -> None:
        self.garmin = {
            key: value
            for key, value in self.garmin.items()
            if key not in CANONICAL_SECTIONS
        }
        populate(self)
        state = self._projection_service().public_state()

        for key in (
            "has_sleep",
            "has_hrv",
            "has_resting_hr",
            "has_readiness",
            "has_weight",
            "has_vo2max",
        ):
            self.assertFalse(state[key], key)
        # The running threshold power stays on the snapshot, so thresholds remain.
        self.assertTrue(state["has_thresholds"])

    def test_weekly_only_hrv_section_still_counts_as_present(self) -> None:
        self.garmin = {
            key: value
            for key, value in self.garmin.items()
            if key not in CANONICAL_SECTIONS
        }
        self.garmin["hrv"] = {"weeklyAvg": 48}
        populate(self)

        state = self._projection_service().public_state()

        self.assertTrue(state["has_hrv"])

    def test_activity_matches_are_equal_between_sources(self) -> None:
        populate(self)
        garmin_activities = copy.deepcopy(self.garmin["activities"])
        legacy = self._payload_service(canonical=False)
        migrated = self._payload_service(canonical=True)

        stamp = {"synced_at": "2026-10-11T07:00:00Z"}
        legacy_matches = legacy.prepare_fixture(
            {"activities": garmin_activities, **stamp}
        )["activity_matches"]
        migrated_matches = migrated.prepare_fixture(
            {"activities": copy.deepcopy(garmin_activities), **stamp}
        )["activity_matches"]

        self.assertEqual(migrated_matches, legacy_matches)
        self.assertTrue(migrated_matches)
        self.assertEqual(
            {row["id"] for row in migrated.intervals_activities()},
            {row["id"] for row in legacy.intervals_activities()},
        )


class GarminSleepReadinessTests(GarminReadFixture):
    def test_observed_day_decides_without_the_raw_sleep_section(self) -> None:
        populate(self)
        day = self.read(lambda db: read_garmin_sleep_day(self.table, db))
        assert day is not None
        with_sections = {"sleep": self.garmin["sleep"]}
        without_sections: dict[str, Any] = {}

        # The raw sleep section alone never makes the check-in ready (#1411).
        self.assertFalse(
            garmin_observations.garmin_sleep_ready_for_checkin(day, with_sections, None)
        )
        self.assertTrue(
            garmin_observations.garmin_sleep_ready_for_checkin(
                day, without_sections, day.isoformat()
            )
        )
        self.assertFalse(
            garmin_observations.garmin_sleep_ready_for_checkin(
                day, without_sections, None
            )
        )

    def test_stored_freshness_stays_authoritative_over_the_observed_day(self) -> None:
        day = date(2026, 10, 10)
        stale = {"source_freshness": {"sleep": {"observed_at": "2026-10-09"}}}

        self.assertEqual(
            garmin_observations.garmin_sleep_observation_date(stale, day.isoformat()),
            "2026-10-09",
        )
        self.assertFalse(
            garmin_observations.garmin_sleep_ready_for_checkin(
                day, stale, day.isoformat()
            )
        )


class _MorningSync:
    def configured(self) -> bool:
        return True

    def sync(self, **_kwargs: Any) -> None:
        return None


class _MorningBattery:
    def __init__(self) -> None:
        self.refreshed: list[date] = []

    def refresh(self, day: date) -> None:
        self.refreshed.append(day)


class GarminMorningCheckinTests(GarminReadFixture):
    def _service(self, today: date) -> tuple[ManualMorningCheckinService, Any]:
        selector = make_selector(self)
        battery = _MorningBattery()
        service = ManualMorningCheckinService(
            _MorningSync(),  # type: ignore[arg-type]
            self._payload_service(canonical=False),
            battery,  # type: ignore[arg-type]
            lambda: today,
            logging.getLogger("test-garmin-morning"),
            observations=GarminSleepObservations(self.manager, lambda: selector),
        )
        return service, battery

    def test_check_in_is_ready_from_sleep_observations_without_the_section(
        self,
    ) -> None:
        populate(self)
        day = self.read(lambda db: read_garmin_sleep_day(self.table, db))
        assert day is not None
        self._strip_canonical_sections()

        service, battery = self._service(day)
        service.prepare()

        self.assertEqual(battery.refreshed, [day])

    def test_check_in_waits_when_the_sleep_day_is_not_today(self) -> None:
        populate(self)
        day = self.read(lambda db: read_garmin_sleep_day(self.table, db))
        assert day is not None
        self._strip_canonical_sections()

        service, battery = self._service(date(2026, 10, 12))
        with self.assertRaises(AppError) as raised:
            service.prepare()

        self.assertEqual(raised.exception.reason, "garmin_sleep_not_ready")
        self.assertEqual(battery.refreshed, [])


class GarminCanonicalReaderUnitTests(unittest.TestCase):
    def _observation(
        self,
        kind: MetricKind,
        value: float,
        *,
        sport: Sport | None = None,
        provider: ProviderId = ProviderId.GARMIN,
        day: date = date(2026, 10, 10),
    ) -> Observation:
        return Observation(
            kind=kind,
            value=MetricValue(value, kind.unit),
            observed_on=day,
            observed_at=None,
            sport=sport,
            provenance=Provenance(
                provider=provider,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=f"{kind.value}:0",
                recorded_by=RecordingOrigin.UNKNOWN,
                retrieved_at=datetime(2026, 10, 11, tzinfo=UTC),
                label=None,
            ),
        )

    def _metrics(self, items: list[Observation]) -> GarminCanonicalMetrics:
        return read_garmin_state(_Observations(items), object()).metrics

    def _with_activity_max_hr(
        self, items: list[Observation], *entries: tuple[Sport, float, date]
    ) -> Any:
        class Reader(_Observations):
            calls = 0

            def activity_max_hr(
                self, db: Any, provider: ProviderId, *, low: float, high: float
            ) -> tuple[tuple[Sport, float, date], ...]:
                Reader.calls += 1
                return entries

        return Reader(items)

    def test_activity_max_hr_is_read_from_the_same_source(self) -> None:
        reader = self._with_activity_max_hr(
            [],
            (Sport.RIDE, 181.0, date(2026, 10, 1)),
            (Sport.RIDE, 186.0, date(2026, 9, 12)),
            (Sport.RUN, 192.0, date(2026, 10, 2)),
        )
        state = read_garmin_state(reader, object())
        metrics = garmin_metrics.garmin_performance_metrics({}, TODAY, state.metrics)

        cycling = metrics["cycling_max_hr_bpm"]
        self.assertEqual(cycling["value"], 186)
        self.assertEqual(cycling["observed_at"], "2026-09-12")
        self.assertTrue(cycling["note"].startswith("Garmin Connect Radaktivitäten"))
        self.assertEqual(metrics["running_max_hr_bpm"]["value"], 192)

    def test_profile_max_hr_skips_the_activity_read(self) -> None:
        reader = self._with_activity_max_hr(
            [self._observation(MetricKind.MAX_HR, 188.0)],
            (Sport.RIDE, 199.0, date(2026, 10, 1)),
        )
        state = read_garmin_state(reader, object())
        metrics = garmin_metrics.garmin_performance_metrics({}, TODAY, state.metrics)

        self.assertEqual(type(reader).calls, 0)
        self.assertEqual(metrics["cycling_max_hr_bpm"]["value"], 188)
        self.assertEqual(
            metrics["cycling_max_hr_bpm"]["note"], "Garmin Connect Herzfrequenzzonen"
        )

    def test_only_the_sport_without_a_profile_value_is_labelled_activities(
        self,
    ) -> None:
        reader = self._with_activity_max_hr(
            [self._observation(MetricKind.MAX_HR, 188.0, sport=Sport.RUN)],
            (Sport.RIDE, 186.0, date(2026, 10, 5)),
        )
        state = read_garmin_state(reader, object())
        metrics = garmin_metrics.garmin_performance_metrics({}, TODAY, state.metrics)

        self.assertEqual(metrics["running_max_hr_bpm"]["value"], 188)
        self.assertEqual(
            metrics["running_max_hr_bpm"]["note"], "Garmin Connect Herzfrequenzzonen"
        )
        self.assertEqual(metrics["cycling_max_hr_bpm"]["value"], 186)
        self.assertTrue(
            metrics["cycling_max_hr_bpm"]["note"].startswith(
                "Garmin Connect Radaktivitäten"
            )
        )

    def test_intervals_observations_are_ignored(self) -> None:
        metrics = self._metrics(
            [
                self._observation(
                    MetricKind.WEIGHT, 80.0, provider=ProviderId.INTERVALS
                ),
                self._observation(MetricKind.WEIGHT, 71.5),
            ]
        )

        self.assertEqual(metrics.weight_kg, 71.5)

    def test_running_vo2max_falls_back_to_the_generic_value(self) -> None:
        generic = self._observation(MetricKind.VO2MAX, 52.0)
        running = self._observation(MetricKind.VO2MAX, 54.0, sport=Sport.RUN)

        self.assertEqual(self._metrics([generic]).running_vo2max, 52.0)
        self.assertEqual(self._metrics([generic, running]).running_vo2max, 54.0)
        self.assertIsNone(self._metrics([generic, running]).cycling_vo2max)

    def test_threshold_speed_becomes_bounded_seconds_per_kilometre(self) -> None:
        def pace(speed: float) -> int | None:
            return self._metrics(
                [self._observation(MetricKind.THRESHOLD_PACE, speed, sport=Sport.RUN)]
            ).run_threshold_pace_seconds_per_km

        self.assertEqual(pace(4.0), 250)
        self.assertIsNone(pace(0.5))
        self.assertIsNone(pace(14.0))

    def test_collected_scaled_pace_and_undated_ftp_reach_current_metrics(self) -> None:
        payload = {
            "running_threshold": {
                "speed_and_heart_rate": {"speed": 0.35833233, "heartRate": 161}
            },
            "cycling_ftp": {
                "calendarDate": "2026-10-03T13:38:07.0",
                "functionalThresholdPower": 306,
            },
        }
        mapped = map_garmin_health(payload, zone=UTC, retrieved_at=LOCAL_NOW)
        canonical = self._metrics(list(mapped.records))
        metrics = garmin_metrics.garmin_performance_metrics(payload, TODAY, canonical)
        legacy = garmin_metrics.garmin_payload_performance_metrics(payload, TODAY)

        self.assertEqual(metrics["run_threshold_pace_seconds_per_km"]["value"], 279)
        self.assertEqual(
            metrics["run_threshold_pace_seconds_per_km"]["value"],
            legacy["run_threshold_pace_seconds_per_km"]["value"],
        )
        self.assertEqual(metrics["run_threshold_hr_bpm"]["value"], 161)
        self.assertEqual(metrics["cycling_ftp_watts"]["value"], 306)

        current = snapshot_metrics(
            {
                "athlete": {
                    "sport_settings": [
                        {"types": ["Ride"], "ftp": 400},
                        {"types": ["Run"], "threshold_pace": 1000 / 267},
                    ]
                }
            },
            {},
            metrics,
        )
        for key, expected in (
            ("cycling_ftp_watts", 306),
            ("run_threshold_pace_seconds_per_km", 279),
            ("run_threshold_hr_bpm", 161),
        ):
            with self.subTest(key=key):
                self.assertEqual(current[key]["value"], expected)
                self.assertEqual(
                    current[key]["source_provider"], ProviderId.GARMIN.value
                )

    def test_newer_generic_vo2max_replaces_an_older_running_value(self) -> None:
        older_running = self._observation(
            MetricKind.VO2MAX, 54.0, sport=Sport.RUN, day=date(2026, 10, 8)
        )
        newer_generic = self._observation(MetricKind.VO2MAX, 51.0)
        same_day_running = self._observation(MetricKind.VO2MAX, 53.0, sport=Sport.RUN)

        self.assertEqual(
            self._metrics([older_running, newer_generic]).running_vo2max, 51.0
        )
        self.assertEqual(
            self._metrics(
                [older_running, newer_generic, same_day_running]
            ).running_vo2max,
            53.0,
        )

    def test_vo2max_outside_the_legacy_bounds_is_dropped(self) -> None:
        metrics = self._metrics(
            [
                self._observation(MetricKind.VO2MAX, 120.0, sport=Sport.RIDE),
                self._observation(MetricKind.VO2MAX, 15.0),
            ]
        )

        self.assertIsNone(metrics.cycling_vo2max)
        self.assertIsNone(metrics.running_vo2max)

    def test_max_hr_comes_from_the_latest_day_of_each_category(self) -> None:
        metrics = self._metrics(
            [
                self._observation(
                    MetricKind.MAX_HR, 195.0, sport=Sport.RUN, day=date(2026, 10, 1)
                ),
                self._observation(MetricKind.MAX_HR, 188.0, sport=Sport.RUN),
            ]
        )

        self.assertEqual(dict(metrics.profile_max_hr), {"running": 188.0})

    def test_max_hr_keeps_the_highest_value_per_category(self) -> None:
        metrics = self._metrics(
            [
                self._observation(MetricKind.MAX_HR, 185.0, sport=Sport.RUN),
                self._observation(MetricKind.MAX_HR, 190.0, sport=Sport.RUN),
                self._observation(MetricKind.MAX_HR, 178.0, sport=Sport.RIDE),
                self._observation(MetricKind.MAX_HR, 192.0),
            ]
        )

        self.assertEqual(
            dict(metrics.profile_max_hr),
            {"running": 190.0, "cycling": 178.0, "generic": 192.0},
        )

    def test_values_outside_the_legacy_bounds_are_dropped(self) -> None:
        metrics = self._metrics(
            [
                self._observation(MetricKind.MAX_HR, 30.0, sport=Sport.RUN),
                self._observation(MetricKind.MAX_HR, 185.0, sport=Sport.RIDE),
                self._observation(MetricKind.WEIGHT, 25.0),
            ]
        )

        self.assertEqual(dict(metrics.profile_max_hr), {"cycling": 185.0})
        self.assertIsNone(metrics.weight_kg)

    def test_latest_observed_day_wins(self) -> None:
        metrics = self._metrics(
            [
                self._observation(MetricKind.WEIGHT, 72.0, day=date(2026, 10, 8)),
                self._observation(MetricKind.WEIGHT, 71.0, day=date(2026, 10, 10)),
            ]
        )

        self.assertEqual(metrics.weight_kg, 71.0)


if __name__ == "__main__":
    unittest.main()
