"""Canonical persistence: write outcomes, natural keys, deletion marks and row fetching.

Each test uses a temporary SQLite file with the schema initialized. No provider
account, network, real data directory or encryption key is involved.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.canonical.records import (
    ActivityRecord,
    MetricValue,
    Observation,
    Provenance,
)
from backend.canonical.vocabulary import (
    DeviceType,
    Environment,
    LoadModel,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store
from backend.db.canonical_store import WriteOutcome
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND

RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
STAMP = "2026-10-11T08:00:00+00:00"
LATER = "2026-10-12T08:00:00+00:00"
ACTIVITY_START = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)


def provenance(
    source_record_id: str | None = "act-1",
    *,
    provider: ProviderId | None = ProviderId.INTERVALS,
) -> Provenance:
    return Provenance(
        provider=provider,
        source_kind=(
            SourceKind.PROVIDER_REPORTED
            if provider is not None
            else SourceKind.ATHLETE_ENTERED
        ),
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=RETRIEVED_AT,
        label=None,
    )


def activity(
    source_record_id: str = "act-1",
    *,
    name: str | None = "Synthetic ride",
    load: float | None = 50.0,
    started_at: datetime = ACTIVITY_START,
) -> ActivityRecord:
    return ActivityRecord(
        activity_id="unused",
        provenance=provenance(source_record_id),
        sport=Sport.RIDE,
        environment=Environment.OUTDOOR,
        started_at=started_at,
        duration_s=3600.0,
        distance_m=30000.0,
        load=load,
        load_model=LoadModel.INTERVALS_TRAINING_LOAD,
        avg_hr=140.0,
        avg_power=210.0,
        name=name,
    )


def observation(
    value: float = 72.5,
    *,
    kind: MetricKind = MetricKind.WEIGHT,
    observed_on: date = date(2026, 10, 1),
    observed_at: datetime | None = None,
    sport: Sport | None = None,
    provider: ProviderId | None = ProviderId.INTERVALS,
    source_record_id: str | None = None,
) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value=value, unit=kind.unit),
        observed_on=observed_on,
        observed_at=observed_at,
        provenance=provenance(source_record_id, provider=provider),
        sport=sport,
    )


class _MappingCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _MappingDb:
    """A connection whose rows are already mappings, as some row factories return."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, _sql: str, _params: tuple[object, ...] = ()) -> _MappingCursor:
        return _MappingCursor(self._rows)


class StoreFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = sqlite3.connect(Path(self.temporary.name) / "store.db")
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys = ON")
        initialize_schema(self.db)
        self.db.commit()

    def one(self, sql: str, params: tuple[object, ...] = ()) -> tuple[Any, ...]:
        row = self.db.execute(sql, params).fetchone()
        assert row is not None
        return row

    def count(self, table: str) -> int:
        return int(self.one(f"SELECT COUNT(*) FROM {table}")[0])


class CanonicalJsonTests(unittest.TestCase):
    def test_keys_are_sorted_and_text_is_kept_unescaped(self) -> None:
        self.assertEqual(
            canonical_store.canonical_json({"b": 1, "a": "ü"}),
            '{"a":"ü","b":1}',
        )

    def test_payload_hash_is_the_sha256_of_the_utf8_text(self) -> None:
        text = canonical_store.canonical_json({"a": "ü"})
        self.assertEqual(
            canonical_store.payload_hash(text),
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )


