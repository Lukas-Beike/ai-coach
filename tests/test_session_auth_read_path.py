from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from backend.config import Config
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.errors import AppError, DatabaseBusyError
from backend.http_api import auth as http_auth
from backend.http_api.auth import SESSION_COOKIE, SessionAuthService
from backend.http_api.rate_limit import RateLimiter

CONFIG = Config(
    port=8090,
    openai_api_key="",
    openai_base_url="",
    openai_model="gpt-6-luna",
    intervals_api_key="",
    intervals_athlete_id="",
    garmin_email="",
    garmin_password="",
    garmin_tokenstore="",
    garmin_fixture_path="",
    calendar_ical_url="",
    app_password="synthetic-password",
    secure_cookies=False,
    data_retention_days=30,
)


def handler_for(token: str = "", csrf: str = "") -> SimpleNamespace:
    headers = {"Cookie": f"{SESSION_COOKIE}={token}"} if token else {}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return SimpleNamespace(headers=headers, client_address=("127.0.0.1", 1))


class SessionAuthReadPathTests(unittest.TestCase):
    def setUp(self) -> None:
        root = self.enterContext(tempfile.TemporaryDirectory())
        self.manager = DatabaseManager(
            Path(root) / "sessions.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            db.execute("PRAGMA journal_mode=WAL")
            initialize_schema(db)
        self.database_lock = threading.RLock()
        self.auth = SessionAuthService(
            self.manager, self.database_lock, CONFIG, True, RateLimiter()
        )
        # Cleanup is covered separately; keep it off the other assertions.
        self.auth._last_cleanup_monotonic = time.monotonic()

    def add_session(
        self,
        name: str,
        *,
        expires_in: float = 3600,
        last_seen_age: float = 0,
    ) -> tuple[str, str]:
        token, csrf = f"session-{name}", f"csrf-{name}"
        seen = (datetime.now(UTC) - timedelta(seconds=last_seen_age)).isoformat()
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    self.auth.session_token_hash(token),
                    self.auth.session_token_hash(csrf),
                    time.time() + expires_in,
                    seen,
                    seen,
                ),
            )
        return token, csrf

    def stored(self, token: str):
        with self.manager.reader() as db:
            return db.execute(
                "SELECT last_seen FROM sessions WHERE token_hash=?",
                (self.auth.session_token_hash(token),),
            ).fetchone()

    def hold_writer(self):
        """Hold the database writer until the returned event is set."""
        holding, release = threading.Event(), threading.Event()

        def hold() -> None:
            with self.manager.unit_of_work() as db:
                db.execute("UPDATE sessions SET last_seen=last_seen")
                holding.set()
                release.wait(10)

        thread = threading.Thread(target=hold)
        thread.start()
        self.assertTrue(holding.wait(5))

        def stop() -> None:
            release.set()
            thread.join(5)

        self.addCleanup(stop)
        return stop

    def run_blocking(self, call):
        """Run ``call`` on a thread so a stalled lookup fails instead of hanging."""
        result: list[object] = []
        thread = threading.Thread(target=lambda: result.append(call()))
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive(), "session lookup waited for the writer")
        return result[0]

    def test_valid_session_authenticates_without_the_writer(self) -> None:
        token, csrf = self.add_session("fresh")
        self.hold_writer()
        session = self.run_blocking(
            lambda: self.auth.authenticated_session(handler_for(token))
        )
        self.assertEqual(
            session["csrf_hash"],
            self.auth.session_token_hash(csrf),  # type: ignore[index]
        )

    def test_missing_or_unknown_token_is_rejected_without_the_writer(self) -> None:
        self.hold_writer()
        self.assertIsNone(
            self.run_blocking(lambda: self.auth.authenticated_session(handler_for()))
        )
        self.assertIsNone(
            self.run_blocking(
                lambda: self.auth.authenticated_session(handler_for("unknown"))
            )
        )

    def test_stale_last_seen_is_touched_once_per_interval(self) -> None:
        stale, _ = self.add_session("stale", last_seen_age=3600)
        recent, _ = self.add_session("recent", last_seen_age=60)
        before_recent = self.stored(recent)["last_seen"]
        before_stale = self.stored(stale)["last_seen"]

        self.assertTrue(self.auth.authenticated_session(handler_for(recent)))
        self.assertEqual(self.stored(recent)["last_seen"], before_recent)

        self.assertTrue(self.auth.authenticated_session(handler_for(stale)))
        touched = self.stored(stale)["last_seen"]
        self.assertNotEqual(touched, before_stale)
        self.assertTrue(self.auth.authenticated_session(handler_for(stale)))
        self.assertEqual(self.stored(stale)["last_seen"], touched)

    def test_touch_skips_the_write_when_another_request_already_touched(self) -> None:
        token, _ = self.add_session("raced", last_seen_age=3600)
        original = self.auth._sessions.touch
        calls: list[str] = []

        def counting_touch(db, token_hash, last_seen):
            calls.append(token_hash)
            original(db, token_hash, last_seen)

        with patch.object(self.auth._sessions, "touch", counting_touch):
            for _ in range(3):
                self.assertTrue(self.auth.authenticated_session(handler_for(token)))
        self.assertEqual(len(calls), 1)

    def test_busy_writer_never_blocks_or_fails_a_valid_stale_session(self) -> None:
        token, _ = self.add_session("busy", last_seen_age=3600)
        before = self.stored(token)["last_seen"]
        release_writer = self.hold_writer()
        with patch.object(http_auth, "SESSION_MAINTENANCE_WAIT_SECONDS", 0.05):
            session = self.run_blocking(
                lambda: self.auth.authenticated_session(handler_for(token))
            )
        self.assertTrue(session)
        self.assertEqual(self.stored(token)["last_seen"], before)
        # The skipped touch is retried by a later request once the writer is free.
        release_writer()
        self.assertTrue(self.auth.authenticated_session(handler_for(token)))
        self.assertNotEqual(self.stored(token)["last_seen"], before)

    def test_expired_session_is_rejected_and_removed(self) -> None:
        token, _ = self.add_session("expired", expires_in=-1)
        self.assertIsNone(self.auth.authenticated_session(handler_for(token)))
        self.assertIsNone(self.stored(token))

    def test_expired_session_is_rejected_even_when_the_writer_is_busy(self) -> None:
        token, _ = self.add_session("expired-busy", expires_in=-1)
        self.hold_writer()
        with patch.object(http_auth, "SESSION_MAINTENANCE_WAIT_SECONDS", 0.05):
            self.assertIsNone(
                self.run_blocking(
                    lambda: self.auth.authenticated_session(handler_for(token))
                )
            )
        self.assertIsNotNone(self.stored(token))

    def test_logout_revokes_the_session_for_the_next_lookup(self) -> None:
        token, _ = self.add_session("logout")
        other, _ = self.add_session("other")
        self.assertTrue(self.auth.authenticated_session(handler_for(token)))
        self.auth.logout_user(handler_for(token))
        self.assertIsNone(self.auth.authenticated_session(handler_for(token)))
        self.assertIsNone(self.stored(token))
        self.assertTrue(self.auth.authenticated_session(handler_for(other)))

    def test_revocation_by_another_connection_is_seen_by_pooled_readers(self) -> None:
        token, _ = self.add_session("revoked")
        self.assertTrue(self.auth.authenticated_session(handler_for(token)))
        with self.manager.unit_of_work() as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (self.auth.session_token_hash(token),),
            )
        self.assertIsNone(self.auth.authenticated_session(handler_for(token)))

    def test_login_creates_a_session_that_the_read_path_accepts(self) -> None:
        result = self.auth.login_user(handler_for(), "synthetic-password")
        session = self.auth.authenticated_session(handler_for(result["session_token"]))
        assert session is not None
        self.assertEqual(
            session["csrf_hash"], self.auth.session_token_hash(result["csrf"])
        )
        with self.assertRaises(AppError) as failure:
            self.auth.login_user(handler_for(), "wrong-password")
        self.assertEqual(failure.exception.status, 401)

    def test_login_and_logout_do_not_queue_behind_the_shared_database_lock(
        self,
    ) -> None:
        # Startup writers hold the shared lock while they wait for the writer;
        # a login must not inherit that wait.
        holding, release = threading.Event(), threading.Event()

        def hold_lock() -> None:
            with self.database_lock:
                holding.set()
                release.wait(10)

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.addCleanup(holder.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(holding.wait(5))
        result = cast(
            dict,
            self.run_blocking(
                lambda: self.auth.login_user(handler_for(), "synthetic-password")
            ),
        )
        token = result["session_token"]
        self.assertTrue(self.auth.authenticated_session(handler_for(token)))

        def logout() -> bool:
            self.auth.logout_user(handler_for(token))
            return True

        self.run_blocking(logout)
        self.assertIsNone(self.auth.authenticated_session(handler_for(token)))

    def test_login_wait_for_a_busy_writer_is_bounded(self) -> None:
        self.hold_writer()
        started = time.monotonic()
        with (
            patch.object(http_auth, "SESSION_WRITE_WAIT_SECONDS", 0.1),
            self.assertRaises(DatabaseBusyError),
        ):
            self.auth.login_user(handler_for(), "synthetic-password")
        self.assertLess(time.monotonic() - started, 3)
        self.assertLess(http_auth.SESSION_WRITE_WAIT_SECONDS, 25)

    def test_csrf_is_enforced_against_the_session_hash(self) -> None:
        token, csrf = self.add_session("csrf")
        session = self.auth.authenticated_session(handler_for(token))
        assert session is not None
        self.auth.require_csrf(handler_for(token, csrf), session)
        for bad in ("", "wrong-token"):
            with self.assertRaises(AppError) as failure:
                self.auth.require_csrf(handler_for(token, bad), session)
            self.assertEqual(failure.exception.status, 403)

    def test_require_auth_rejects_anonymous_and_expired_requests(self) -> None:
        expired, _ = self.add_session("expired-auth", expires_in=-5)
        for token in ("", "unknown", expired):
            with self.assertRaises(AppError) as failure:
                self.auth.require_auth(handler_for(token))
            self.assertEqual(failure.exception.status, 401)

    def test_due_cleanup_runs_once_per_interval(self) -> None:
        self.add_session("gone", expires_in=-10)
        token, _ = self.add_session("live")
        self.auth._last_cleanup_monotonic = None
        self.assertTrue(self.auth.authenticated_session(handler_for(token)))
        with self.manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"], 1
            )
        self.add_session("gone-again", expires_in=-10)
        self.assertTrue(self.auth.authenticated_session(handler_for(token)))
        with self.manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"], 2
            )

    def test_skipped_cleanup_backs_off_until_the_next_interval(self) -> None:
        self.add_session("gone", expires_in=-10)
        token, _ = self.add_session("live")
        self.auth._last_cleanup_monotonic = None
        stop = self.hold_writer()
        with patch.object(http_auth, "SESSION_MAINTENANCE_WAIT_SECONDS", 0.05):
            self.assertTrue(
                self.run_blocking(
                    lambda: self.auth.authenticated_session(handler_for(token))
                )
            )
        stop()
        self.assertFalse(self.auth._cleanup_due())
        with self.manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"], 2
            )

    def test_restore_coach_session_csrf_hash_reads_without_the_writer(self) -> None:
        _, csrf = self.add_session("coach")
        key = self.auth.session_token_hash(self.auth.session_token_hash(csrf))
        self.hold_writer()
        self.assertEqual(
            self.run_blocking(lambda: self.auth.restore_coach_session_csrf_hash(key)),
            self.auth.session_token_hash(csrf),
        )
        self.assertEqual(self.auth.restore_coach_session_csrf_hash("unknown"), "")


class SessionAuthCacheLockTests(unittest.TestCase):
    def test_cache_resolution_does_not_wait_for_the_database_lock(self) -> None:
        cache = http_auth.SessionAuthServiceCache()
        database_lock = threading.RLock()
        resolved: list[object] = []
        acquired = threading.Event()
        release = threading.Event()

        def hold_database_lock() -> None:
            with database_lock:
                acquired.set()
                release.wait(10)

        holder = threading.Thread(target=hold_database_lock)
        holder.start()
        self.addCleanup(holder.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(acquired.wait(5))

        resolver = threading.Thread(
            target=lambda: resolved.append(
                cache.get(
                    cast(DatabaseManager, object()),
                    database_lock,
                    CONFIG,
                    True,
                    RateLimiter(),
                )
            )
        )
        resolver.start()
        resolver.join(5)
        self.assertFalse(resolver.is_alive())
        self.assertEqual(len(resolved), 1)


if __name__ == "__main__":
    unittest.main()
