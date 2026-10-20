"""Session-scoped activity reads: the active records bundled in one canonical session."""

import sqlite3
import unittest

from backend.canonical.vocabulary import ProviderId
from backend.db import row_factory
from backend.db.canonical_store import session_activity_rows
from backend.db.schema import initialize_schema
from backend.sync.canonical_table_reader import CanonicalTableReader

EARLY = "2026-10-18T07:00:00+00:00"
STAMP = "2026-10-18T08:00:00+00:00"
LATE = "2026-10-18T09:00:00+00:00"


class SessionActivityReadTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.db.execute("PRAGMA foreign_keys = ON")

    def add_session(self, activity_id, state="active", merged_into=None):
        self.db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, state, merged_into, started_at, "
            "created_at, updated_at) VALUES (?, 'intervals', ?, ?, ?, ?, ?, ?)",
            (activity_id, activity_id, state, merged_into, STAMP, STAMP, STAMP),
        )

    def add_record(
        self, provider, provider_activity_id, activity_id, state="active", started=STAMP
    ):
        self.db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
            "state, mapper_version, source_kind, recorded_by, sport, environment, "
            "started_at, load_model, fetched_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, 'provider_reported', 'garmin', 'ride', 'outdoor', "
            "?, 'unknown', ?, ?, ?)",
            (
                provider.value,
                provider_activity_id,
                activity_id,
                state,
                started,
                STAMP,
                STAMP,
                STAMP,
            ),
        )

    def ids(self, rows):
        return [row["provider_activity_id"] for row in rows]

    def test_session_rows_include_merged_duplicates_in_activity_order(self):
        self.add_session("act_1")
        self.add_session("act_2", "duplicate", merged_into="act_1")
        self.add_record(ProviderId.INTERVALS, "i1", "act_1", started=STAMP)
        self.add_record(ProviderId.GARMIN, "g1", "act_2", started=LATE)
        self.add_record(ProviderId.WAHOO, "w1", "act_1", started=EARLY)

        rows = session_activity_rows(self.db, "act_1")

        self.assertEqual(["w1", "i1", "g1"], self.ids(rows))

    def test_invalid_and_deleted_records_are_not_returned(self):
        self.add_session("act_1")
        self.add_record(ProviderId.INTERVALS, "i1", "act_1")
        self.add_record(ProviderId.GARMIN, "g1", "act_1", state="invalid")
        self.add_record(ProviderId.WAHOO, "w1", "act_1", state="deleted")

        self.assertEqual(["i1"], self.ids(session_activity_rows(self.db, "act_1")))

    def test_a_deleted_session_returns_nothing(self):
        self.add_session("act_1", "deleted")
        self.add_record(ProviderId.INTERVALS, "i1", "act_1")

        self.assertEqual([], session_activity_rows(self.db, "act_1"))

    def test_duplicates_of_a_deleted_session_return_nothing(self):
        self.add_session("act_1", "deleted")
        self.add_session("act_2", "duplicate", merged_into="act_1")
        self.add_record(ProviderId.GARMIN, "g1", "act_2")

        self.assertEqual([], session_activity_rows(self.db, "act_1"))

    def test_unknown_session_returns_nothing(self):
        self.assertEqual([], session_activity_rows(self.db, "act_missing"))

    def test_reader_maps_the_session_records_in_activity_order(self):
        self.add_session("act_1")
        self.add_session("act_2", "duplicate", merged_into="act_1")
        self.add_record(ProviderId.INTERVALS, "i1", "act_1", started=STAMP)
        self.add_record(ProviderId.GARMIN, "g1", "act_2", started=LATE)

        records = CanonicalTableReader().session_activities(self.db, "act_1")

        self.assertEqual(("i1", "g1"), tuple(r.activity_id for r in records))
        self.assertEqual(
            (ProviderId.INTERVALS, ProviderId.GARMIN),
            tuple(r.provenance.provider for r in records),
        )

    def test_reader_returns_nothing_for_a_deleted_session(self):
        self.add_session("act_1", "deleted")
        self.add_record(ProviderId.INTERVALS, "i1", "act_1")

        self.assertEqual(
            (), CanonicalTableReader().session_activities(self.db, "act_1")
        )


if __name__ == "__main__":
    unittest.main()