class ProviderRecordStoreTests(StoreFixture):
    def write(self, payload: dict[str, Any], *, version: int = 1, now: str = STAMP):
        return canonical_store.upsert_provider_record(
            self.db,
            provider="intervals",
            record_kind="activity",
            source_record_id="rec-1",
            payload=payload,
            mapper_version=version,
            fetched_at=STAMP,
            now=now,
        )

    def test_new_record_is_written_with_its_hash_and_version(self) -> None:
        self.assertIs(self.write({"name": "Ride"}), WriteOutcome.WRITTEN)
        text, digest, version, state = self.one(
            "SELECT payload, payload_hash, mapped_version, state FROM provider_records"
        )
        self.assertEqual(text, '{"name":"Ride"}')
        self.assertEqual(digest, canonical_store.payload_hash(text))
        self.assertEqual((version, state), (1, "active"))

    def test_same_payload_and_version_is_unchanged_and_not_rewritten(self) -> None:
        self.write({"name": "Ride"})
        self.assertIs(self.write({"name": "Ride"}, now=LATER), WriteOutcome.UNCHANGED)
        self.assertEqual(self.one("SELECT updated_at FROM provider_records")[0], STAMP)

    def test_changed_payload_is_updated_in_place(self) -> None:
        self.write({"name": "Ride"})
        self.assertIs(
            self.write({"name": "Long ride"}, now=LATER), WriteOutcome.UPDATED
        )
        text, digest, updated_at = self.one(
            "SELECT payload, payload_hash, updated_at FROM provider_records"
        )
        self.assertEqual(text, '{"name":"Long ride"}')
        self.assertEqual(digest, canonical_store.payload_hash(text))
        self.assertEqual(updated_at, LATER)
        self.assertEqual(self.count("provider_records"), 1)

    def test_changed_mapper_version_alone_updates_the_record(self) -> None:
        self.write({"name": "Ride"})
        self.assertIs(self.write({"name": "Ride"}, version=2), WriteOutcome.UPDATED)
        self.assertEqual(self.one("SELECT mapped_version FROM provider_records")[0], 2)

    def test_a_deleted_record_seen_again_is_reactivated(self) -> None:
        self.write({"name": "Ride"})
        self.db.execute("UPDATE provider_records SET state = 'deleted'")
        self.assertIs(self.write({"name": "Ride"}, now=LATER), WriteOutcome.UPDATED)
        self.assertEqual(self.one("SELECT state FROM provider_records")[0], "active")


class ActivityStoreTests(StoreFixture):
    def write(self, record: ActivityRecord, *, local: date = date(2026, 6, 1)):
        return canonical_store.upsert_activity_record(
            self.db,
            record,
            local_date=local,
            mapper_version=1,
            fetched_at=STAMP,
            now=STAMP,
        )

    def test_new_activity_gets_a_single_link_session(self) -> None:
        self.assertIs(self.write(activity()), WriteOutcome.WRITTEN)
        session_id, link, confirmed, state, local = self.one(
            "SELECT s.activity_id, s.link_kind, s.athlete_confirmed, s.state, s.local_date "
            "FROM activity_sessions s"
        )
        self.assertTrue(session_id.startswith(canonical_store.ACTIVITY_ID_PREFIX))
        self.assertEqual(
            (link, confirmed, state, local), ("single", 0, "active", "2026-06-01")
        )
        record_session = self.one(
            "SELECT activity_id, state, load FROM activity_records"
        )
        self.assertEqual(record_session, (session_id, "active", 50.0))

    def test_identical_activity_is_unchanged(self) -> None:
        self.write(activity())
        self.assertIs(self.write(activity()), WriteOutcome.UNCHANGED)
        self.assertEqual(self.count("activity_sessions"), 1)

    def test_identical_resync_refreshes_the_fetch_time(self) -> None:
        self.write(activity())
        outcome = canonical_store.upsert_activity_record(
            self.db,
            activity(),
            local_date=date(2026, 6, 1),
            mapper_version=1,
            fetched_at=LATER,
            now=LATER,
        )
        self.assertIs(outcome, WriteOutcome.UNCHANGED)
        self.assertEqual(self.one("SELECT fetched_at FROM activity_records")[0], LATER)
        self.assertEqual(self.count("activity_sessions"), 1)

    def test_changed_activity_keeps_its_id_and_is_updated(self) -> None:
        self.write(activity())
        original_id = self.one("SELECT activity_id FROM activity_records")[0]
        outcome = self.write(
            activity(name="Renamed", load=None), local=date(2026, 6, 2)
        )
        self.assertIs(outcome, WriteOutcome.UPDATED)
        name, load, load_model = self.one(
            "SELECT name, load, load_model FROM activity_records"
        )
        self.assertEqual(
            (name, load, load_model), ("Renamed", None, "intervals_training_load")
        )
        self.assertEqual(
            self.one("SELECT activity_id, local_date FROM activity_sessions"),
            (original_id, "2026-06-02"),
        )
        self.assertEqual(self.count("activity_sessions"), 1)

    def test_null_load_is_stored_as_null_and_stays_unchanged(self) -> None:
        self.write(activity(load=None))
        self.assertIsNone(self.one("SELECT load FROM activity_records")[0])
        self.assertIs(self.write(activity(load=None)), WriteOutcome.UNCHANGED)

    def test_deleted_activity_seen_again_is_reactivated_with_its_session(self) -> None:
        self.write(activity())
        self.db.execute("UPDATE activity_records SET state = 'deleted'")
        self.db.execute("UPDATE activity_sessions SET state = 'deleted'")
        self.assertIs(self.write(activity()), WriteOutcome.UPDATED)
        self.assertEqual(self.one("SELECT state FROM activity_records")[0], "active")
        self.assertEqual(self.one("SELECT state FROM activity_sessions")[0], "active")

    def test_activity_without_provider_or_source_id_is_refused(self) -> None:
        no_provider = replace(activity(), provenance=provenance(None, provider=None))
        no_source = replace(activity(), provenance=provenance(None))
        for record in (no_provider, no_source):
            with self.subTest(record=record.provenance), self.assertRaises(ValueError):
                self.write(record)
        self.assertEqual(self.count("activity_records"), 0)
        self.assertEqual(self.count("activity_sessions"), 0)


