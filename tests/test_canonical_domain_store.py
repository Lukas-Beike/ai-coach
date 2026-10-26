"""Canonical sleep, zone, provider status and gear records, their store and reader.

Each test uses a temporary SQLite file with the schema initialized. No provider
account, network, real data directory or encryption key is involved.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from canonical_domain_support import (
    GEAR_SOURCE,
    LATER,
    NOW,
    SETTINGS_SOURCE,
    SLEEP_START,
    WATCH_CONTEXT,
    WELLNESS_SOURCE,
    gear_item,
    gear_link,
    local_zone_configuration,
    provenance,
    sleep_period,
    status,
    zone_configuration,
)

from backend.canonical.vocabulary import (
    CategoricalDomain,
    Environment,
    ProviderId,
    SleepKind,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
    ZonePercentBasis,
)
from backend.db import canonical_domain_store, row_factory
from backend.db.canonical_domain_store import ReplaceResult
from backend.db.canonical_store import WriteOutcome
from backend.db.schema import initialize_schema
from backend.sync.canonical_table_reader import CanonicalTableReader

NAIVE_TIME = datetime(2026, 10, 20, 6, 0)  # noqa: DTZ001 - naive value under test
BERLIN = ZoneInfo("Europe/Berlin")
# 02:30 summer time, then 02:15 winter time, is 45 minutes later.
AUTUMN_START = datetime(2026, 10, 25, 2, 30, tzinfo=BERLIN)
AUTUMN_END = datetime(2026, 10, 25, 2, 15, fold=1, tzinfo=BERLIN)


class ProviderSourceValidationTests(unittest.TestCase):
    def test_provider_records_need_a_provider_and_source_record_and_are_not_derived(
        self,
    ) -> None:
        builders: dict[str, Callable[..., object]] = {
            "status": status,
            "sleep": sleep_period,
            "gear": gear_item,
            "link": gear_link,
        }
        invalid = {
            "no provider": provenance(None, provider=None),
            "no source record": provenance(None),
            "derived": provenance(source_kind=SourceKind.DERIVED),
        }
        for name, build in builders.items():
            for reason, value in invalid.items():
                with (
                    self.subTest(record=name, reason=reason),
                    self.assertRaises(ValueError),
                ):
                    build(provenance=value)

    def test_a_gear_link_has_no_measurement_context(self) -> None:
        with self.assertRaisesRegex(ValueError, "no measurement context"):
            gear_link(provenance=provenance(GEAR_SOURCE, context=WATCH_CONTEXT))


class CategoricalObservationTests(unittest.TestCase):
    def test_a_status_keeps_the_provider_code(self) -> None:
        observation = status(code="MAINTAINING_2", sport=Sport.RUN)
        self.assertEqual("MAINTAINING_2", observation.code)
        self.assertIs(Sport.RUN, observation.sport)

    def test_invalid_statuses_are_rejected(self) -> None:
        cases: dict[str, tuple[type[Exception], dict[str, Any]]] = {
            "code with a space": (ValueError, {"code": "NOT VALID"}),
            "empty code": (ValueError, {"code": ""}),
            "numeric code": (TypeError, {"code": 3}),
            "domain text": (TypeError, {"domain": "training_status"}),
            "naive time": (ValueError, {"observed_at": NAIVE_TIME}),
            "datetime day": (TypeError, {"observed_on": SLEEP_START}),
            "sport text": (TypeError, {"sport": "run"}),
        }
        for name, (error, overrides) in cases.items():
            with self.subTest(name), self.assertRaises(error):
                status(**overrides)


class SleepPeriodTests(unittest.TestCase):
    def test_invalid_sleep_periods_are_rejected(self) -> None:
        cases: dict[str, tuple[type[Exception], dict[str, Any]]] = {
            "end before start": (ValueError, {"end": SLEEP_START}),
            "longer than a day": (
                ValueError,
                {
                    "end": SLEEP_START + timedelta(hours=24, seconds=1),
                    "wake_date": date(2026, 10, 21),
                },
            ),
            "naive start": (ValueError, {"start": NAIVE_TIME}),
            "start before the UTC range": (
                ValueError,
                {"start": datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1)))},
            ),
            "end after the local range": (
                ValueError,
                {
                    "start": datetime(9999, 12, 31, 20, 0, tzinfo=UTC),
                    "end": datetime(9999, 12, 31, 23, 30, tzinfo=UTC),
                    "wake_date": date(9999, 12, 31),
                },
            ),
            "wake date far from end": (ValueError, {"wake_date": date(2026, 10, 25)}),
            "wake date a day early": (ValueError, {"wake_date": date(2026, 10, 19)}),
            "wake date a day late": (ValueError, {"wake_date": date(2026, 10, 21)}),
            "zone with a space": (ValueError, {"timezone": "Europe Berlin"}),
            "unknown zone": (ValueError, {"timezone": "Not/AZone"}),
            "zone region only": (ValueError, {"timezone": "Europe"}),
            "zone with an empty part": (ValueError, {"timezone": "Europe//Berlin"}),
            "zone not text": (TypeError, {"timezone": 1}),
            "duration above a day": (ValueError, {"reported_duration_s": 86_401.0}),
            "negative duration": (ValueError, {"reported_duration_s": -1.0}),
            "bounds method not a slug": (ValueError, {"bounds_method": "Start End"}),
            "kind text": (TypeError, {"kind": "night"}),
        }
        for name, (error, overrides) in cases.items():
            with self.subTest(name), self.assertRaises(error):
                sleep_period(**overrides)

    def test_the_wake_date_is_the_local_date_of_the_end(self) -> None:
        # 23:30 UTC is the next day in Europe/Berlin.
        start = datetime(2026, 10, 20, 15, 30, tzinfo=UTC)
        end = start + timedelta(hours=8)
        period = sleep_period(start=start, end=end, wake_date=date(2026, 10, 21))
        self.assertEqual(date(2026, 10, 21), period.wake_date)
        with self.assertRaises(ValueError):
            sleep_period(start=start, end=end, wake_date=date(2026, 10, 20))

    def test_without_a_zone_the_wake_date_is_within_a_day_of_the_utc_end(
        self,
    ) -> None:
        # The default end is 06:30 UTC on 20 October.
        for day in (19, 20, 21):
            with self.subTest(day=day):
                period = sleep_period(timezone=None, wake_date=date(2026, 10, day))
                self.assertIsNone(period.timezone)
        for day in (18, 22):
            with self.subTest(day=day), self.assertRaises(ValueError):
                sleep_period(timezone=None, wake_date=date(2026, 10, day))

    def test_known_zone_names_are_kept(self) -> None:
        # The default end is 20 October in each of these zones.
        for name in ("UTC", "Etc/GMT-14", "America/Argentina/Buenos_Aires"):
            with self.subTest(name):
                self.assertEqual(name, sleep_period(timezone=name).timezone)

    def test_bounds_are_utc_instants_across_the_autumn_change(self) -> None:
        period = sleep_period(
            start=AUTUMN_START, end=AUTUMN_END, wake_date=date(2026, 10, 25)
        )
        self.assertEqual(
            (
                datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
                datetime(2026, 10, 25, 1, 15, tzinfo=UTC),
            ),
            (period.start, period.end),
        )
        self.assertIs(UTC, period.end.tzinfo)
        self.assertEqual(timedelta(minutes=45), period.end - period.start)

    def test_the_day_limit_uses_the_true_length_across_dst_changes(self) -> None:
        # 20:00 to 19:30 the next day lasts 24.5 hours when winter time starts;
        # 20:00 to 20:30 the next day lasts 23.5 hours when summer time starts.
        with self.assertRaises(ValueError):
            sleep_period(
                start=datetime(2026, 10, 24, 20, 0, tzinfo=BERLIN),
                end=datetime(2026, 10, 25, 19, 30, tzinfo=BERLIN),
                wake_date=date(2026, 10, 25),
            )
        period = sleep_period(
            start=datetime(2026, 3, 28, 20, 0, tzinfo=BERLIN),
            end=datetime(2026, 3, 29, 20, 30, tzinfo=BERLIN),
            wake_date=date(2026, 3, 29),
        )
        self.assertEqual(timedelta(hours=23, minutes=30), period.end - period.start)

    def test_a_night_across_the_spring_gap_keeps_its_true_length(self) -> None:
        # 22:00 winter time to 07:00 summer time is 8 hours, not 9.
        period = sleep_period(
            start=datetime(2026, 3, 28, 22, 0, tzinfo=BERLIN),
            end=datetime(2026, 3, 29, 7, 0, tzinfo=BERLIN),
            wake_date=date(2026, 3, 29),
        )
        self.assertEqual(timedelta(hours=8), period.end - period.start)


class ZoneConfigurationTests(unittest.TestCase):
    def test_percent_limits_keep_their_basis_and_an_open_top(self) -> None:
        configuration = zone_configuration(
            metric=ZoneConfigurationMetric.POWER,
            sport=Sport.RIDE,
            threshold=280.0,
            maximum=None,
            resting=None,
            limits=None,
            percent_limits=(55.0, 75.0, 90.0, 105.0, 120.0, 150.0, 999.0),
            percent_basis=ZonePercentBasis.THRESHOLD,
            model="seven_zone",
        )
        self.assertIsNone(configuration.limits)
        self.assertEqual(
            (55.0, 75.0, 90.0, 105.0, 120.0, 150.0, 999.0),
            configuration.percent_limits,
        )

    def test_a_local_configuration_has_no_provider(self) -> None:
        configuration = local_zone_configuration()
        self.assertIsNone(configuration.provenance.provider)

    def test_invalid_zone_configurations_are_rejected(self) -> None:
        cases: dict[str, tuple[type[Exception], dict[str, Any]]] = {
            "limits not ascending": (ValueError, {"limits": (130.0, 130.0)}),
            "no limits": (ValueError, {"limits": ()}),
            "too many limits": (
                ValueError,
                {"limits": tuple(float(value) for value in range(100, 120))},
            ),
            "limits as a list": (TypeError, {"limits": [130.0, 145.0]}),
            "heart rate out of range": (ValueError, {"limits": (130.0, 300.0)}),
            "no limits at all": (ValueError, {"limits": None}),
            "percent without basis": (ValueError, {"percent_limits": (80.0, 90.0)}),
            "basis without percent": (
                ValueError,
                {"percent_basis": ZonePercentBasis.MAXIMUM},
            ),
            "reserve outside heart rate": (
                ValueError,
                {
                    "metric": ZoneConfigurationMetric.POWER,
                    "threshold": None,
                    "maximum": None,
                    "resting": None,
                    "limits": None,
                    "percent_limits": (60.0, 80.0),
                    "percent_basis": ZonePercentBasis.RESERVE,
                },
            ),
            "resting outside heart rate": (
                ValueError,
                {
                    "metric": ZoneConfigurationMetric.POWER,
                    "threshold": None,
                    "maximum": None,
                    "resting": 48.0,
                    "limits": (150.0, 200.0),
                },
            ),
            "valid until before from": (
                ValueError,
                {"valid_from": date(2026, 10, 2), "valid_until": date(2026, 10, 1)},
            ),
            "derived": (
                ValueError,
                {"provenance": provenance(source_kind=SourceKind.DERIVED)},
            ),
            "provider without source": (ValueError, {"provenance": provenance(None)}),
            "model not a slug": (ValueError, {"model": "Five Zones"}),
            "metric text": (TypeError, {"metric": "heart_rate"}),
        }
        for name, (error, overrides) in cases.items():
            with self.subTest(name), self.assertRaises(error):
                zone_configuration(**overrides)


class GearTests(unittest.TestCase):
    def test_invalid_gear_is_rejected(self) -> None:
        cases: dict[str, tuple[type[Exception], dict[str, Any]]] = {
            "empty id": (ValueError, {"gear_id": " "}),
            "long name": (ValueError, {"name": "x" * 201}),
            "negative distance": (ValueError, {"total_distance_m": -1.0}),
            "activity count as bool": (TypeError, {"total_activities": True}),
            "activity count as float": (TypeError, {"total_activities": 3.0}),
            "negative activity count": (ValueError, {"total_activities": -1}),
        }
        for name, (error, overrides) in cases.items():
            with self.subTest(name), self.assertRaises(error):
                gear_item(**overrides)


class DomainStoreFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = sqlite3.connect(Path(self.temporary.name) / "domain.db")
        self.addCleanup(self.db.close)
        self.db.row_factory = row_factory
        self.db.execute("PRAGMA foreign_keys = ON")
        initialize_schema(self.db)
        self.db.commit()
        self.reader = CanonicalTableReader()

    def replace_sleep(
        self, *periods: Any, source: str = WELLNESS_SOURCE, now: str = NOW
    ) -> ReplaceResult:
        return canonical_domain_store.replace_sleep_periods(
            self.db,
            provider=ProviderId.GARMIN,
            source_record_id=source,
            periods=periods,
            mapper_version=1,
            now=now,
        )

    def replace_statuses(
        self, *observations: Any, source: str = WELLNESS_SOURCE
    ) -> ReplaceResult:
        return canonical_domain_store.replace_categorical_observations(
            self.db,
            provider=ProviderId.GARMIN,
            source_record_id=source,
            observations=observations,
            mapper_version=1,
            now=NOW,
        )

    def rows(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.db.execute(sql, params).fetchall()]


class DomainReplaceTests(DomainStoreFixture):
    def test_replace_writes_rows_then_leaves_them_unchanged(self) -> None:
        extra = sleep_period(
            start=SLEEP_START + timedelta(hours=15),
            end=SLEEP_START + timedelta(hours=16),
            kind=SleepKind.UNKNOWN,
        )
        self.assertEqual(
            ReplaceResult(2, 0, 0, 0), self.replace_sleep(sleep_period(), extra)
        )
        self.assertEqual(
            ReplaceResult(0, 0, 2, 0), self.replace_sleep(sleep_period(), extra)
        )

    def test_replace_updates_changed_rows_and_retires_rows_no_longer_emitted(
        self,
    ) -> None:
        extra = sleep_period(
            start=SLEEP_START + timedelta(hours=15),
            end=SLEEP_START + timedelta(hours=16),
        )
        self.replace_sleep(sleep_period(), extra)
        changed = sleep_period(reported_duration_s=26_000.0)
        self.assertEqual(
            ReplaceResult(0, 1, 0, 1), self.replace_sleep(changed, now=LATER)
        )
        self.assertEqual((changed,), self.reader.sleep_periods(self.db))
        self.assertEqual(
            [
                {"state": "active", "updated_at": LATER},
                {"state": "retired", "updated_at": LATER},
            ],
            self.rows(
                "SELECT state, updated_at FROM sleep_periods ORDER BY started_at"
            ),
        )

    def test_a_retired_row_emitted_again_is_active_again(self) -> None:
        extra = sleep_period(
            start=SLEEP_START + timedelta(hours=15),
            end=SLEEP_START + timedelta(hours=16),
        )
        self.replace_sleep(sleep_period(), extra)
        self.replace_sleep(sleep_period())
        self.assertEqual(
            ReplaceResult(0, 1, 1, 0), self.replace_sleep(sleep_period(), extra)
        )
        self.assertEqual(2, len(self.reader.sleep_periods(self.db)))

    def test_an_empty_replace_retires_every_row_of_the_source_only(self) -> None:
        other = sleep_period(
            start=SLEEP_START + timedelta(days=1),
            end=SLEEP_START + timedelta(days=1, hours=8),
            wake_date=date(2026, 10, 21),
            provenance=provenance("wellness-2026-10-21"),
        )
        self.replace_sleep(sleep_period())
        self.replace_sleep(other, source="wellness-2026-10-21")
        self.assertEqual(ReplaceResult(0, 0, 0, 1), self.replace_sleep())
        self.assertEqual((other,), self.reader.sleep_periods(self.db))

    def test_a_row_another_source_record_emits_moves_to_that_record(self) -> None:
        self.replace_statuses(status())
        moved = status(provenance=provenance("wellness-late"))
        self.assertEqual(
            ReplaceResult(0, 1, 0, 0),
            self.replace_statuses(moved, source="wellness-late"),
        )
        # The first source no longer owns the row, so its replace keeps it.
        self.assertEqual(ReplaceResult(0, 0, 0, 0), self.replace_statuses())
        self.assertEqual(
            (moved,),
            self.reader.categorical_observations(
                self.db, CategoricalDomain.TRAINING_STATUS
            ),
        )

    def test_rows_of_another_source_or_with_a_repeated_key_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "come from the replaced source"):
            self.replace_statuses(status(provenance=provenance("other-record")))
        with self.assertRaisesRegex(ValueError, "come from the replaced source"):
            canonical_domain_store.replace_categorical_observations(
                self.db,
                provider=ProviderId.INTERVALS,
                source_record_id=WELLNESS_SOURCE,
                observations=[status()],
                mapper_version=1,
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "repeat a key"):
            self.replace_statuses(status(), status(code="RECOVERY"))

    def test_replace_validates_its_arguments(self) -> None:
        cases: dict[str, tuple[type[Exception], dict[str, Any]]] = {
            "mapper version bool": (TypeError, {"mapper_version": True}),
            "mapper version text": (TypeError, {"mapper_version": "1"}),
            "mapper version zero": (ValueError, {"mapper_version": 0}),
            "provider text": (TypeError, {"provider": "garmin"}),
            "empty source": (ValueError, {"source_record_id": ""}),
            "record of another type": (TypeError, {"periods": [status()]}),
        }
        for name, (error, overrides) in cases.items():
            arguments: dict[str, Any] = {
                "provider": ProviderId.GARMIN,
                "source_record_id": WELLNESS_SOURCE,
                "periods": [sleep_period()],
                "mapper_version": 1,
                "now": NOW,
                **overrides,
            }
            with self.subTest(name), self.assertRaises(error):
                canonical_domain_store.replace_sleep_periods(self.db, **arguments)

    def test_sleep_bounds_are_stored_in_utc(self) -> None:
        berlin = timezone(timedelta(hours=2))
        start = SLEEP_START.astimezone(berlin)
        self.replace_sleep(sleep_period(start=start, end=start + timedelta(hours=8)))
        self.assertEqual(
            [
                {
                    "started_at": "2026-10-19T22:30:00+00:00",
                    "ended_at": "2026-10-20T06:30:00+00:00",
                    "wake_date": "2026-10-20",
                }
            ],
            self.rows("SELECT started_at, ended_at, wake_date FROM sleep_periods"),
        )

    def test_zoned_sleep_bounds_round_trip_as_utc_instants(self) -> None:
        period = sleep_period(
            start=AUTUMN_START, end=AUTUMN_END, wake_date=date(2026, 10, 25)
        )
        self.replace_sleep(period)
        self.assertEqual(
            [
                {
                    "started_at": "2026-10-25T00:30:00+00:00",
                    "ended_at": "2026-10-25T01:15:00+00:00",
                    "wake_date": "2026-10-25",
                    "timezone": "Europe/Berlin",
                }
            ],
            self.rows(
                "SELECT started_at, ended_at, wake_date, timezone FROM sleep_periods"
            ),
        )
        stored = self.reader.sleep_periods(self.db)
        self.assertEqual((period,), stored)
        self.assertEqual(ReplaceResult(0, 0, 1, 0), self.replace_sleep(*stored))

    def test_known_context_and_zone_model_are_kept_in_details(self) -> None:
        self.replace_statuses(status(provenance=provenance(context=WATCH_CONTEXT)))
        canonical_domain_store.replace_zone_configurations(
            self.db,
            provider=ProviderId.INTERVALS,
            source_record_id=SETTINGS_SOURCE,
            configurations=[zone_configuration(model="five_zone")],
            mapper_version=1,
            now=NOW,
        )
        self.replace_sleep(sleep_period())
        self.assertEqual(
            {"context": WATCH_CONTEXT.as_details()},
            json.loads(
                self.rows("SELECT details FROM categorical_observations")[0]["details"]
            ),
        )
        self.assertEqual(
            {"model": "five_zone"},
            json.loads(
                self.rows("SELECT details FROM zone_configurations")[0]["details"]
            ),
        )
        self.assertEqual(
            [{"details": "{}"}], self.rows("SELECT details FROM sleep_periods")
        )


class DomainKeyTests(unittest.TestCase):
    def test_status_natural_keys_are_stable(self) -> None:
        self.assertEqual(
            "garmin|training_status||2026-10-20",
            canonical_domain_store.categorical_natural_key(status()),
        )
        self.assertEqual(
            "garmin|hrv_status|run|2026-10-20T06:00:00+00:00",
            canonical_domain_store.categorical_natural_key(
                status(
                    domain=CategoricalDomain.HRV_STATUS,
                    code="BALANCED",
                    sport=Sport.RUN,
                    observed_at=datetime(2026, 10, 20, 6, tzinfo=UTC),
                )
            ),
        )

    def test_zone_configuration_keys_are_stable(self) -> None:
        self.assertEqual(
            "intervals|heart_rate|run||",
            canonical_domain_store.zone_configuration_key(zone_configuration()),
        )
        self.assertEqual(
            "|power|ride|indoor|2026-10-01",
            canonical_domain_store.zone_configuration_key(
                local_zone_configuration(
                    metric=ZoneConfigurationMetric.POWER,
                    sport=Sport.RIDE,
                    environment=Environment.INDOOR,
                    valid_from=date(2026, 10, 1),
                    threshold=280.0,
                    maximum=None,
                    resting=None,
                    limits=(150.0, 210.0, 250.0, 300.0),
                )
            ),
        )


class LocalZoneConfigurationTests(DomainStoreFixture):
    def test_a_local_configuration_is_written_updated_and_retired(self) -> None:
        local = local_zone_configuration()
        key = canonical_domain_store.zone_configuration_key(local)
        upsert = canonical_domain_store.upsert_local_zone_configuration
        self.assertIs(WriteOutcome.WRITTEN, upsert(self.db, local, now=NOW))
        self.assertIs(WriteOutcome.UNCHANGED, upsert(self.db, local, now=NOW))
        changed = replace(local, threshold=170.0)
        self.assertIs(WriteOutcome.UPDATED, upsert(self.db, changed, now=LATER))
        self.assertEqual((changed,), self.reader.zone_configurations(self.db))
        self.assertEqual(
            [{"provider": None, "source_record_id": None, "mapper_version": None}],
            self.rows(
                "SELECT provider, source_record_id, mapper_version "
                "FROM zone_configurations"
            ),
        )
        retire = canonical_domain_store.retire_local_zone_configuration
        self.assertTrue(retire(self.db, key, now=LATER))
        self.assertFalse(retire(self.db, key, now=LATER))
        self.assertEqual((), self.reader.zone_configurations(self.db))
        self.assertIs(WriteOutcome.UPDATED, upsert(self.db, changed, now=LATER))
        self.assertEqual((changed,), self.reader.zone_configurations(self.db))

    def test_provider_configurations_are_not_local(self) -> None:
        with self.assertRaisesRegex(ValueError, "has no provider"):
            canonical_domain_store.upsert_local_zone_configuration(
                self.db, zone_configuration(), now=NOW
            )
        canonical_domain_store.replace_zone_configurations(
            self.db,
            provider=ProviderId.INTERVALS,
            source_record_id=SETTINGS_SOURCE,
            configurations=[zone_configuration()],
            mapper_version=1,
            now=NOW,
        )
        provider_key = canonical_domain_store.zone_configuration_key(
            zone_configuration()
        )
        self.assertFalse(
            canonical_domain_store.retire_local_zone_configuration(
                self.db, provider_key, now=LATER
            )
        )

    def test_a_provider_replace_keeps_local_configurations(self) -> None:
        local = local_zone_configuration()
        canonical_domain_store.upsert_local_zone_configuration(self.db, local, now=NOW)
        result = canonical_domain_store.replace_zone_configurations(
            self.db,
            provider=ProviderId.INTERVALS,
            source_record_id=SETTINGS_SOURCE,
            configurations=[],
            mapper_version=1,
            now=LATER,
        )
        self.assertEqual(ReplaceResult(0, 0, 0, 0), result)
        self.assertEqual((local,), self.reader.zone_configurations(self.db))


class DomainReaderTests(DomainStoreFixture):
    def test_every_domain_record_round_trips_through_store_and_reader(self) -> None:
        sleep = sleep_period(provenance=provenance(context=WATCH_CONTEXT))
        observation = status(
            domain=CategoricalDomain.READINESS_LEVEL,
            code="HIGH",
            observed_at=datetime(2026, 10, 20, 6, 5, tzinfo=UTC),
            sport=Sport.RUN,
            provenance=provenance(context=WATCH_CONTEXT),
        )
        zones = (
            zone_configuration(model="five_zone", valid_from=date(2026, 9, 1)),
            zone_configuration(
                metric=ZoneConfigurationMetric.PACE,
                threshold=4.2,
                maximum=None,
                resting=None,
                limits=None,
                percent_limits=(78.0, 88.0, 94.0, 100.0, 999.0),
                percent_basis=ZonePercentBasis.THRESHOLD,
            ),
        )
        item = gear_item()
        links = (gear_link("i1001"), gear_link("i1002"))
        self.replace_sleep(sleep)
        self.replace_statuses(observation)
        common: dict[str, Any] = {"mapper_version": 2, "now": NOW}
        canonical_domain_store.replace_zone_configurations(
            self.db,
            provider=ProviderId.INTERVALS,
            source_record_id=SETTINGS_SOURCE,
            configurations=zones,
            **common,
        )
        canonical_domain_store.replace_gear_items(
            self.db,
            provider=ProviderId.INTERVALS,
            source_record_id=GEAR_SOURCE,
            items=[item],
            **common,
        )
        canonical_domain_store.replace_gear_activity_links(
            self.db,
            provider=ProviderId.INTERVALS,
            source_record_id=GEAR_SOURCE,
            links=links,
            **common,
        )
        self.assertEqual((sleep,), self.reader.sleep_periods(self.db))
        self.assertEqual(
            (observation,),
            self.reader.categorical_observations(
                self.db, CategoricalDomain.READINESS_LEVEL
            ),
        )
        self.assertEqual(
            (),
            self.reader.categorical_observations(
                self.db, CategoricalDomain.TRAINING_STATUS
            ),
        )
        self.assertEqual(
            sorted(zones, key=canonical_domain_store.zone_configuration_key),
            list(self.reader.zone_configurations(self.db)),
        )
        self.assertEqual((item,), self.reader.gear_items(self.db))
        self.assertEqual(links, self.reader.gear_activity_links(self.db))

    def test_sleep_and_statuses_are_filtered_by_inclusive_day(self) -> None:
        first = sleep_period()
        second = sleep_period(
            start=SLEEP_START + timedelta(days=1),
            end=SLEEP_START + timedelta(days=1, hours=8),
            wake_date=date(2026, 10, 21),
        )
        self.replace_sleep(second, first)
        self.assertEqual((first, second), self.reader.sleep_periods(self.db))
        self.assertEqual(
            (second,), self.reader.sleep_periods(self.db, start=date(2026, 10, 21))
        )
        self.assertEqual(
            (first,), self.reader.sleep_periods(self.db, end=date(2026, 10, 20))
        )
        later = status(observed_on=date(2026, 10, 21), code="RECOVERY")
        self.replace_statuses(later, status())
        self.assertEqual(
            (later,),
            self.reader.categorical_observations(
                self.db,
                CategoricalDomain.TRAINING_STATUS,
                start=date(2026, 10, 21),
                end=date(2026, 10, 21),
            ),
        )


if __name__ == "__main__":
    unittest.main()
