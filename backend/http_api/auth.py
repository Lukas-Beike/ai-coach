"""Authentication, session, cookie, CSRF, and local request rate limits."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie
from typing import Any

from backend import config as app_config
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.http_api.rate_limit import RateLimiter
from backend.http_api.responses import session_cookies

RATE_LIMITER = RateLimiter()
SESSION_COOKIE = "ic_session"
CSRF_COOKIE = "ic_csrf"
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
SESSION_TOUCH_INTERVAL_SECONDS = 5 * 60
SESSION_CLEANUP_INTERVAL_SECONDS = 15 * 60
SESSION_CLEANUP_BATCH_SIZE = 100


class SessionAuthServiceCache:
    """Keep the composed auth service bound to the active persistence config."""

    def __init__(self) -> None:
        self._service: SessionAuthService | None = None
        self._signature: tuple[DatabaseManager, Config, bool] | None = None

    def get(
        self,
        database_manager: DatabaseManager,
        database_lock: threading.RLock,
        config: Config,
        sqlcipher_available: bool,
        rate_limiter: RateLimiter,
    ) -> SessionAuthService:
        with database_lock:
            signature = (database_manager, config, sqlcipher_available)
            if self._service is None or self._signature != signature:
                self._service = SessionAuthService(
                    database_manager,
                    database_lock,
                    config,
                    sqlcipher_available,
                    rate_limiter,
                )
                self._signature = signature
            return self._service


SESSION_AUTH_SERVICE_CACHE = SessionAuthServiceCache()


class SessionAuthService:
    """Own persistent session behavior and its in-memory synchronization state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: threading.RLock,
        config: Config,
        sqlcipher_available: bool,
        rate_limiter: RateLimiter,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._config = config
        self._sqlcipher_available = sqlcipher_available
        self._rate_limiter = rate_limiter
        self._session_lock = threading.RLock()
        self._last_cleanup_monotonic = 0.0

    @property
    def session_lock(self) -> threading.RLock:
        return self._session_lock

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    @staticmethod
    def client_ip(handler: Any) -> str:
        return str(handler.client_address[0]) if handler.client_address else "unknown"

    @staticmethod
    def cookie_value(handler: Any, name: str) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(handler.headers.get("Cookie", ""))
        except (CookieError, TypeError, ValueError):
            return ""
        return cookie[name].value if name in cookie else ""

    @staticmethod
    def session_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def session_timestamp(value: Any) -> float | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (TypeError, ValueError, OverflowError):
            return None

    def cleanup_expired_sessions(self, db: Any, now: float, *, force: bool = False) -> int:
        current_monotonic = time.monotonic()
        if (
            not force
            and current_monotonic - self._last_cleanup_monotonic
            < SESSION_CLEANUP_INTERVAL_SECONDS
        ):
            return 0
        cursor = db.execute(
            "DELETE FROM sessions WHERE token_hash IN ("
            "SELECT token_hash FROM sessions WHERE expires_at <= ? LIMIT ?"
            ")",
            (now, SESSION_CLEANUP_BATCH_SIZE),
        )
        self._last_cleanup_monotonic = current_monotonic
        return cursor.rowcount

    def authenticated_session(self, handler: Any) -> dict[str, Any] | None:
        token = self.cookie_value(handler, SESSION_COOKIE)
        if not token:
            return None
        now = time.time()
        token_hash = self.session_token_hash(token)
        with self._session_lock, self._database_lock, self._database_manager.unit_of_work() as db:
            self.cleanup_expired_sessions(db, now)
            row = db.execute(
                "SELECT csrf_hash, expires_at, last_seen FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            if float(row["expires_at"]) <= now:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            last_seen = self.session_timestamp(row["last_seen"])
            if last_seen is None or now - last_seen >= SESSION_TOUCH_INTERVAL_SECONDS:
                db.execute(
                    "UPDATE sessions SET last_seen = ? WHERE token_hash = ?",
                    (datetime.now(timezone.utc).isoformat(), token_hash),
                )
            return {"csrf_hash": row["csrf_hash"], "expires_at": float(row["expires_at"])}

    def login_user(self, handler: Any, password: str) -> dict[str, Any]:
        if app_config.security_configuration_error(
            self._config, sqlcipher_available=self._sqlcipher_available
        ):
            raise AppError(503, "Die sichere App-Konfiguration ist unvollständig.")
        allowed, retry_after = self._rate_limiter.allow(
            f"login:{self.client_ip(handler)}", 5, 900
        )
        if not allowed:
            raise AppError(429, f"Zu viele Anmeldeversuche. Erneut versuchen in etwa {retry_after} Sekunden.")
        if not hmac.compare_digest(str(password).encode("utf-8"), self._config.app_password.encode("utf-8")):
            raise AppError(401, "Ungültiges Passwort.")
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        with self._session_lock, self._database_lock, self._database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                (
                    self.session_token_hash(token), self.session_token_hash(csrf),
                    now + SESSION_TTL_SECONDS, datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return {"status": "ok", "authenticated": True, "csrf": csrf, "session_token": token}

    def logout_user(self, handler: Any) -> None:
        token = self.cookie_value(handler, SESSION_COOKIE)
        if not token:
            return
        with self._session_lock, self._database_lock, self._database_manager.unit_of_work() as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (self.session_token_hash(token),),
            )

    def require_auth(self, handler: Any) -> dict[str, Any]:
        if app_config.security_configuration_error(
            self._config, sqlcipher_available=self._sqlcipher_available
        ):
            raise AppError(503, "Die sichere App-Konfiguration ist unvollständig.")
        session = self.authenticated_session(handler)
        if not session:
            raise AppError(401, "Anmeldung erforderlich.")
        allowed, retry_after = self._rate_limiter.allow(
            f"api:{self.client_ip(handler)}", 180, 60
        )
        if not allowed:
            raise AppError(429, f"Zu viele Anfragen. Erneut versuchen in etwa {retry_after} Sekunden.")
        return session

    def require_csrf(self, handler: Any, session: dict[str, Any]) -> None:
        token = handler.headers.get("X-CSRF-Token", "")
        if not token or not hmac.compare_digest(
            self.session_token_hash(token), str(session.get("csrf_hash", ""))
        ):
            raise AppError(403, "Ungültiges CSRF-Token.")

    def session_cookie_headers(
        self, token: str = "", csrf: str = "", *, clear: bool = False
    ) -> list[str]:
        return session_cookies(
            SESSION_COOKIE, CSRF_COOKIE, token, csrf,
            ttl_seconds=SESSION_TTL_SECONDS,
            secure=bool(getattr(self._config, "secure_cookies", False)),
            clear=clear,
        )

    def restore_coach_session_csrf_hash(self, session_key: str) -> str:
        normalized_key = str(session_key or "").strip()
        if not normalized_key:
            return ""
        now = time.time()
        with self._session_lock, self._database_lock, self._database_manager.unit_of_work() as db:
            rows = db.execute("SELECT csrf_hash, expires_at FROM sessions").fetchall()
        for row in rows:
            csrf_hash = str(row.get("csrf_hash") or "")
            if not csrf_hash or float(row.get("expires_at") or 0) <= now:
                continue
            key = hashlib.sha256(csrf_hash.encode("utf-8")).hexdigest()
            if hmac.compare_digest(key, normalized_key):
                return csrf_hash
        return ""
