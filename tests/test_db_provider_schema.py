"""Schema version 6 canonical provider tables: lifecycle CHECKs, keys and indexes.

Open vocabularies (provider, sport, metric, unit, source kind, ...) and numeric
ranges are validated in Python by backend.canonical, so the database keeps them
open. The tests below pin the closed lifecycle enums and the structural rules.
"""

import re
import sqlite3
import unittest

from backend.canonical.vocabulary import (
    ActivityDetailKind,
    ActivityDetailOrigin,
    ActivityLinkKind,
    ActivityRecordState,
    ActivitySessionState,
    ProviderRecordState,
)
from backend.db.schema import (
    ACTIVITY_DETAIL_DDL,
    CURRENT_DATABASE_INDEXES,
    CURRENT_SCHEMA_VERSION,
    PROVIDER_TABLES_DDL,
    database_schema_is_current,
    initialize_schema,
)

STAMP = "2026-10-01T08:00:00+00:00"
PROVIDER = "test-provider"
PROVIDER_INDEXES = {
    "idx_activity_records_activity",
    "idx_activity_records_local_date",
    "idx_activity_records_started",
    "idx_activity_sessions_local_date",
    "idx_activity_sessions_merged_into",
    "idx_observations_metric_date",
    "idx_provider_records_reprojection",
}
PROVIDER_TABLES = (
    "provider_records",
    "activity_sessions",
    "activity_records",
    "observations",
)


