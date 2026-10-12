"""Canonical persistence: write outcomes, natural keys, deletion marks and row fetching.

Each test uses a temporary SQLite file with the schema initialized. No provider
account, network, real data directory or encryption key is involved.
"""

from __future__ import annotations

import hashlib
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
            SourceKind.PROVIDER_REPORTED if provider is not None else SourceKind.ATHLETE_ENTERED
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
) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value=value, unit="kg"),
        observed_on=observed_on,
        observed_at=observed_at,
        provenance=provenance(None, provider=provider),
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
        self.assertIs(self.write({"name": "Long ride"}, now=LATER), WriteOutcome.UPDATED)
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
        self.assertEqual((link, confirmed, state, local), ("single", 0, "active", "2026-06-01"))
        record_session = self.one("SELECT activity_id, state, load FROM activity_records")
        self.assertEqual(record_session, (session_id, "active", 50.0))

    def test_identical_activity_is_unchanged(self) -> None:
        self.write(activity())
        self.assertIs(self.write(activity()), WriteOutcome.UNCHANGED)
        self.assertEqual(self.count("activity_sessions"), 1)

    def test_changed_activity_keeps_its_id_and_is_updated(self) -> None:
        self.write(activity())
        original_id = self.one("SELECT activity_id FROM activity_records")[0]
        outcome = self.write(activity(name="Renamed", load=None), local=date(2026, 6, 2))
        self.assertIs(outcome, WriteOutcome.UPDATED)
        name, load, load_model = self.one(
            "SELECT name, load, load_model FROM activity_records"
        )
        self.assertEqual((name, load, load_model), ("Renamed", None, "intervals_training_load"))
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
        by_day = observation()
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
            record = replace(record, provenance=replace(record.provenance, provider=ProviderId.GARMIN))
        canonical_store.upsert_activity_record(
            self.db, record, local_date=local, mapper_version=1, fetched_at=STAMP, now=STAMP
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

    def test_missing_activity_inside_the_window_is_marked_deleted_everywhere(self) -> None:
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
        self.assertEqual(canonical_store._fetch_all(db, "SELECT a FROM t", ()), [{"a": 1}])
        self.assertEqual(canonical_store._fetch_all(db, "SELECT a FROM t WHERE 0", ()), [])
        self.assertEqual(
            canonical_store._fetch_all(_MappingDb([{"a": 1}]), "SELECT a", ()),
            [{"a": 1}],
        )

    def test_mapping_rows_are_copied_as_they_are(self) -> None:
        db = _MappingDb([{"a": 1}])
        self.assertEqual(canonical_store._fetch_row(db, "SELECT a", ()), {"a": 1})
        self.assertIsNone(canonical_store._fetch_row(_MappingDb([]), "SELECT a", ()))


if __name__ == "__main__":
    unittest.main()
