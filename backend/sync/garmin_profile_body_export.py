"""Explicit profile body-composition export, independent of local commits."""

import logging
import math
from contextlib import ExitStack
from datetime import datetime
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

from backend.athlete.profile import timezone_name
from backend.sync.garmin_service import _persist_garmin_tokens, shared_garmin_sync_lock


class GarminProfileBodyExport:
    def __init__(self, profile: Any, reader: Any, fixture_loader: Any, tokens: Any):
        self._profile = profile
        self._reader = reader
        self._fixture_loader = fixture_loader
        self._tokens = tokens

    def _acquire_locks(self, stack: ExitStack, deadline: float) -> bool:
        for lock in (shared_garmin_sync_lock(), self._profile.mutation_coordinator):
            if not lock.acquire(timeout=max(0.0, deadline - monotonic())):
                return False
            stack.callback(lock.release)
        return monotonic() < deadline

    def _authenticate(self) -> tuple[Any, Any] | None:
        if self._fixture_loader.path() is not None or not self._reader.configured():
            return None
        try:
            return self._reader._authenticated_client(
                lambda _service, _operation, call, _details: call()
            )
        except Exception:  # noqa: BLE001 - provider authentication is an external boundary
            return None

    def _upload_and_persist(
        self,
        client: Any,
        login_argument: Any,
        tz_name: str | None,
        weight: float,
        fat: float,
        deadline: float,
    ) -> str:
        try:
            if monotonic() >= deadline:
                return "unavailable"
            timestamp = datetime.now(ZoneInfo(timezone_name(tz_name))).isoformat()
            response = _upload_with_deadline(client, timestamp, weight, fat, deadline)
            return _outcome(response)
        except Exception as exc:  # noqa: BLE001 - remote outcome may be ambiguous
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return (
                "rejected"
                if isinstance(status, int)
                and 400 <= status < 500
                and status not in (408, 429)
                else "uncertain"
            )
        finally:
            try:
                _persist_garmin_tokens(self._tokens, client, login_argument)
            except Exception:  # noqa: BLE001 - preserve the determined remote outcome
                logging.getLogger(__name__).warning("Garmin token persistence failed")

    def export(
        self, saved: dict[str, str], revision: str | None, deadline: float | None = None
    ) -> str:
        deadline = monotonic() + 10.0 if deadline is None else deadline
        with ExitStack() as locks:
            if not self._acquire_locks(locks, deadline):
                return "unavailable"
            current = self._profile.get()  # reader closes before authentication or upload
            if self._profile.revision() != revision or any(
                current.get(k) != saved.get(k) for k in ("weight_kg", "body_fat_pct")
            ):
                return "superseded"
            body = _parse_body_measurements(current)
            if body is None:
                return "invalid"
            auth = self._authenticate()
            if auth is None:
                return "unavailable"
            client, login_argument = auth
            weight, fat = body
            return self._upload_and_persist(
                client, login_argument, current.get("timezone"), weight, fat, deadline
            )


def _parse_body_measurements(current: dict[str, Any]) -> tuple[float, float] | None:
    try:
        weight = float(current["weight_kg"])
        fat = float(current["body_fat_pct"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (
        math.isfinite(weight)
        and 20 <= weight <= 300
        and math.isfinite(fat)
        and 1 <= fat <= 70
    ):
        return None
    return weight, fat


def _upload_with_deadline(
    client: Any, timestamp: str, weight: float, fat: float, deadline: float
) -> Any:
    """Bound every SDK upload POST, including its internal 401 replay."""
    transport = client.client
    session = transport._api_session
    upload_url = transport._resolve_url(client.garmin_connect_upload)
    request = session.request

    def guarded_request(method: str, url: str, **kwargs: Any) -> Any:
        if method.upper() == "POST" and url == upload_url:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Garmin upload deadline expired")
            kwargs["timeout"] = min(float(kwargs.get("timeout", 15)), remaining)
        return request(method, url, **kwargs)

    session.request = guarded_request
    try:
        return client.add_body_composition(
            timestamp=timestamp, weight=weight, percent_fat=fat
        )
    finally:
        session.request = request


def _outcome(response: Any) -> str:
    if not isinstance(response, dict):
        return "uncertain"
    result = response.get("detailedImportResult")
    if not isinstance(result, dict):
        return "uncertain"
    failures = result.get("failures")
    successes = result.get("successes")
    if isinstance(failures, list) and failures:
        return (
            "rejected" if isinstance(successes, list) and not successes else "uncertain"
        )
    if (
        isinstance(successes, list)
        and any(isinstance(item, dict) and item for item in successes)
        and isinstance(failures, list)
        and not failures
    ):
        return "success"
    return "uncertain"
