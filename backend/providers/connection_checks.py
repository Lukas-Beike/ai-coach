"""Explicit, read-only provider connection checks with an in-memory last result.

A check proves that the effective credentials were accepted at one moment. It
is separate from configuration (a value exists) and from synchronization
freshness (data was loaded). Results live only in memory, are bound to an
opaque fingerprint of the effective credentials, and are discarded when that
fingerprint changes or the server restarts. Raw provider responses, credentials
and tokens never enter a result.

Known limit: a credential that changes and changes back between two status
reads revives its earlier result. The UI reloads after every credential change,
so this needs an API client that writes and reverts without reading status.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.errors import AppError

_LOGGER = logging.getLogger(__name__)

NOT_CONFIGURED = "not_configured"
UNCHECKED = "unchecked"
SUCCESS = "success"
AUTH_FAILED = "auth_failed"
RATE_LIMITED = "rate_limited"
UNAVAILABLE = "unavailable"
SCOPE_MISSING = "scope_missing"
UNSUPPORTED = "unsupported"
MISCONFIGURED = "misconfigured"
BUSY = "busy"
CHECKING = "checking"
# A local state read failed, so no statement about the provider is possible.
UNKNOWN = "unknown"

# Longest wait for one check before the card reports it as still running.
CHECK_DEADLINE_SECONDS = 45.0
# Minimum time between two real requests per provider and credential set.
CHECK_COOLDOWN = timedelta(seconds=10)

# Provider reasons that mean the endpoint cannot answer this check at all.
UNSUPPORTED_REASON = "check_unsupported"
_REPLAYABLE = frozenset(
    {SUCCESS, AUTH_FAILED, RATE_LIMITED, MISCONFIGURED, UNSUPPORTED, SCOPE_MISSING}
)
MISCONFIGURED_REASON = "check_misconfigured"
BUSY_REASON = "provider_busy"
UNREADABLE_REASON = "check_unreadable"
SCOPE_MISSING_REASON = "check_scope_missing"
_AUTH_REASONS = frozenset(
    {
        "upstream_auth",
        "wahoo_unauthorized",
        "wahoo_reconnect_required",
        "wahoo_not_connected",
        "reconnect_required",
    }
)


@dataclass(frozen=True)
class ProviderProbe:
    """One provider's read-only check and its local configuration signals."""

    # One read of (configured, opaque identity of the effective credentials).
    snapshot: Callable[[], tuple[bool, str]]
    # Performs exactly one bounded read-only request; failures raise AppError.
    # Returns the identity it verified when that differs from the pre-check one
    # (a Garmin login rotates its stored token), otherwise None.
    check: Callable[[], str | None]
    # Recovery guidance shown when the credentials were rejected.
    auth_hint: str = ""


def simple_probe(
    configured: Callable[[], bool],
    identity: Callable[[], str],
    check: Callable[[], None],
    auth_hint: str = "",
) -> ProviderProbe:
    """Build a probe whose configuration and identity are cheap separate reads."""

    def snapshot() -> tuple[bool, str]:
        return (True, identity()) if configured() else (False, "")

    return ProviderProbe(snapshot=snapshot, check=check, auth_hint=auth_hint)


def classify_failure(error: AppError) -> str:
    """Map a provider error to a safe category without keeping its text."""
    upstream = error.upstream_status
    if error.reason == UNSUPPORTED_REASON:
        return UNSUPPORTED
    if error.reason == MISCONFIGURED_REASON:
        return MISCONFIGURED
    if error.reason == BUSY_REASON:
        return BUSY
    if error.reason == UNREADABLE_REASON:
        return UNKNOWN
    if error.reason == SCOPE_MISSING_REASON:
        return SCOPE_MISSING
    if upstream == 429 or error.status == 429:
        return RATE_LIMITED
    if upstream in {401, 403} or error.status == 401 or error.reason in _AUTH_REASONS:
        return AUTH_FAILED
    if (
        upstream is not None
        and 400 <= upstream < 500
        and upstream not in {401, 403, 408, 429}
    ):
        # The provider was reached and refused the request itself.
        return MISCONFIGURED
    return UNAVAILABLE


def _result(
    probe: ProviderProbe, status: str, checked_at: str | None
) -> dict[str, Any]:
    return {
        "status": status,
        "checked_at": checked_at,
        "guidance": probe.auth_hint if status == AUTH_FAILED else "",
    }


