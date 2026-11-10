"""The daily schedule follows the refresh history's retry time."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db.manager import DatabaseManager
from backend.sync.retry_hold import ProviderRetryHold

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
TOKENS = "garmin_oauth_tokens"


class ProviderRetryHoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = DatabaseManager(
            Path(self.directory.name) / "hold.sqlite",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            db.executescript(
                """
                CREATE TABLE provider_refresh_history (
                    id TEXT PRIMARY KEY, provider TEXT, area TEXT, operation_id TEXT,
                    trigger TEXT, started_at TEXT, finished_at TEXT, phase TEXT,
                    status TEXT, error_code TEXT, next_retry_at TEXT
                );
                CREATE TABLE kv (
                    key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL
                );
                """
            )
        self.hold = ProviderRetryHold(
            lambda: self.manager,
            lambda: NOW,
            credential_keys={"garmin": (TOKENS,)},
        )
        self.counter = 0

    def record(
        self,
        status: str,
        *,
        minutes_ago: int = 30,
        error_code: str | None = None,
        retry_in_minutes: int | None = None,
        provider: str = "garmin",
        area: str = "data",
    ) -> None:
        self.counter += 1
        started = NOW - timedelta(minutes=minutes_ago)
        retry = (
            None
            if retry_in_minutes is None
            else (NOW + timedelta(minutes=retry_in_minutes)).isoformat()
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO provider_refresh_history(id, provider, area, started_at, "
                "finished_at, phase, status, error_code, next_retry_at) "
                "VALUES (?, ?, ?, ?, ?, 'complete', ?, ?, ?)",
                (
                    f"row-{self.counter}",
                    provider,
                    area,
                    started.isoformat(),
                    (started + timedelta(minutes=1)).isoformat(),
                    status,
                    error_code,
                    retry,
                ),
            )

    def store_credentials(self, minutes_ago: int) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT OR REPLACE INTO kv(key, value, updated_at) VALUES (?, 'x', ?)",
                (TOKENS, (NOW - timedelta(minutes=minutes_ago)).isoformat()),
            )

    def test_no_history_never_holds(self) -> None:
        self.assertFalse(self.hold.held("garmin"))
        self.assertFalse(self.hold.held("unknown-provider"))

    def test_a_failed_refresh_holds_until_its_next_retry_time(self) -> None:
        self.record("error", error_code="provider_error", retry_in_minutes=45)

        self.assertTrue(self.hold.held("garmin"))

    def test_a_retry_time_in_the_past_releases_the_hold(self) -> None:
        self.record("error", error_code="provider_error", retry_in_minutes=-5)

        self.assertFalse(self.hold.held("garmin"))

    def test_a_later_success_releases_the_hold(self) -> None:
        self.record(
            "error", minutes_ago=60, error_code="provider_error", retry_in_minutes=30
        )
        self.record("success", minutes_ago=10)

        self.assertFalse(self.hold.held("garmin"))

    def test_a_skipped_attempt_never_holds(self) -> None:
        self.record("skipped")

        self.assertFalse(self.hold.held("garmin"))

    def test_a_skipped_attempt_does_not_release_an_earlier_failure_hold(self) -> None:
        self.record(
            "error", minutes_ago=60, error_code="provider_error", retry_in_minutes=30
        )
        self.record("skipped", minutes_ago=10)

        self.assertTrue(self.hold.held("garmin"))

    def test_auth_required_holds_until_the_athlete_acts(self) -> None:
        self.record("error", error_code="auth_required")

        self.assertTrue(self.hold.held("garmin"))

    def test_a_newer_attempt_after_auth_required_ends_the_hold(self) -> None:
        self.record("error", minutes_ago=90, error_code="auth_required")
        self.record("success", minutes_ago=5)

        self.assertFalse(self.hold.held("garmin"))

    def test_changed_credentials_release_an_auth_required_hold(self) -> None:
        self.record("error", minutes_ago=30, error_code="auth_required")
        self.store_credentials(minutes_ago=10)

        self.assertFalse(self.hold.held("garmin"))

    def test_credentials_older_than_the_failure_keep_the_hold(self) -> None:
        self.record("error", minutes_ago=30, error_code="auth_required")
        self.store_credentials(minutes_ago=120)

        self.assertTrue(self.hold.held("garmin"))

    def test_a_configuration_error_without_retry_does_not_hold(self) -> None:
        self.record("error", error_code="invalid_configuration")

        self.assertFalse(self.hold.held("garmin"))

    def test_a_provider_is_held_only_by_its_own_history(self) -> None:
        self.record(
            "error", error_code="auth_required", provider="wahoo", area="activities"
        )

        self.assertFalse(self.hold.held("garmin"))
        self.assertTrue(self.hold.held("wahoo"))


if __name__ == "__main__":
    unittest.main()