class ObservationStoreTests(StoreFixture):
    def write(self, item: Observation, *, now: str = STAMP) -> WriteOutcome:
        return canonical_store.upsert_observation(
            self.db, item, mapper_version=2, now=now
        )

    def test_natural_key_uses_provider_metric_sport_and_observation_time(self) -> None:
        by_day = observation(source_record_id="2026-10-01")
        self.assertEqual(
            canonical_store.observation_natural_key(by_day),
            "intervals|weight|||2026-10-01",
        )
        by_moment = observation(
            observed_at=datetime(2026, 10, 1, 7, 0, tzinfo=UTC),
            sport=Sport.RIDE,
            provider=None,
        )
        self.assertEqual(
            canonical_store.observation_natural_key(by_moment),
            "|weight|ride||2026-10-01T07:00:00+00:00",
        )

    def test_athlete_profile_weight_has_its_own_series_in_either_write_order(
        self,
    ) -> None:
        wellness = observation(72.5, source_record_id="2026-10-01")
        for athlete_id in ("i12345", None):
            athlete = observation(70.0, source_record_id=athlete_id)
            self.assertEqual(
                canonical_store.observation_natural_key(athlete),
                "intervals|weight||athlete|2026-10-01",
            )
            self.assertNotEqual(
                canonical_store.observation_natural_key(athlete),
                canonical_store.observation_natural_key(wellness),
            )
        athlete = observation(70.0, source_record_id="i12345")
        for first, second in ((wellness, athlete), (athlete, wellness)):
            self.db.execute("DELETE FROM observations")
            self.assertIs(self.write(first), WriteOutcome.WRITTEN)
            self.assertIs(self.write(second), WriteOutcome.WRITTEN)
            values = self.db.execute("SELECT value FROM observations").fetchall()
            self.assertEqual(sorted(row[0] for row in values), [70.0, 72.5])

    def test_athlete_profile_eftp_has_its_own_series(self) -> None:
        wellness = observation(
            258.0, kind=MetricKind.EFTP, sport=Sport.RIDE, source_record_id="2026-10-01"
        )
        athlete = observation(
            262.0, kind=MetricKind.EFTP, sport=Sport.RIDE, source_record_id="i12345"
        )
        self.assertEqual(
            canonical_store.observation_natural_key(athlete),
            "intervals|eftp|ride|athlete|2026-10-01",
        )
        self.assertEqual(
            canonical_store.observation_natural_key(wellness),
            "intervals|eftp|ride||2026-10-01",
        )
        self.assertIs(self.write(wellness), WriteOutcome.WRITTEN)
        self.assertIs(self.write(athlete), WriteOutcome.WRITTEN)
        self.assertEqual(self.count("observations"), 2)

    def test_other_athlete_profile_kinds_share_the_daily_key(self) -> None:
        ftp = observation(
            260.0, kind=MetricKind.FTP, sport=Sport.RIDE, source_record_id="i12345"
        )
        self.assertEqual(
            canonical_store.observation_natural_key(ftp), "intervals|ftp|ride||2026-10-01"
        )

    def test_insert_unchanged_and_update_by_natural_key(self) -> None:
        self.assertIs(self.write(observation()), WriteOutcome.WRITTEN)
        self.assertIs(self.write(observation()), WriteOutcome.UNCHANGED)
        self.assertIs(self.write(observation(80.0), now=LATER), WriteOutcome.UPDATED)
        value, details, updated_at, count = self.one(
            "SELECT value, details, updated_at, "
            "(SELECT COUNT(*) FROM observations) FROM observations"
        )
        self.assertEqual((value, details, updated_at, count), (80.0, "{}", LATER, 1))

    def test_different_sport_or_day_is_a_different_observation(self) -> None:
        self.write(observation())
        self.write(observation(observed_on=date(2026, 10, 2)))
        self.write(observation(sport=Sport.RUN))
        self.assertEqual(self.count("observations"), 3)