def _fingerprint(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _snapshot(probe: ProviderProbe, provider: str) -> tuple[bool, str] | None:
    """Read configuration and identity once; None when the local read failed."""
    try:
        configured, identity = probe.snapshot()
    except Exception as error:  # noqa: BLE001 - one unreadable provider must not hide the rest
        _LOGGER.warning(
            "Provider connection state unreadable",
            extra={
                "event": "provider_check_state_failed",
                "context": {"provider": provider, "error_type": type(error).__name__},
            },
        )
        return None
    return (True, _fingerprint(identity)) if configured else (False, "")


class ProviderConnectionChecks:
    """Run explicit checks and report the last result per provider."""

    def __init__(
        self,
        probes: dict[str, ProviderProbe],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        deadline_seconds: float = CHECK_DEADLINE_SECONDS,
        operation: Callable[[], AbstractContextManager[Any]] = lambda: nullcontext(),
    ) -> None:
        self._probes = dict(probes)
        self._now = now
        self._lock = threading.Lock()
        self._busy = {name: threading.Lock() for name in probes}
        self._deadline_seconds = deadline_seconds
        self._operation = operation
        self._last: dict[str, tuple[str, str, str]] = {}
        self._at: dict[str, datetime] = {}

    def providers(self) -> tuple[str, ...]:
        return tuple(self._probes)

    def status(self, provider: str, *, include_running: bool = True) -> dict[str, Any]:
        """Read local state only; never contact the provider."""
        probe = self._probe(provider)
        state = _snapshot(probe, provider)
        if state is None:
            return _result(probe, UNKNOWN, None)
        configured, fingerprint = state
        if not configured:
            with self._lock:
                self._last.pop(provider, None)
            return _result(probe, NOT_CONFIGURED, None)
        if include_running and self._busy[provider].locked():
            # A check is still running (also after a reload): show it, not a stale result.
            return _result(probe, CHECKING, None)
        with self._lock:
            last = self._last.get(provider)
            if last is not None and last[0] != fingerprint:
                # Changed credentials drop the result when it is next read.
                del self._last[provider]
                last = None
        if last is None:
            return _result(probe, UNCHECKED, None)
        return _result(probe, last[1], last[2])

    def statuses(self) -> dict[str, dict[str, Any]]:
        return {name: self.status(name) for name in self._probes}

    def check(self, provider: str) -> dict[str, Any]:
        """Run one explicit check; a concurrent call reports it as in progress.

        The request runs in a worker thread bounded by the deadline. A check that
        outlives the deadline reports ``checking``; the worker still stores its
        result when it finishes, and the card picks it up on the next read.
        """
        probe = self._probe(provider)
        state = _snapshot(probe, provider)
        if state is None:
            return _result(probe, UNKNOWN, None)
        configured, fingerprint = state
        if not configured:
            with self._lock:
                self._last.pop(provider, None)
            return _result(probe, NOT_CONFIGURED, None)
        busy = self._busy[provider]
        if not busy.acquire(blocking=False):
            return _result(probe, CHECKING, None)
        outcome: dict[str, dict[str, Any]] = {}
        done = threading.Event()

        def run() -> None:
            try:
                with self._operation():
                    outcome["result"] = self._perform(provider, probe, fingerprint)
            except AppError as error:
                # A maintenance window (restore, privacy delete) is not a crash.
                _LOGGER.info(
                    "Provider connection check interrupted",
                    extra={
                        "event": "provider_check_interrupted",
                        "context": {"provider": provider, "reason": error.reason},
                    },
                )
                outcome["result"] = _result(probe, UNKNOWN, None)
            except Exception:
                _LOGGER.exception("Provider connection check crashed")
                outcome["result"] = _result(probe, UNKNOWN, None)
            finally:
                busy.release()
                done.set()

        try:
            threading.Thread(target=run, name=f"check-{provider}", daemon=True).start()
        except BaseException:
            busy.release()
            raise
        if done.wait(self._deadline_seconds):
            return outcome["result"]
        return _result(probe, CHECKING, None)

    def _perform(
        self, provider: str, probe: ProviderProbe, fingerprint: str
    ) -> dict[str, Any]:
        with self._lock:
            last, last_at = self._last.get(provider), self._at.get(provider)
        if (
            last is not None
            and last[0] == fingerprint
            and last_at is not None
            and last[1] in _REPLAYABLE
            and self._now() - last_at < CHECK_COOLDOWN
        ):
            # Repeated clicks must not become repeated provider requests;
            # transient outcomes are always retried.
            return _result(probe, last[1], last[2])
        verified: str | None = None
        try:
            verified = probe.check()
            result = SUCCESS
        except AppError as error:
            result = classify_failure(error)
        except Exception as error:  # noqa: BLE001 - not a provider answer
            _LOGGER.warning(
                "Provider connection check failed locally",
                extra={
                    "event": "provider_check_failed",
                    "context": {
                        "provider": provider,
                        "error_type": type(error).__name__,
                    },
                },
            )
            return _result(probe, UNKNOWN, None)
        checked_at = self._now().isoformat()
        after = _snapshot(probe, provider)
        if after is None:
            return _result(probe, UNKNOWN, None)
        configured_after, fingerprint_after = after
        if not configured_after:
            with self._lock:
                self._last.pop(provider, None)
        if not configured_after and result == AUTH_FAILED:
            # The failed check itself invalidated the grant (Wahoo): keep the
            # reconnect guidance for this answer without storing a result.
            return _result(probe, result, checked_at)
        # A verified identity replaces the pre-check one: the check's own token
        # rotation must not discard the answer it produced.
        expected = _fingerprint(verified) if isinstance(verified, str) else fingerprint
        if not configured_after or fingerprint_after != expected:
            # Credentials changed while the request was in flight.
            return self.status(provider, include_running=False)
        if result == BUSY:
            # The provider was never contacted; keep the previous result.
            return _result(probe, BUSY, None)
        with self._lock:
            self._last[provider] = (expected, result, checked_at)
            self._at[provider] = self._now()
        return _result(probe, result, checked_at)

    def _probe(self, provider: str) -> ProviderProbe:
        probe = self._probes.get(provider)
        if probe is None:
            raise AppError(404, "Unbekannter Anbieter.", reason="unknown_provider")
        return probe
