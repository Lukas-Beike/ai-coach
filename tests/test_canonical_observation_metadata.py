"""Observation metadata, measurement context and merged-session retention.

Each store test uses a temporary SQLite file with the schema initialized. No
provider account, network, real data directory or encryption key is involved.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.records import (
    FORM_METHOD,
    FORM_METHOD_VERSION,
    UNKNOWN_CONTEXT,
    ActivityRecord,
    MeasurementContext,
    MetricValue,
    Observation,
    ObservationPeriod,
    Provenance,
    fingerprint_inputs,
)
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    MetricKind,
    ObservationAggregation,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store, row_factory
from backend.db.canonical_store import WriteOutcome
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    current_observation_mapper_versions,
)
from backend.providers.intervals_wellness_mapping import map_intervals_wellness
from backend.sync.canonical_table_reader import CanonicalTableReader

RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
STAMP = "2026-10-11T08:00:00+00:00"
LATER = "2026-10-12T08:00:00+00:00"
NIGHT = ObservationPeriod(
    start=datetime(2026, 10, 10, 22, 0, tzinfo=UTC),
    end=datetime(2026, 10, 11, 6, 0, tzinfo=UTC),
)
CONTEXT = MeasurementContext(
    device_model="HRM 600",
    firmware="3.10",
    algorithm="rmssd_overnight",
    sensor="chest_strap",
    window="overnight",
    protocol="ble",
)
FINGERPRINT = fingerprint_inputs({"samples": [41.0, 44.5]})
NAIVE_TIME = datetime(2026, 10, 11, 6, 0)  # noqa: DTZ001 - naive value under test
BERLIN = ZoneInfo("Europe/Berlin")
# 02:30 summer time, then 02:15 winter time, is 45 minutes later.
AUTUMN_START = datetime(2026, 10, 25, 2, 30, tzinfo=BERLIN)
AUTUMN_END = datetime(2026, 10, 25, 2, 15, fold=1, tzinfo=BERLIN)


def provenance(
    *,
    source_kind: SourceKind = SourceKind.PROVIDER_REPORTED,
    context: MeasurementContext = UNKNOWN_CONTEXT,
) -> Provenance:
    return Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=source_kind,
        source_record_id="2026-10-11",
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=RETRIEVED_AT,
        label=None,
        context=context,
    )


def observation(**overrides: Any) -> Observation:
    values: dict[str, Any] = {
        "kind": MetricKind.HRV_RMSSD,
        "value": MetricValue(42.5, MetricKind.HRV_RMSSD.unit),
        "observed_on": date(2026, 10, 11),
        "observed_at": None,
        "provenance": provenance(),
    }
    values.update(overrides)
    return Observation(**values)


def derived_form(**overrides: Any) -> Observation:
    values: dict[str, Any] = {
        "kind": MetricKind.FORM,
        "value": MetricValue(-8.33, MetricKind.FORM.unit),
        "provenance": provenance(source_kind=SourceKind.DERIVED),
        "method": FORM_METHOD,
        "method_version": FORM_METHOD_VERSION,
        "input_fingerprint": fingerprint_inputs({"ctl": 52.1, "atl": 60.43}),
    }
    values.update(overrides)
    return observation(**values)


class MeasurementContextTests(unittest.TestCase):
    def test_an_unknown_context_has_no_details_and_a_fixed_identity(self) -> None:
        self.assertTrue(UNKNOWN_CONTEXT.is_unknown)
        self.assertFalse(CONTEXT.is_unknown)
        self.assertEqual({}, UNKNOWN_CONTEXT.as_details())
        self.assertEqual(
            hashlib.sha256(
                b'["measurement-context-v1",null,null,null,null,null,null]'
            ).hexdigest(),
            UNKNOWN_CONTEXT.identity,
        )

    def test_the_identity_is_stable_and_changes_with_every_field(self) -> None:
        self.assertEqual(CONTEXT.identity, replace(CONTEXT).identity)
        identities = {UNKNOWN_CONTEXT.identity, CONTEXT.identity}
        for field in CONTEXT.as_details():
            identities.add(replace(CONTEXT, **{field: None}).identity)
        self.assertEqual(8, len(identities))

    def test_details_round_trip_and_other_keys_are_rejected(self) -> None:
        self.assertEqual(CONTEXT, MeasurementContext.from_details(CONTEXT.as_details()))
        self.assertEqual(UNKNOWN_CONTEXT, MeasurementContext.from_details({}))
        with self.assertRaises(ValueError):
            MeasurementContext.from_details({"serial_number": "x"})
        with self.assertRaises(TypeError):
            MeasurementContext.from_details(["device_model"])

    def test_device_identifiers_and_free_text_are_rejected(self) -> None:
        cases: dict[str, tuple[type[Exception], dict[str, Any]]] = {
            "hex serial in model": (ValueError, {"device_model": "Edge 3A9F12BC"}),
            "digit run in model": (ValueError, {"device_model": "Unit 1234567"}),
            "untrimmed model": (ValueError, {"device_model": " Edge 1040"}),
            "control character": (ValueError, {"device_model": "Edge\t1040"}),
            "long model": (ValueError, {"device_model": "x" * 101}),
            "model not text": (TypeError, {"device_model": 1040}),
            "firmware with a space": (ValueError, {"firmware": "21 19"}),
            "firmware not text": (TypeError, {"firmware": 21}),
            "algorithm not a slug": (ValueError, {"algorithm": "Firstbeat V2"}),
            "sensor not text": (TypeError, {"sensor": 3}),
            "window not a slug": (ValueError, {"window": "over night"}),
        }
        for name, (error, values) in cases.items():
            with self.subTest(name), self.assertRaises(error):
                MeasurementContext(**values)


class ObservationMetadataTests(unittest.TestCase):
    def test_metadata_is_optional_and_kept(self) -> None:
        plain = observation()
        self.assertIsNone(plain.method)
        self.assertIsNone(plain.period)
        described = observation(
            method="rmssd",
            aggregation=ObservationAggregation.MEAN,
            method_version=2,
            input_fingerprint=FINGERPRINT,
            period=NIGHT,
        )
        self.assertEqual(NIGHT, described.period)

    def test_invalid_metadata_is_rejected(self) -> None:
        cases: dict[str, tuple[type[Exception], dict[str, Any]]] = {
            "method not a slug": (ValueError, {"method": "RMSSD"}),
            "aggregation text": (TypeError, {"aggregation": "mean"}),
            "version zero": (ValueError, {"method": "rmssd", "method_version": 0}),
            "version too high": (
                ValueError,
                {"method": "rmssd", "method_version": 10_001},
            ),
            "version bool": (TypeError, {"method": "rmssd", "method_version": True}),
            "short fingerprint": (
                ValueError,
                {"method": "rmssd", "input_fingerprint": "ab" * 31},
            ),
            "upper-case fingerprint": (
                ValueError,
                {"method": "rmssd", "input_fingerprint": FINGERPRINT.upper()},
            ),
            "version without method": (ValueError, {"method_version": 1}),
            "fingerprint without method": (
                ValueError,
                {"input_fingerprint": FINGERPRINT},
            ),
            "period text": (TypeError, {"period": "overnight"}),
        }
        for name, (error, overrides) in cases.items():
            with self.subTest(name), self.assertRaises(error):
                observation(**overrides)

    def test_invalid_periods_are_rejected(self) -> None:
        start = NIGHT.start
        cases: dict[str, tuple[type[Exception], datetime, datetime]] = {
            "end before start": (ValueError, start, start),
            "longer than 366 days": (ValueError, start, start + timedelta(days=367)),
            # Summer time at the start and winter time at the end add an hour
            # to the wall-clock span of 366 days less half an hour.
            "longer than 366 days across a DST change": (
                ValueError,
                datetime(2027, 10, 30, 12, 0, tzinfo=BERLIN),
                datetime(2028, 10, 30, 11, 30, tzinfo=BERLIN),
            ),
            "naive start": (ValueError, NAIVE_TIME, start + timedelta(days=1)),
            "start before the UTC range": (
                ValueError,
                datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))),
                start,
            ),
        }
        for name, (error, begin, end) in cases.items():
            with self.subTest(name), self.assertRaises(error):
                ObservationPeriod(start=begin, end=end)

    def test_order_and_length_use_utc_instants(self) -> None:
        night = ObservationPeriod(start=AUTUMN_START, end=AUTUMN_END)
        self.assertEqual(
            (
                datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
                datetime(2026, 10, 25, 1, 15, tzinfo=UTC),
            ),
            (night.start, night.end),
        )
        self.assertIs(UTC, night.end.tzinfo)
        # Winter time at the start and summer time at the end take an hour
        # from the wall-clock span of 366 days and half an hour.
        year = ObservationPeriod(
            start=datetime(2026, 3, 28, 12, 0, tzinfo=BERLIN),
            end=datetime(2027, 3, 29, 12, 30, tzinfo=BERLIN),
        )
        self.assertEqual(timedelta(days=366, minutes=-30), year.end - year.start)

    def test_derived_observations_name_method_version_and_inputs(self) -> None:
        self.assertEqual(FORM_METHOD, derived_form().method)
        for missing in ("method", "method_version", "input_fingerprint"):
            with self.subTest(missing), self.assertRaises(ValueError):
                derived_form(**{missing: None})

    def test_input_fingerprints_ignore_key_order_and_reject_nan(self) -> None:
        self.assertEqual(
            fingerprint_inputs({"ctl": 52.1, "atl": 60.43}),
            fingerprint_inputs({"atl": 60.43, "ctl": 52.1}),
        )
        self.assertNotEqual(
            fingerprint_inputs({"ctl": 52.1, "atl": 60.43}),
            fingerprint_inputs({"ctl": 52.1, "atl": 60.44}),
        )
        with self.assertRaises(ValueError):
            fingerprint_inputs({"ctl": float("nan")})

    def test_the_wellness_mapper_derives_form_with_its_inputs(self) -> None:
        result = map_intervals_wellness(
            [{"id": "2026-10-08", "ctl": 52.1, "atl": 60.43}],
            retrieved_at=RETRIEVED_AT,
        )
        values = {record.kind: record for record in result.records}
        form = values[MetricKind.FORM]
        self.assertIs(SourceKind.DERIVED, form.provenance.source_kind)
        self.assertEqual(
            (
                FORM_METHOD,
                FORM_METHOD_VERSION,
                fingerprint_inputs(
                    {
                        "ctl": values[MetricKind.CTL].value.value,
                        "atl": values[MetricKind.ATL].value.value,
                    }
                ),
            ),
            (form.method, form.method_version, form.input_fingerprint),
        )


def stored_observations(db: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            "SELECT natural_key, method, aggregation, details FROM observations"
        ).fetchall()
    ]


class ObservationStoreFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = sqlite3.connect(Path(self.temporary.name) / "metadata.db")
        self.addCleanup(self.db.close)
        self.db.row_factory = row_factory
        self.db.execute("PRAGMA foreign_keys = ON")
        initialize_schema(self.db)
        self.db.commit()
        self.version = current_observation_mapper_versions()["intervals"]
        self.reader = CanonicalTableReader()

    def write(self, record: Observation) -> WriteOutcome:
        return canonical_store.upsert_observation(
            self.db, record, mapper_version=self.version, now=STAMP
        )


class ObservationMetadataStoreTests(ObservationStoreFixture):
    def test_metadata_and_context_round_trip_through_store_and_reader(self) -> None:
        record = observation(
            provenance=provenance(context=CONTEXT),
            method="rmssd",
            aggregation=ObservationAggregation.MEAN,
            method_version=2,
            input_fingerprint=FINGERPRINT,
            period=NIGHT,
        )
        self.assertIs(WriteOutcome.WRITTEN, self.write(record))
        (row,) = stored_observations(self.db)
        self.assertEqual(("rmssd", "mean"), (row["method"], row["aggregation"]))
        self.assertEqual(
            {
                "context": CONTEXT.as_details(),
                "method_version": 2,
                "input_fingerprint": FINGERPRINT,
                "period": {
                    "start": "2026-10-10T22:00:00+00:00",
                    "end": "2026-10-11T06:00:00+00:00",
                },
            },
            json.loads(row["details"]),
        )
        self.assertEqual(
            (record,), self.reader.observations(self.db, MetricKind.HRV_RMSSD)
        )

    def test_a_device_change_mid_series_is_a_visible_continuity_break(self) -> None:
        # #1420: the reader output shows where the measuring device changed.
        newer = replace(CONTEXT, device_model="Forerunner 965")
        for day, context in (
            (date(2026, 10, 9), CONTEXT),
            (date(2026, 10, 10), CONTEXT),
            (date(2026, 10, 11), newer),
            (date(2026, 10, 12), UNKNOWN_CONTEXT),
        ):
            self.write(
                observation(observed_on=day, provenance=provenance(context=context))
            )
        series = self.reader.observations(self.db, MetricKind.HRV_RMSSD)
        identities = [record.provenance.context.identity for record in series]
        self.assertEqual(identities[0], identities[1])
        self.assertEqual(len(set(identities)), 3)
        self.assertTrue(series[-1].provenance.context.is_unknown)

    def test_a_zoned_period_round_trips_as_utc_instants(self) -> None:
        record = observation(
            method="rmssd",
            period=ObservationPeriod(start=AUTUMN_START, end=AUTUMN_END),
        )
        self.assertIs(WriteOutcome.WRITTEN, self.write(record))
        (row,) = stored_observations(self.db)
        self.assertEqual(
            {"start": "2026-10-25T00:30:00+00:00", "end": "2026-10-25T01:15:00+00:00"},
            json.loads(row["details"])["period"],
        )
        (stored,) = self.reader.observations(self.db, MetricKind.HRV_RMSSD)
        self.assertEqual(record, stored)
        self.assertIs(WriteOutcome.UNCHANGED, self.write(stored))

    def test_a_row_without_metadata_keeps_empty_details_and_stays_unchanged(
        self,
    ) -> None:
        self.assertIs(WriteOutcome.WRITTEN, self.write(observation()))
        self.assertEqual(
            [{"method": None, "aggregation": None, "details": "{}"}],
            [
                {key: row[key] for key in ("method", "aggregation", "details")}
                for row in stored_observations(self.db)
            ],
        )
        self.assertIs(WriteOutcome.UNCHANGED, self.write(observation()))
        self.assertEqual(
            (observation(),), self.reader.observations(self.db, MetricKind.HRV_RMSSD)
        )

    def test_metadata_and_context_changes_update_the_row_under_its_key(self) -> None:
        base = observation()
        described = observation(method="rmssd", aggregation=ObservationAggregation.MEAN)
        measured = replace(described, provenance=provenance(context=CONTEXT))
        key = canonical_store.observation_natural_key(base)
        self.assertEqual(key, canonical_store.observation_natural_key(described))
        self.assertEqual(key, canonical_store.observation_natural_key(measured))
        self.write(base)
        self.assertIs(WriteOutcome.UPDATED, self.write(described))
        self.assertIs(WriteOutcome.UPDATED, self.write(measured))
        self.assertIs(WriteOutcome.UNCHANGED, self.write(measured))
        self.assertEqual(
            [key], [row["natural_key"] for row in stored_observations(self.db)]
        )

    def test_a_derived_form_row_without_metadata_reads_with_its_method(self) -> None:
        self.write(derived_form())
        # A derived FORM row written before schema version 15.
        self.db.execute("UPDATE observations SET method = NULL, details = '{}'")
        (legacy,) = self.reader.observations(self.db, MetricKind.FORM)
        self.assertEqual(
            (
                FORM_METHOD,
                FORM_METHOD_VERSION,
                fingerprint_inputs(
                    {
                        "unversioned_row": "intervals",
                        "source_record_id": "2026-10-11",
                        "observed_on": "2026-10-11",
                        "value": -8.33,
                    }
                ),
            ),
            (legacy.method, legacy.method_version, legacy.input_fingerprint),
        )
        self.assertIs(WriteOutcome.UPDATED, self.write(derived_form()))
        self.assertEqual(
            (derived_form(),), self.reader.observations(self.db, MetricKind.FORM)
        )


ACTIVITY_START = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)


class MergedSessionRetentionTests(ObservationStoreFixture):
    """A deleted alias keeps its merge survivor, so feedback written for it resolves."""

    def seed(self, source_id: str, provider: ProviderId, *, hours: int = 0) -> str:
        record = ActivityRecord(
            activity_id="unused",
            provenance=Provenance(
                provider=provider,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=source_id,
                recorded_by=RecordingOrigin.UNKNOWN,
                retrieved_at=RETRIEVED_AT,
                label=None,
            ),
            sport=Sport.RIDE,
            environment=Environment.OUTDOOR,
            started_at=ACTIVITY_START + timedelta(hours=hours),
            duration_s=3600.0,
            distance_m=30000.0,
            load=50.0,
            load_model=LoadModel.INTERVALS_TRAINING_LOAD,
            avg_hr=140.0,
            avg_power=210.0,
            name="Synthetic ride",
        )
        canonical_store.upsert_activity_record(
            self.db,
            record,
            local_date=date(2026, 6, 1),
            mapper_version=1,
            fetched_at=STAMP,
            now=STAMP,
        )
        canonical_store.upsert_provider_record(
            self.db,
            provider=provider.value,
            record_kind=ACTIVITY_RECORD_KIND,
            source_record_id=source_id,
            payload={"id": source_id},
            mapper_version=1,
            fetched_at=STAMP,
            now=STAMP,
        )
        return str(
            self.db.execute(
                "SELECT activity_id FROM activity_records "
                "WHERE provider = ? AND provider_activity_id = ?",
                (provider.value, source_id),
            ).fetchone()["activity_id"]
        )

    def session(self, activity_id: str) -> tuple[Any, ...]:
        row = self.db.execute(
            "SELECT state, merged_into, merged_into_retained FROM activity_sessions "
            "WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        return (row["state"], row["merged_into"], row["merged_into_retained"])

    def merge(self, activity_id: str, into: str) -> None:
        self.assertTrue(
            canonical_store.merge_activity_session(
                self.db, activity_id=activity_id, into=into, now=STAMP
            )
        )

    def delete_intervals_alias(self) -> None:
        self.assertTrue(
            canonical_store.mark_activity_deleted(
                self.db,
                ProviderId.INTERVALS.value,
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id="intervals-1",
                now=LATER,
            )
        )

    def test_a_deleted_alias_keeps_its_survivor_until_it_is_revived(self) -> None:
        keep = self.seed("wahoo-1", ProviderId.WAHOO)
        alias = self.seed("intervals-1", ProviderId.INTERVALS)
        self.merge(alias, keep)
        self.delete_intervals_alias()
        self.assertEqual(("deleted", None, keep), self.session(alias))
        self.assertEqual(
            {alias: keep, keep: keep},
            canonical_store.effective_session_ids(self.db, [alias, keep, "missing"]),
        )
        self.seed("intervals-1", ProviderId.INTERVALS)
        self.assertEqual(("active", None, None), self.session(alias))
        self.assertEqual(
            {alias: alias}, canonical_store.effective_session_ids(self.db, [alias])
        )
        self.assertEqual({}, canonical_store.effective_session_ids(self.db, []))

    def test_merging_the_survivor_re_points_its_deleted_aliases(self) -> None:
        first = self.seed("wahoo-1", ProviderId.WAHOO)
        alias = self.seed("intervals-1", ProviderId.INTERVALS)
        self.merge(alias, first)
        self.delete_intervals_alias()
        third = self.seed("garmin-1", ProviderId.GARMIN, hours=2)
        self.merge(first, third)
        self.assertEqual(("deleted", None, third), self.session(alias))
        self.assertEqual(
            {alias: third, first: third},
            canonical_store.effective_session_ids(self.db, [alias, first]),
        )

    def test_a_chain_is_followed_and_a_cycle_stops_the_walk(self) -> None:
        first = self.seed("wahoo-1", ProviderId.WAHOO)
        second = self.seed("intervals-1", ProviderId.INTERVALS, hours=2)
        last = self.seed("garmin-1", ProviderId.GARMIN, hours=4)
        retain = (
            "UPDATE activity_sessions SET state = 'deleted', "
            "merged_into_retained = ? WHERE activity_id = ?"
        )
        self.db.execute(retain, (second, first))
        self.db.execute(retain, (last, second))
        self.assertEqual(
            {first: last}, canonical_store.effective_session_ids(self.db, [first])
        )
        self.db.execute(retain, (first, last))
        self.assertEqual(
            {first: last, second: first, last: second},
            canonical_store.effective_session_ids(self.db, [first, second, last]),
        )


if __name__ == "__main__":
    unittest.main()