class MarkMissingDeletedTests(StoreFixture):
    def seed(self, source_id: str, local: date, *, provider: str = "intervals") -> None:
        record = activity(source_id)
        if provider != "intervals":
            record = replace(
                record,
                provenance=replace(record.provenance, provider=ProviderId.GARMIN),
            )
        canonical_store.upsert_activity_record(
            self.db,
            record,
            local_date=local,
            mapper_version=1,
            fetched_at=STAMP,
            now=STAMP,
        )
        canonical_store.upsert_provider_record(
            self.db,
            provider=provider,
            record_kind=ACTIVITY_RECORD_KIND,
            source_record_id=source_id,
            payload={"id": source_id},
            mapper_version=1,
            fetched_at=STAMP,
            now=STAMP,
        )

    def states(self) -> dict[str, tuple[str, str, str]]:
        rows = self.db.execute(
            "SELECT r.provider_activity_id, r.state, p.state, s.state "
            "FROM activity_records r "
            "JOIN provider_records p ON p.source_record_id = r.provider_activity_id "
            "JOIN activity_sessions s ON s.activity_id = r.activity_id"
        ).fetchall()
        return {row[0]: (row[1], row[2], row[3]) for row in rows}

    def test_missing_activity_inside_the_window_is_marked_deleted_everywhere(
        self,
    ) -> None:
        self.seed("kept", date(2026, 6, 2))
        self.seed("gone", date(2026, 6, 3))
        self.seed("outside", date(2026, 7, 1))
        deleted = canonical_store.mark_missing_deleted(
            self.db,
            "intervals",
            record_kind=ACTIVITY_RECORD_KIND,
            window_start=date(2026, 6, 1),
            window_end=date(2026, 6, 30),
            present_ids=frozenset({"kept"}),
            now=LATER,
        )
        self.assertEqual(deleted, 1)
        states = self.states()
        self.assertEqual(states["gone"], ("deleted", "deleted", "deleted"))
        self.assertEqual(states["kept"], ("active", "active", "active"))
        self.assertEqual(states["outside"], ("active", "active", "active"))

    def test_already_deleted_activities_are_not_counted_again(self) -> None:
        self.seed("gone", date(2026, 6, 3))

        def sweep() -> int:
            return canonical_store.mark_missing_deleted(
                self.db,
                "intervals",
                record_kind=ACTIVITY_RECORD_KIND,
                window_start=date(2026, 6, 1),
                window_end=date(2026, 6, 30),
                present_ids=frozenset(),
                now=LATER,
            )

        self.assertEqual(sweep(), 1)
        self.assertEqual(sweep(), 0)

    def test_other_providers_are_never_touched(self) -> None:
        self.seed("foreign", date(2026, 6, 3), provider="garmin")
        deleted = canonical_store.mark_missing_deleted(
            self.db,
            "intervals",
            record_kind=ACTIVITY_RECORD_KIND,
            window_start=date(2026, 6, 1),
            window_end=date(2026, 6, 30),
            present_ids=frozenset(),
            now=LATER,
        )
        self.assertEqual(deleted, 0)
        self.assertEqual(self.states()["foreign"], ("active", "active", "active"))


