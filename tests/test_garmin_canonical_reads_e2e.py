"""Garmin readers on an encrypted database: tables serve the same JSON as the snapshot.

Populates a temporary SQLCipher database through the real backfill ingest of a
populated Intervals.icu and Garmin snapshot, completes the backfill, removes the
canonical sections from the stored Garmin snapshot, and compares the migrated
services with the legacy run. All storage is temporary.
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

import test_garmin_canonical_reads as garmin_reads
from canonical_read_support import populate

from backend.coach.morning import GarminSleepObservations
from backend.db import DatabaseManager, row_factory
from backend.db.schema import configure_cipher, initialize_schema
from backend.performance.garmin_canonical import read_garmin_sleep_day

try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None

PUBLIC_KEYS = ("has_sleep", "has_hrv", "has_resting_hr", "has_readiness", "has_weight")


@unittest.skipIf(
    cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
)
class GarminCanonicalEncryptedEndToEndTests(garmin_reads.GarminReadFixture):
    def setUp(self) -> None:
        super().setUp()
        self.manager = DatabaseManager(
            Path(self.temporary.name) / "encrypted.db",
            cipher_backend,
            password="synthetic-e2e-test-key",
            configure=configure_cipher,
            row_factory=row_factory,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)

    def test_services_are_unchanged_once_tables_serve_the_encrypted_database(
        self,
    ) -> None:
        populate(self)
        legacy_state = self._projection_service().public_state()
        legacy_context = self._projection_service().coach_context(
            include_performance=True
        )

        self._strip_canonical_sections()
        migrated = self._projection_service()

        state = migrated.public_state()
        self.assertEqual(
            json.dumps(state, sort_keys=True),
            json.dumps(legacy_state, sort_keys=True),
        )
        self.assertEqual(
            migrated.coach_context(include_performance=True)["performance"],
            legacy_context["performance"],
        )
        self.assertTrue(all(state[key] for key in PUBLIC_KEYS))

    def test_sleep_day_comes_from_the_encrypted_tables(self) -> None:
        populate(self)
        observations = GarminSleepObservations(self.manager, lambda: self.table)

        with observations.database_manager.reader() as db:
            day = read_garmin_sleep_day(observations.reader(), db)

        self.assertIsInstance(day, date)


if __name__ == "__main__":
    unittest.main()
