"""Authentication, session, cookie, CSRF, and local request rate limits."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from http.cookies import CookieError, SimpleCookie
from typing import Any

from backend import config as app_config
from backend.athlete.sessions import AthleteSessionService
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
# Session upkeep (touch, cleanup, expired delete) never decides authentication,
# so it only tries the locks and the writer once and retries on a later request.
SESSION_MAINTENANCE_WAIT_SECONDS = 0.0
# Login and logout write one session row in their own unit of work. They wait
# only for the writer, never for the shared database lock: multi-repository
# writers hold that lock while they themselves wait for the writer, so queuing
# behind it made a login wait for several background units without a bound.
# The writer wait stays well below the browser's request timeout, so a busy
# writer answers with a retryable 503 instead of a hung or failed request.
# A restore still cannot interleave: restore_drain blocks new leases and waits
# for active ones before the database file is swapped.
SESSION_WRITE_WAIT_SECONDS = 10.0

TrustedNetworks = Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]


def _parsed_ip(
    value: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped or address


def resolve_client_ip(
    peer: str, forwarded_for: Iterable[str], trusted_proxies: TrustedNetworks
) -> str:
    """Return the request's client address for rate limiting.

    ``X-Forwarded-For`` is honored only when the socket peer is a configured
    trusted proxy. The chain is read from the right, skipping trusted hops, so
    entries a client prepends itself cannot choose its rate-limit bucket.
    """
    trusted = tuple(trusted_proxies)
    if not trusted:
        return peer
    peer_address = _parsed_ip(peer)

    def is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return any(address in network for network in trusted)

    if peer_address is None or not is_trusted(peer_address):
        return peer
    client = peer_address
    # Walk from the right and stop at the first untrusted or malformed hop,
    # so the cost does not grow with entries a client prepends.
    for value in reversed(list(forwarded_for)):
        remaining, separator = str(value), ","
        while separator:
            remaining, separator, hop = remaining.rpartition(",")
            address = _parsed_ip(hop)
            if address is None:
                return str(client)
            client = address
            if not is_trusted(address):
                return str(client)
    return str(client)


class SessionAuthServiceCache:
    """Keep the composed auth service bound to the active persistence config."""

    def __init__(self) -> None:
        self._service: SessionAuthService | None = None
        self._signature: (
            tuple[DatabaseManager, Config, bool, AthleteSessionService] | None
        ) = None
        self._sessions = AthleteSessionService()
        self._lock = threading.Lock()

    def get(
        self,
        database_manager: DatabaseManager,
        database_lock: threading.RLock,
        config: Config,
        sqlcipher_available: bool,
        rate_limiter: RateLimiter,
        sessions: AthleteSessionService | None = None,
    ) -> SessionAuthService:
        # The cache only guards its own composition state; it must not queue
        # every authenticated request behind a database writer.
        with self._lock:
            sessions = sessions or self._sessions
            signature = (database_manager, config, sqlcipher_available, sessions)
            if self._service is None or self._signature != signature:
                self._service = SessionAuthService(
                    database_manager,
                    database_lock,
                    config,
                    sqlcipher_available,
                    rate_limiter,
                    sessions,
                )
                self._signature = signature
            return self._service


SESSION_AUTH_SERVICE_CACHE = SessionAuthServiceCache()


def get_session_auth_service(
    database_manager: DatabaseManager,
    database_lock: threading.RLock,
    config: Config,
    sqlcipher_available: bool,
    sessions: AthleteSessionService | None = None,
) -> SessionAuthService:
    """Return the auth service owned by the current persistence config."""
    return SESSION_AUTH_SERVICE_CACHE.get(
        database_manager,
        database_lock,
        config,
        sqlcipher_available,
        RATE_LIMITER,
        sessions,
    )


class SessionAuthService:
    """Own persistent session behavior and its in-memory synchronization state."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: threading.RLock,
        config: Config,
        sqlcipher_available: bool,
        rate_limiter: RateLimiter,
        sessions: AthleteSessionService | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._config = config
        self._sqlcipher_available = sqlcipher_available
        self._rate_limiter = rate_limiter
        self._sessions = sessions or AthleteSessionService()
        self._session_lock = threading.RLock()
        # None means no cleanup has run yet, so the first check is always due
        # regardless of how long the monotonic clock has been running.
        self._last_cleanup_monotonic: float | None = None

    @property
    def session_lock(self) -> threading.RLock:
        return self._session_lock

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    def client_ip(self, handler: Any) -> str:
        peer = str(handler.client_address[0]) if handler.client_address else "unknown"
        trusted = getattr(self._config, "trusted_proxies", ())
        if not trusted:
            return peer
        headers = getattr(handler, "headers", None)
        get_all = getattr(headers, "get_all", None)
        forwarded = (get_all("X-Forwarded-For") if callable(get_all) else None) or []
        return resolve_client_ip(peer, forwarded, trusted)

    @staticmethod
    def cookie_value(handler: Any, name: str) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(handler.headers.get("Cookie", ""))
        except CookieError, TypeError, ValueError:
            return ""
        return cookie[name].value if name in cookie else ""

    @staticmethod
    def session_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def session_timestamp(value: Any) -> float | None:
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.timestamp()
        except TypeError, ValueError, OverflowError:
            return None

    def cleanup_expired_sessions(
        self, db: Any, now: float, *, force: bool = False
    ) -> int:
        if not force and not self._cleanup_due():
            return 0
        deleted = self._sessions.cleanup_expired(db, now, SESSION_CLEANUP_BATCH_SIZE)
        self._last_cleanup_monotonic = time.monotonic()
        return deleted

    def _cleanup_due(self) -> bool:
        last = self._last_cleanup_monotonic
        return (
            last is None or time.monotonic() - last >= SESSION_CLEANUP_INTERVAL_SECONDS
        )

    def _write_if_idle(self, write: Callable[[Any], object]) -> bool:
        """Run a non-essential session write unless the writer is busy.

        Authentication is decided from the read snapshot alone, so a busy
        writer must never stall or fail a request; the write is retried by a
        later request.
        """
        held: list[threading.RLock] = []
        try:
            for lock in (self._session_lock, self._database_lock):
                if not lock.acquire(timeout=SESSION_MAINTENANCE_WAIT_SECONDS):
                    return False
                held.append(lock)
            with self._database_manager.unit_of_work(
                timeout=SESSION_MAINTENANCE_WAIT_SECONDS
            ) as db:
                write(db)
            return True
        except TimeoutError:
            return False
        finally:
            for lock in reversed(held):
                lock.release()

    def _touch_if_still_stale(self, db: Any, token_hash: str, now: float) -> None:
        row = self._sessions.get(db, token_hash)
        if not row:
            return
        last_seen = self.session_timestamp(row["last_seen"])
        if last_seen is None or now - last_seen >= SESSION_TOUCH_INTERVAL_SECONDS:
            self._sessions.touch(db, token_hash, datetime.now(UTC).isoformat())

    def authenticated_session(self, handler: Any) -> dict[str, Any] | None:
        token = self.cookie_value(handler, SESSION_COOKIE)
        if not token:
            return None
        now = time.time()
        token_hash = self.session_token_hash(token)
        # The lookup is a pure read on a WAL snapshot: it neither waits for the
        # writer nor holds a lock, and it sees every committed login/logout.
        with self._database_manager.read_snapshot() as db:
            row = self._sessions.get(db, token_hash)
        expires_at = float(row["expires_at"]) if row else 0.0
        if self._cleanup_due() and not self._write_if_idle(
            lambda db: self.cleanup_expired_sessions(db, now)
        ):
            # Back off until the next interval so a long busy writer does not
            # make every request wait for the cleanup attempt.
            self._last_cleanup_monotonic = time.monotonic()
        if not row:
            return None
        if expires_at <= now:
            self._write_if_idle(lambda db: self._sessions.delete(db, token_hash))
            return None
        last_seen = self.session_timestamp(row["last_seen"])
        if last_seen is None or now - last_seen >= SESSION_TOUCH_INTERVAL_SECONDS:
            self._write_if_idle(
                lambda db: self._touch_if_still_stale(db, token_hash, now)
            )
        return {"csrf_hash": row["csrf_hash"], "expires_at": expires_at}

    def login_user(self, handler: Any, password: str | None = None) -> dict[str, Any]:
        if app_config.security_configuration_error(
            self._config, sqlcipher_available=self._sqlcipher_available
        ):
            raise AppError(503, "Die sichere App-Konfiguration ist unvollständig.")
        allowed, retry_after = self._rate_limiter.allow(
            f"login:{self.client_ip(handler)}", 5, 900
        )
        if not allowed:
            raise AppError(
                429,
                f"Zu viele Anmeldeversuche. Erneut versuchen in etwa {retry_after} Sekunden.",
                reason="rate_limited",
                retry_after_seconds=retry_after,
            )
        if password is None:
            payload = handler.read_json()
            password = (
                str(payload.get("password") or "") if isinstance(payload, dict) else ""
            )
        if not hmac.compare_digest(
            str(password).encode("utf-8"), self._config.app_password.encode("utf-8")
        ):
            raise AppError(401, "Ungültiges Passwort.")
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = time.time()
        with (
            self._session_lock,
            self._database_manager.unit_of_work(
                timeout=SESSION_WRITE_WAIT_SECONDS
            ) as db,
        ):
            self._sessions.create(
                db,
                self.session_token_hash(token),
                self.session_token_hash(csrf),
                now + SESSION_TTL_SECONDS,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            )
        return {
            "status": "ok",
            "authenticated": True,
            "csrf": csrf,
            "session_token": token,
        }

    def logout_user(self, handler: Any) -> None:
        token = self.cookie_value(handler, SESSION_COOKIE)
        if not token:
            return
        with (
            self._session_lock,
            self._database_manager.unit_of_work(
                timeout=SESSION_WRITE_WAIT_SECONDS
            ) as db,
        ):
            self._sessions.delete(db, self.session_token_hash(token))

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
            raise AppError(
                429,
                f"Zu viele Anfragen. Erneut versuchen in etwa {retry_after} Sekunden.",
                reason="rate_limited",
                retry_after_seconds=retry_after,
            )
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
            SESSION_COOKIE,
            CSRF_COOKIE,
            token,
            csrf,
            ttl_seconds=SESSION_TTL_SECONDS,
            secure=bool(getattr(self._config, "secure_cookies", False)),
            clear=clear,
        )

    def restore_coach_session_csrf_hash(self, session_key: str) -> str:
        normalized_key = str(session_key or "").strip()
        if not normalized_key:
            return ""
        now = time.time()
        with self._database_manager.read_snapshot() as db:
            rows = self._sessions.list_csrf(db)
        for row in rows:
            csrf_hash = str(row.get("csrf_hash") or "")
            if not csrf_hash or float(row.get("expires_at") or 0) <= now:
                continue
            key = hashlib.sha256(csrf_hash.encode("utf-8")).hexdigest()
            if hmac.compare_digest(key, normalized_key):
                return csrf_hash
        return ""