class MergedAliasDeletionTests(StoreFixture):
    """A duplicate alias session must be deletable without breaking its merge CHECK."""

    def seed(self, source_id: str, provider: ProviderId) -> str:
        record = activity(source_id)
        record = replace(
            record, provenance=replace(record.provenance, provider=provider)
        )
        canonical_store.upsert_activity_record(
            self.db,
            record,
            local_date=date(2026, 6, 3),
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
            self.one(
                "SELECT activity_id FROM activity_records "
                "WHERE provider = ? AND provider_activity_id = ?",
                (provider.value, source_id),
            )[0]
        )

    def merge_duplicate(self) -> tuple[str, str]:
        keep_id = self.seed("wahoo-1", ProviderId.WAHOO)
        dup_id = self.seed("garmin-1", ProviderId.INTERVALS)
        self.assertTrue(
            canonical_store.merge_activity_session(
                self.db, activity_id=dup_id, into=keep_id, now=STAMP
            )
        )
        self.assertEqual(
            self.one(
                "SELECT state, merged_into FROM activity_sessions WHERE activity_id = ?",
                (dup_id,),
            ),
            ("duplicate", keep_id),
        )
        return keep_id, dup_id

    def test_deleting_a_merged_alias_clears_its_merge_link(self) -> None:
        keep_id, dup_id = self.merge_duplicate()
        self.assertTrue(
            canonical_store.mark_activity_deleted(
                self.db,
                "intervals",
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id="garmin-1",
                now=LATER,
            )
        )
        self.assertEqual(
            self.one(
                "SELECT state, merged_into FROM activity_sessions WHERE activity_id = ?",
                (dup_id,),
            ),
            ("deleted", None),
        )
        self.assertEqual(
            self.one(
                "SELECT state FROM activity_records WHERE provider_activity_id = ?",
                ("garmin-1",),
            ),
            ("deleted",),
        )
        self.assertEqual(
            self.one(
                "SELECT state, merged_into FROM activity_sessions WHERE activity_id = ?",
                (keep_id,),
            ),
            ("active", None),
        )

    def test_missing_merged_alias_in_the_window_is_deleted_without_error(self) -> None:
        _, dup_id = self.merge_duplicate()
        deleted = canonical_store.mark_missing_deleted(
            self.db,
            "intervals",
            record_kind=ACTIVITY_RECORD_KIND,
            window_start=date(2026, 6, 1),
            window_end=date(2026, 6, 30),
            present_ids=frozenset(),
            now=LATER,
        )
        self.assertEqual(deleted, 1)
        self.assertEqual(
            self.one(
                "SELECT state, merged_into FROM activity_sessions WHERE activity_id = ?",
                (dup_id,),
            ),
            ("deleted", None),
        )


class FetchRowTests(unittest.TestCase):
    def test_tuple_rows_are_named_from_the_cursor_description(self) -> None:
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
        db.execute("INSERT INTO t VALUES (1, 'x')")
        self.assertEqual(
            canonical_store._fetch_row(db, "SELECT a, b FROM t", ()),
            {"a": 1, "b": "x"},
        )

    def test_empty_result_is_none(self) -> None:
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE t (a INTEGER)")
        self.assertIsNone(canonical_store._fetch_row(db, "SELECT a FROM t", ()))

    def test_fetch_all_returns_named_rows_for_tuples_mappings_and_nothing(self) -> None:
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE t (a INTEGER)")
        db.execute("INSERT INTO t VALUES (1)")
        self.assertEqual(
            canonical_store._fetch_all(db, "SELECT a FROM t", ()), [{"a": 1}]
        )
        self.assertEqual(
            canonical_store._fetch_all(db, "SELECT a FROM t WHERE 0", ()), []
        )
        self.assertEqual(
            canonical_store._fetch_all(_MappingDb([{"a": 1}]), "SELECT a", ()),
            [{"a": 1}],
        )

    def test_mapping_rows_are_copied_as_they_are(self) -> None:
        db = _MappingDb([{"a": 1}])
        self.assertEqual(canonical_store._fetch_row(db, "SELECT a", ()), {"a": 1})
        self.assertIsNone(canonical_store._fetch_row(_MappingDb([]), "SELECT a", ()))


