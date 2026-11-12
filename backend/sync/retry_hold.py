"""Hold automatic refreshes while the provider history says a retry is not due.

``provider_refresh_history`` records, for each failed refresh, when the next
attempt may start (``next_retry_at``, exponential up to the cap). The daily
scheduler consults this hold so its attempts follow that schedule instead of
the loop cadence. An ``auth_required`` failure schedules no retry at all: the
hold lasts until the athlete acts, that is until a manual refresh or restart
records a newer attempt, or the provider's stored credentials change.

Only the scheduler asks. Manual refreshes, Coach refreshes and the startup
refresh never consult the hold, so the athlete can always retry at once.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY

# A failure only the athlete can fix; no automatic retry is scheduled for it.
ATHLETE_ACTION_ERROR_CODES: Final = frozenset({"auth_required"})


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


class ProviderRetryHold:
    """Answer whether a provider's automatic refresh must wait.

    ``credential_keys`` names, per provider, the key/value rows holding its
    stored credentials; a row written after the failed attempt ended releases an
    ``auth_required`` hold.
    """

    def __init__(
        self,
        database_manager: Callable[[], Any],
        now: Callable[[], datetime],
        *,
        credential_keys: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._now = now
        self._credential_keys = credential_keys or {}

    def held(self, provider: str) -> bool:
        """Return whether the provider's latest failed refresh holds the schedule."""
        areas = [
            area.area
            for provider_id, area in DEFAULT_PROVIDER_REGISTRY.freshness_areas()
            if provider_id == provider
        ]
        if not areas:
            return False
        current = self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        with self._database_manager().reader() as db:
            for area in areas:
                row = db.execute(
                    "SELECT status, error_code, finished_at, next_retry_at "
                    "FROM provider_refresh_history WHERE provider=? AND area=? "
                    "AND status != 'skipped' ORDER BY started_at DESC LIMIT 1",
                    (provider, area),
                ).fetchone()
                if row is not None and self._row_holds(db, provider, row, current):
                    return True
        return False

    def _row_holds(
        self, db: Any, provider: str, row: Mapping[str, Any], current: datetime
    ) -> bool:
        if row["status"] != "error":
            return False
        retry_at = _parse(row["next_retry_at"])
        if retry_at is not None:
            return retry_at > current
        if row["error_code"] not in ATHLETE_ACTION_ERROR_CODES:
            return False
        return not self._credentials_changed_since(db, provider, row["finished_at"])

    def _credentials_changed_since(
        self, db: Any, provider: str, finished_at: Any
    ) -> bool:
        failed_at = _parse(finished_at)
        if failed_at is None:
            return False
        for key in self._credential_keys.get(provider, ()):
            stored = db.execute(
                "SELECT updated_at FROM kv WHERE key=?", (key,)
            ).fetchone()
            written = _parse(stored["updated_at"]) if stored is not None else None
            if written is not None and written > failed_at:
                return True
        return False