def valid_observation(**overrides):
    row = {
        "natural_key": "observation-1",
        "metric": "weight",
        "value": 72.5,
        "unit": "kg",
        "source_kind": "provider_reported",
        "recorded_by": "manual",
        "provider": PROVIDER,
        "observed_on": "2026-10-01",
        "mapper_version": 1,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    row.update(overrides)
    return row


def valid_activity(**overrides):
    row = {
        "provider": PROVIDER,
        "provider_activity_id": "activity-1",
        "source_kind": "provider_reported",
        "recorded_by": "manual",
        "mapper_version": 1,
        "sport": "ride",
        "environment": "outdoor",
        "started_at": STAMP,
        "load_model": "unknown",
        "fetched_at": STAMP,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    row.update(overrides)
    return row


def valid_session(**overrides):
    row = {
        "activity_id": "act_1",
        "primary_provider": PROVIDER,
        "primary_provider_activity_id": "activity-1",
        "started_at": STAMP,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    row.update(overrides)
    return row


def valid_provider_record(**overrides):
    row = {
        "provider": PROVIDER,
        "record_kind": "activity",
        "source_record_id": "record-1",
        "payload": '{"name":"Synthetic"}',
        "payload_hash": "a" * 64,
        "fetched_at": STAMP,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    row.update(overrides)
    return row


class ProviderSchemaTests(unittest.TestCase):
    def fresh(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        db.execute("PRAGMA foreign_keys = ON")
        initialize_schema(db)
        return db

    def insert(self, db, table, row):
        columns = ",".join(row)
        placeholders = ",".join("?" for _ in row)
        db.execute(
            f"INSERT INTO {table}({columns}) VALUES ({placeholders})",
            tuple(row.values()),
        )

    def count(self, db, table):
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_fresh_database_is_current_schema_with_empty_provider_tables(self):
        db = self.fresh()
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(CURRENT_SCHEMA_VERSION, 16)
        self.assertTrue(database_schema_is_current(db))
        for table in PROVIDER_TABLES:
            with self.subTest(table=table):
                self.assertEqual(self.count(db, table), 0)
        present = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        self.assertLessEqual(PROVIDER_INDEXES, present)
        self.assertLessEqual(PROVIDER_INDEXES, CURRENT_DATABASE_INDEXES)

    def test_provider_ddl_names_no_provider_identifier(self):
        self.assertNotIn("'intervals'", PROVIDER_TABLES_DDL)
        self.assertNotIn("'garmin'", PROVIDER_TABLES_DDL)

    def test_closed_lifecycle_checks_mirror_the_vocabulary_enums(self):
        lists = {
            (match.group(1), frozenset(re.findall(r"'([^']*)'", match.group(2))))
            for match in re.finditer(r"(\w+) IN \(('[^)]*')\)", PROVIDER_TABLES_DDL)
        }
        expected = {
            (
                "state",
                frozenset(member.value for member in ProviderRecordState),
            ),
            (
                "state",
                frozenset(member.value for member in ActivityRecordState),
            ),
            (
                "state",
                frozenset(member.value for member in ActivitySessionState),
            ),
            (
                "link_kind",
                frozenset(member.value for member in ActivityLinkKind),
            ),
        }
        self.assertEqual(lists, expected)

    def test_activity_detail_checks_mirror_the_closed_detail_enums(self):
        self.assertNotIn("'intervals'", ACTIVITY_DETAIL_DDL)
        self.assertNotIn("'garmin'", ACTIVITY_DETAIL_DDL)
        lists = {
            (match.group(1), frozenset(re.findall(r"'([^']*)'", match.group(2))))
            for match in re.finditer(r"(\w+) IN \(('[^)]*')\)", ACTIVITY_DETAIL_DDL)
        }
        zone_kinds = frozenset(
            (ActivityDetailKind.HEART_RATE_ZONES, ActivityDetailKind.POWER_ZONES)
        )
        self.assertEqual(
            lists,
            {
                (
                    "detail_kind",
                    frozenset(member.value for member in ActivityDetailKind),
                ),
                ("origin", frozenset(member.value for member in ActivityDetailOrigin)),
                ("detail_kind", frozenset(member.value for member in zone_kinds)),
            },
        )

    def test_no_open_vocabulary_or_range_checks_remain_in_sql(self):
        for fragment in ("sport IN", "metric IN", "recorded_by IN", "source_kind IN"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, PROVIDER_TABLES_DDL)
        self.assertNotIn("CASE", PROVIDER_TABLES_DDL)

    def test_open_vocabularies_are_accepted_by_the_database(self):
        db = self.fresh()
        self.insert(
            db,
            "observations",
            valid_observation(
                metric="a_future_metric",
                unit="furlong",
                source_kind="future_source",
                recorded_by="carrier_pigeon",
                sport="a_future_sport",
            ),
        )
        self.insert(
            db,
            "activity_records",
            valid_activity(
                sport="a_future_sport",
                environment="moon",
                load_model="a_future_model",
                source_kind="future_source",
                recorded_by="carrier_pigeon",
                avg_hr=None,
                duration_s=None,
            ),
        )
        self.insert(
            db,
            "activity_records",
            valid_activity(
                provider_activity_id="activity-2",
                duration_s=-1.0,
                distance_m=9_999_999.0,
                avg_hr=999.0,
            ),
        )
        self.assertEqual(self.count(db, "observations"), 1)
        self.assertEqual(self.count(db, "activity_records"), 2)

    def test_provider_records_require_object_payload_state_and_unique_source(self):
        invalid = (
            {"payload": "not json"},
            {"payload": "[]"},
            {"state": "invalid"},
            {"payload_hash": "a" * 63},
            {"record_kind": ""},
            {"source_record_id": "x" * 257},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                db = self.fresh()
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert(
                        db, "provider_records", valid_provider_record(**overrides)
                    )

        db = self.fresh()
        self.insert(db, "provider_records", valid_provider_record())
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(db, "provider_records", valid_provider_record())
        self.insert(
            db,
            "provider_records",
            valid_provider_record(source_record_id="record-2"),
        )
        state = db.execute(
            "SELECT state FROM provider_records WHERE source_record_id='record-2'"
        ).fetchone()[0]
        self.assertEqual(state, ProviderRecordState.ACTIVE.value)

    def test_identifier_length_guards_reject_empty_and_overlong_text(self):
        invalid = (
            ("observations", valid_observation(natural_key="")),
            ("observations", valid_observation(natural_key="n" * 513)),
            ("observations", valid_observation(metric="")),
            ("observations", valid_observation(unit="u" * 17)),
            ("observations", valid_observation(provider="")),
            ("activity_records", valid_activity(provider_activity_id="")),
            ("activity_records", valid_activity(provider_activity_id="p" * 257)),
            ("activity_records", valid_activity(source_kind="")),
        )
        for table, row in invalid:
            with self.subTest(table=table, row=row):
                db = self.fresh()
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert(db, table, row)

    def test_json_detail_columns_must_be_objects(self):
        for table, row in (
            ("observations", valid_observation(details="[]")),
            ("observations", valid_observation(details="not json")),
            ("activity_records", valid_activity(details="3")),
        ):
            with self.subTest(table=table, row=row):
                db = self.fresh()
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert(db, table, row)

        db = self.fresh()
        self.insert(db, "observations", valid_observation())
        self.insert(db, "activity_records", valid_activity())
        self.assertEqual(
            db.execute("SELECT details FROM observations").fetchone()[0], "{}"
        )
        self.assertEqual(
            db.execute("SELECT details FROM activity_records").fetchone()[0], "{}"
        )

    def test_observation_natural_key_is_unique(self):
        db = self.fresh()
        self.insert(db, "observations", valid_observation())
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(db, "observations", valid_observation())
        self.insert(db, "observations", valid_observation(natural_key="observation-2"))
        self.assertEqual(self.count(db, "observations"), 2)

    def test_activity_session_lifecycle_and_link_kind_are_closed(self):
        invalid = (
            {"link_kind": "guessed"},
            {"athlete_confirmed": 2},
            {"state": "merged"},
            {"state": "tombstoned"},
            {"state": "duplicate", "merged_into": None},
            {"state": "active", "merged_into": "act_0"},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                db = self.fresh()
                self.insert(db, "activity_sessions", valid_session(activity_id="act_0"))
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert(db, "activity_sessions", valid_session(**overrides))

        db = self.fresh()
        self.insert(db, "activity_sessions", valid_session(activity_id="act_0"))
        self.insert(
            db,
            "activity_sessions",
            valid_session(
                activity_id="act_1",
                primary_provider_activity_id="activity-2",
                state=ActivitySessionState.DUPLICATE.value,
                merged_into="act_0",
            ),
        )
        self.assertEqual(self.count(db, "activity_sessions"), 2)

    def test_activity_session_primary_is_not_unique_and_merge_target_is_checked(self):
        # The primary pointer can move between sessions by precedence, so no UNIQUE
        # applies to it; the record PK plus activity_id is the identity.
        db = self.fresh()
        self.insert(db, "activity_sessions", valid_session())
        self.insert(db, "activity_sessions", valid_session(activity_id="act_2"))
        self.assertEqual(self.count(db, "activity_sessions"), 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(
                db,
                "activity_sessions",
                valid_session(
                    activity_id="act_3",
                    primary_provider_activity_id="activity-3",
                    state=ActivitySessionState.DUPLICATE.value,
                    merged_into="act_missing",
                ),
            )

    def test_activity_session_id_must_use_the_act_prefix(self):
        for activity_id in ("session-1", "act_", "ac_1"):
            with self.subTest(activity_id=activity_id):
                db = self.fresh()
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert(
                        db, "activity_sessions", valid_session(activity_id=activity_id)
                    )

    def test_activity_records_reference_sessions_when_linked(self):
        db = self.fresh()
        self.insert(db, "activity_sessions", valid_session())
        self.insert(db, "activity_records", valid_activity(activity_id="act_1"))
        self.insert(db, "activity_records", valid_activity(provider_activity_id="a-2"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(
                db,
                "activity_records",
                valid_activity(provider_activity_id="a-3", activity_id="act_missing"),
            )
        linked = db.execute(
            "SELECT COUNT(*) FROM activity_records WHERE activity_id IS NULL"
        ).fetchone()[0]
        self.assertEqual(linked, 1)

    def test_activity_record_primary_key_is_provider_scoped(self):
        db = self.fresh()
        self.insert(db, "activity_records", valid_activity())
        self.insert(
            db,
            "activity_records",
            valid_activity(provider="another-provider"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(db, "activity_records", valid_activity())

    def test_activity_record_lifecycle_accepts_only_closed_states(self):
        db = self.fresh()
        self.insert(
            db,
            "activity_records",
            valid_activity(state=ActivityRecordState.DELETED.value),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(
                db,
                "activity_records",
                valid_activity(provider_activity_id="a-2", state="tombstoned"),
            )

    def test_provider_record_lifecycle_accepts_only_active_or_deleted(self):
        db = self.fresh()
        self.insert(db, "provider_records", valid_provider_record(state="deleted"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(
                db,
                "provider_records",
                valid_provider_record(source_record_id="record-2", state="invalid"),
            )

    def test_typed_activity_columns_are_nullable_reals_never_defaulted(self):
        typed = (
            "moving_duration_s",
            "elevation_gain_m",
            "intensity_pct",
            "max_hr",
            "normalized_power",
            "avg_cadence",
            "energy_kj",
        )
        db = self.fresh()
        self.insert(db, "activity_records", valid_activity())
        self.insert(
            db,
            "activity_records",
            valid_activity(provider_activity_id="a-2", **{name: 0.0 for name in typed}),
        )
        columns = {
            row[1]: row for row in db.execute("PRAGMA table_info(activity_records)")
        }
        for name in typed:
            with self.subTest(column=name):
                self.assertEqual(columns[name][2], "REAL")
                self.assertEqual(columns[name][3], 0)
                self.assertIsNone(columns[name][4])
        columns_sql = ", ".join(typed)
        missing = db.execute(
            f"SELECT {columns_sql} FROM activity_records WHERE provider_activity_id = 'activity-1'"
        ).fetchone()
        self.assertEqual(tuple(missing), (None,) * len(typed))
        zeros = db.execute(
            f"SELECT {columns_sql} FROM activity_records WHERE provider_activity_id = 'a-2'"
        ).fetchone()
        self.assertEqual(tuple(zeros), (0.0,) * len(typed))


if __name__ == "__main__":
    unittest.main()