class ActivityMetricStoreTests(StoreFixture):
    def test_summary_metrics_round_trip_and_zero_is_stored_as_null(self) -> None:
        record = replace(
            activity("wahoo-1", load=76.3),
            provenance=replace(
                provenance("wahoo-1", provider=ProviderId.WAHOO),
                recorded_by=RecordingOrigin.WAHOO,
            ),
            load_model=LoadModel.TSS,
            moving_duration_s=3600.4,
            elevation_gain_m=412.5,
            normalized_power=231.7,
            avg_cadence=88.4,
            energy_kj=1500.0,
        )
        canonical_store.upsert_activity_record(
            self.db,
            record,
            local_date=date(2026, 6, 1),
            mapper_version=2,
            fetched_at=STAMP,
            now=STAMP,
        )
        self.db.commit()

        rows = canonical_store.active_activity_rows(self.db)

        self.assertEqual(1, len(rows))
        self.assertEqual(
            (3600.4, 412.5, 231.7, 88.4, 1500.0),
            tuple(
                rows[0][column]
                for column in (
                    "moving_duration_s",
                    "elevation_gain_m",
                    "normalized_power",
                    "avg_cadence",
                    "energy_kj",
                )
            ),
        )
        self.assertEqual("tss", rows[0]["load_model"])
        self.assertEqual(76.3, rows[0]["load"])

    def test_absent_metrics_are_stored_as_null_and_round_trip_as_none(self) -> None:
        canonical_store.upsert_activity_record(
            self.db,
            activity("plain-1"),
            local_date=date(2026, 6, 1),
            mapper_version=1,
            fetched_at=STAMP,
            now=STAMP,
        )
        self.db.commit()

        rows = canonical_store.active_activity_rows(self.db)

        self.assertEqual(1, len(rows))
        for column in (
            "moving_duration_s",
            "elevation_gain_m",
            "normalized_power",
            "avg_cadence",
            "energy_kj",
        ):
            with self.subTest(column=column):
                self.assertIsNone(rows[0][column])

    def test_elapsed_duration_is_kept_in_the_details_and_round_trips(self) -> None:
        def write(record: ActivityRecord) -> WriteOutcome:
            return canonical_store.upsert_activity_record(
                self.db,
                record,
                local_date=date(2026, 6, 1),
                mapper_version=2,
                fetched_at=STAMP,
                now=STAMP,
            )

        record = replace(activity("walk-1"), elapsed_duration_s=4520.0)
        self.assertIs(WriteOutcome.WRITTEN, write(record))
        self.assertIs(WriteOutcome.UNCHANGED, write(record))
        details = self.one("SELECT details FROM activity_records")[0]
        self.assertEqual('{"elapsed_duration_s":4520.0}', details)
        row = canonical_store.active_activity_rows(self.db)[0]
        self.assertEqual(
            4520.0, canonical_store.activity_elapsed_duration(row["details"])
        )

        self.assertIs(
            WriteOutcome.UPDATED, write(replace(record, elapsed_duration_s=None))
        )
        self.assertEqual(
            canonical_store.ACTIVITY_DETAILS,
            self.one("SELECT details FROM activity_records")[0],
        )

    def test_max_hr_is_kept_in_the_details_beside_elapsed_duration(self) -> None:
        def write(record: ActivityRecord) -> WriteOutcome:
            return canonical_store.upsert_activity_record(
                self.db,
                record,
                local_date=date(2026, 6, 1),
                mapper_version=3,
                fetched_at=STAMP,
                now=STAMP,
            )

        record = replace(activity("walk-1"), max_hr=171.0)
        self.assertIs(WriteOutcome.WRITTEN, write(record))
        self.assertEqual(
            '{"max_hr":171.0}', self.one("SELECT details FROM activity_records")[0]
        )

        both = replace(record, elapsed_duration_s=4520.0)
        self.assertIs(WriteOutcome.UPDATED, write(both))
        self.assertIs(WriteOutcome.UNCHANGED, write(both))
        details = self.one("SELECT details FROM activity_records")[0]
        self.assertEqual('{"elapsed_duration_s":4520.0,"max_hr":171.0}', details)
        row = canonical_store.active_activity_rows(self.db)[0]
        self.assertEqual(171.0, canonical_store.activity_max_hr(row["details"]))
        self.assertEqual(
            4520.0, canonical_store.activity_elapsed_duration(row["details"])
        )

    def test_unreadable_details_have_no_max_hr(self) -> None:
        for details in (None, "{", "[]", "{}", '{"max_hr":"171"}', '{"max_hr":true}'):
            with self.subTest(details=details):
                self.assertIsNone(canonical_store.activity_max_hr(details))

    def test_unreadable_details_have_no_elapsed_duration(self) -> None:
        for details in (
            None,
            "",
            "{",
            "[]",
            "{}",
            '{"elapsed_duration_s":"4520"}',
            '{"elapsed_duration_s":true}',
            "[" * 100_000,
        ):
            with self.subTest(details=details[:20] if details else details):
                self.assertIsNone(canonical_store.activity_elapsed_duration(details))
        self.assertEqual(
            61.0, canonical_store.activity_elapsed_duration('{"elapsed_duration_s":61}')
        )

    def test_extremes_and_device_type_round_trip_through_the_details(self) -> None:
        def write(record: ActivityRecord) -> WriteOutcome:
            return canonical_store.upsert_activity_record(
                self.db,
                record,
                local_date=date(2026, 6, 1),
                mapper_version=5,
                fetched_at=STAMP,
                now=STAMP,
            )

        record = replace(
            activity("walk-1"),
            max_speed_mps=7.5,
            max_power_w=1100.0,
            min_hr=52.0,
            elevation_high_m=812.0,
            elevation_low_m=-3.0,
            steps=12000.0,
            device_type=DeviceType.WATCH,
        )
        self.assertIs(WriteOutcome.WRITTEN, write(record))
        self.assertIs(WriteOutcome.UNCHANGED, write(record))
        details = self.one("SELECT details FROM activity_records")[0]
        self.assertEqual(
            {
                "device_type",
                "elevation_high_m",
                "elevation_low_m",
                "max_power_w",
                "max_speed_mps",
                "min_hr",
                "steps",
            },
            set(json.loads(details)),
        )
        row = canonical_store.active_activity_rows(self.db)[0]
        details = row["details"]
        self.assertEqual(7.5, canonical_store.activity_max_speed(details))
        self.assertEqual(1100.0, canonical_store.activity_max_power(details))
        self.assertEqual(52.0, canonical_store.activity_min_hr(details))
        self.assertEqual(812.0, canonical_store.activity_elevation_high(details))
        self.assertEqual(-3.0, canonical_store.activity_elevation_low(details))
        self.assertEqual(12000.0, canonical_store.activity_steps(details))
        self.assertIs(DeviceType.WATCH, canonical_store.activity_device_type(details))

        self.assertIs(WriteOutcome.UPDATED, write(activity("walk-1")))
        self.assertEqual(
            canonical_store.ACTIVITY_DETAILS,
            self.one("SELECT details FROM activity_records")[0],
        )

    def test_unreadable_extremes_and_device_type_are_none(self) -> None:
        for details in (
            None,
            "{",
            '{"device_type":"tablet"}',
            '{"device_type":5}',
            '{"max_speed_mps":"7"}',
            '{"steps":true}',
        ):
            with self.subTest(details=details):
                self.assertIsNone(canonical_store.activity_device_type(details))
                self.assertIsNone(canonical_store.activity_max_speed(details))
                self.assertIsNone(canonical_store.activity_steps(details))


if __name__ == "__main__":
    unittest.main()
