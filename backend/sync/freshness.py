"""Read-only projection of the freshness of configured data providers.

The projection walks the registry's freshness areas in descriptor order. Each
area reads its fallbacks and configured predicate from a ``FreshnessSource``
keyed by provider id and area name; the built-in sources live in
``backend.sync.freshness_sources``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.providers.descriptors import FreshnessArea
from backend.sync.freshness_sources import (
    DEFAULT_FRESHNESS_SOURCES,
    GARMIN_CORE_ERROR_SIGNAL,
    GARMIN_TOKENSTORE_SIGNAL,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from backend.sync.provider_runtime import FreshnessInputs, FreshnessSource
from backend.sync.refresh import cleanup_refresh_history

UTC_OFFSET_SUFFIX = "+00:00"
PROVIDER_REFRESH_RETENTION_DAYS = 30
PROVIDER_REFRESH_MAX_ROWS = 200
PROVIDER_REFRESH_STALE_SECONDS = {
    (provider_id, area.area): area.stale_after_s
    for provider_id, area in DEFAULT_PROVIDER_REGISTRY.freshness_areas()
}
PROVIDER_REFRESH_LABELS = {
    (provider_id, area.area): area.label
    for provider_id, area in DEFAULT_PROVIDER_REGISTRY.freshness_areas()
}


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", UTC_OFFSET_SUFFIX))
    except TypeError, ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _scheduled_provider_retry_at(
    db: Any, provider: str, *, now: datetime
) -> str | None:
    """Return only a future queued retry, never an advisory history timestamp."""
    rows = db.execute(
        "SELECT available_at FROM sync_jobs "
        "WHERE provider=? AND type='refresh' "
        "AND status='queued' AND available_at IS NOT NULL ORDER BY available_at",
        (provider,),
    ).fetchall()
    for row in rows:
        available_at = _parse_utc(row["available_at"])
        if available_at is not None and available_at > now:
            return available_at.isoformat()
    return None


def _provider_freshness_last_good_state(
    stale_after_s: int, last_good: Any, *, now: datetime
) -> str:
    parsed = _parse_utc(last_good)
    if parsed is None:
        return "stale" if last_good else "error"
    age = (now - parsed).total_seconds()
    return "stale" if age > stale_after_s else "fresh"


def _provider_fallback_error_code(fallback_error: bool) -> str | None:
    return "provider_error" if fallback_error else None


def _provider_freshness_error_code(
    row: Mapping[str, Any] | None, fallback_error: bool
) -> str | None:
    if row:
        error_code = str(row.get("error_code") or "")
        if error_code:
            return error_code
    return _provider_fallback_error_code(fallback_error)


def _provider_freshness_status(
    stale_after_s: int,
    configured: bool,
    row: Mapping[str, Any] | None,
    last_good: Any,
    fallback_error: bool,
    *,
    now: datetime,
) -> tuple[str, str | None]:
    if not configured:
        return "not_configured", _provider_freshness_error_code(row, fallback_error)
    if row:
        status = row["status"]
        if status == "running":
            return "syncing", _provider_fallback_error_code(fallback_error)
        if status == "error":
            state = "stale" if last_good else "error"
            return state, row.get("error_code")
        if status == "partial":
            return "partial", _provider_fallback_error_code(fallback_error)
    if last_good:
        return _provider_freshness_last_good_state(
            stale_after_s, last_good, now=now
        ), _provider_fallback_error_code(fallback_error)
    if fallback_error:
        return "error", "provider_error"
    return "never_loaded", None


def _provider_freshness_entry(
    db: Any,
    provider_id: str,
    area: FreshnessArea,
    source: FreshnessSource,
    inputs: FreshnessInputs,
    *,
    now: datetime,
) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM provider_refresh_history WHERE provider=? AND area=? ORDER BY started_at DESC LIMIT 1",
        (provider_id, area.area),
    ).fetchone()
    last_success = db.execute(
        "SELECT finished_at FROM provider_refresh_history WHERE provider=? AND area=? AND status IN ('success','partial') "
        "ORDER BY finished_at DESC LIMIT 1",
        (provider_id, area.area),
    ).fetchone()
    row = dict(row) if row else None
    configured = bool(source.configured(inputs))
    fallback = source.fallback_at(inputs)
    fallback_error = bool(source.fallback_error(inputs))
    last_attempt = row.get("started_at") if row else fallback
    last_good = (last_success["finished_at"] if last_success else None) or fallback
    scheduled_retry = _scheduled_provider_retry_at(db, provider_id, now=now)
    state, error_code = _provider_freshness_status(
        area.stale_after_s,
        configured,
        row,
        last_good,
        fallback_error,
        now=now,
    )
    return {
        "provider": provider_id,
        "area": area.area,
        "label": area.label,
        "configured": configured,
        "read_only": area.read_only,
        "state": state,
        "phase": row.get("phase") if row else None,
        "last_attempt_at": last_attempt,
        "last_success_at": last_good,
        "error_code": error_code,
        "next_retry_at": scheduled_retry,
        "stale": state == "stale",
        "has_last_good": bool(last_good),
    }


def _check_sources_match_registry(
    sources: Mapping[str, Mapping[str, FreshnessSource]],
    registry: ProviderRegistry,
) -> None:
    """Reject sources that disagree with the registry's declared areas.

    A provider with sources must supply exactly its declared area names, as the
    runtime registry requires of a binding; a source for an undeclared provider
    is an error. Failing here keeps a partial projection from being returned.
    """
    declared: dict[str, set[str]] = {}
    for provider_id, area in registry.freshness_areas():
        declared.setdefault(provider_id, set()).add(area.area)
    for provider_id, areas in sources.items():
        if provider_id not in declared:
            raise ValueError(
                f"freshness sources name undeclared provider {provider_id!r}"
            )
        if set(areas) != declared[provider_id]:
            raise ValueError(
                f"freshness sources for {provider_id!r} must cover exactly "
                "its declared freshness areas"
            )


def provider_freshness_state(
    db: Any,
    *,
    config: Config,
    get_value: Callable[[str], str | None],
    profile: Mapping[str, Any],
    garmin_has_core_error: bool,
    garmin_tokenstore_exists: bool,
    now: datetime,
    retention_days: int = PROVIDER_REFRESH_RETENTION_DAYS,
    max_rows: int = PROVIDER_REFRESH_MAX_ROWS,
    freshness_sources: Mapping[str, Mapping[str, FreshnessSource]] | None = None,
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    cleanup: bool = True,
) -> list[dict[str, Any]]:
    """Build the provider freshness projection on a caller-owned connection.

    ``cleanup=False`` skips the retention delete so the projection is a pure
    read that also works on a query-only snapshot.

    A provider without freshness sources is omitted, as it is from the runtime
    registry. A provider with sources must supply exactly its declared areas;
    mismatches raise ``ValueError`` before any database work. The cleanup
    intentionally remains uncommitted: the caller owns transaction boundaries
    and may roll back the diagnostic cleanup together with its work.
    """
    current_time = (
        now.astimezone(timezone.utc)
        if now.tzinfo is not None
        else now.replace(tzinfo=timezone.utc)
    )
    sources = (
        DEFAULT_FRESHNESS_SOURCES if freshness_sources is None else freshness_sources
    )
    _check_sources_match_registry(sources, registry)
    inputs = FreshnessInputs(
        config=config,
        get_value=get_value,
        profile=profile,
        signals={
            GARMIN_CORE_ERROR_SIGNAL: garmin_has_core_error,
            GARMIN_TOKENSTORE_SIGNAL: garmin_tokenstore_exists,
        },
    )
    cutoff = (current_time - timedelta(days=retention_days)).isoformat()
    if cleanup:
        cleanup_refresh_history(db, cutoff=cutoff, max_rows=max_rows)
    result: list[dict[str, Any]] = []
    for provider_id, area in registry.freshness_areas():
        provider_sources = sources.get(provider_id)
        if provider_sources is None:
            continue
        result.append(
            _provider_freshness_entry(
                db,
                provider_id,
                area,
                provider_sources[area.area],
                inputs,
                now=current_time,
            )
        )
    return result


class ProviderFreshnessService:
    """Own the transaction and key/value reads for provider freshness state."""

    def __init__(
        self,
        config: Config,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        now: Callable[[], datetime],
        *,
        freshness_sources: Mapping[str, Mapping[str, FreshnessSource]] | None = None,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._now = now
        self._freshness_sources = freshness_sources
        self._registry = registry

    def current(
        self,
        *,
        profile: Mapping[str, Any],
        garmin_has_core_error: bool,
        garmin_tokenstore_exists: bool,
        read_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Project freshness; ``read_only`` uses a reader and skips cleanup."""
        now = self._now()
        lease = (
            self._database_manager.reader
            if read_only
            else self._database_manager.unit_of_work
        )
        with lease() as db:
            return provider_freshness_state(
                db,
                config=self._config,
                get_value=lambda key: self._key_value_repository.get(db, key),
                profile=profile,
                garmin_has_core_error=garmin_has_core_error,
                garmin_tokenstore_exists=garmin_tokenstore_exists,
                now=now,
                freshness_sources=self._freshness_sources,
                registry=self._registry,
                cleanup=not read_only,
            )
