"""Bounded Intervals activity summary refresh for the Analysis sessions view."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import quote

from backend.activities.duplicates import deduplicate_api_records
from backend.config import Config
from backend.db import DatabaseManager
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.planning.context import compact_snapshot
from backend.providers.descriptors import INTERVALS_ID
from backend.providers.intervals import IntervalsApiClient
from backend.providers.snapshot_projection import intervals_row_local_date
from backend.sync.canonical_ingest import (
    ingest_intervals_partial_snapshot,
    ingest_intervals_snapshot,
    intervals_deletion_window,
)
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.snapshot_storage import SnapshotStorage

RECENT_ACTIVITY_DAYS = 42
RECENT_ACTIVITY_LIMIT = 500
_REFRESH_LOCK = threading.Lock()


class AnalysisSessionsRefreshService:
    """Refresh only recent Intervals activity summaries; preserve all other data."""

    def __init__(
        self,
        *,
        config: Config,
        database_manager: DatabaseManager,
        provider_client: IntervalsApiClient,
        event_publisher: Any,
        observer: SyncOperationObserver,
        resync_gate: ProviderResyncGate,
        zone_provider: Callable[[], tzinfo | None],
        utc_now: Callable[[], str],
        all_sync_days: int,
        earliest_date: date,
        snapshot_storage: SnapshotStorage,
        lock: Any = _REFRESH_LOCK,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._provider_client = provider_client
        self._event_publisher = event_publisher
        self._observer = observer
        self._resync_gate = resync_gate
        self._zone_provider = zone_provider
        self._utc_now = utc_now
        self._all_sync_days = all_sync_days
        self._earliest_date = earliest_date
        self._snapshot_storage = snapshot_storage
        self._lock = lock

    def refresh(self) -> dict[str, Any]:
        with (
            self._observer.observe(INTERVALS_ID, "activities") as scope,
            self._resync_gate.operation(),
        ):
            result = self._refresh_inner()
            scope.result = result
            return result

    def _refresh_inner(self) -> dict[str, Any]:
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR, reason="not_configured")
        if not self._lock.acquire(blocking=False):
            return {"status": "already_running"}
        try:
            end = self._configured_today()
            start = end - timedelta(days=RECENT_ACTIVITY_DAYS - 1)
            athlete = quote(self._config.intervals_athlete_id, safe="")
            payload = self._provider_client.get(
                f"/athlete/{athlete}/activities",
                {
                    "oldest": start.isoformat(),
                    "newest": end.isoformat(),
                    "limit": RECENT_ACTIVITY_LIMIT,
                    "offset": 0,
                },
            )
            if not isinstance(payload, list) or any(
                not isinstance(item, dict) for item in payload
            ):
                raise AppError(502, "Ungültige Einheiten vom Anbieter.")
            if len(payload) > RECENT_ACTIVITY_LIMIT:
                raise AppError(502, "Zu viele Einheiten vom Anbieter.")

            fetched_at = self._utc_now()
            recent = compact_snapshot(
                {},
                payload,
                [],
                [],
                RECENT_ACTIVITY_DAYS,
                all_sync_days=self._all_sync_days,
                synced_at=fetched_at,
            )
            existing = self._snapshot_storage.merge_base() or {}
            zone = self._zone_provider() or UTC
            deletion_window = intervals_deletion_window(
                today=end,
                activity_days=RECENT_ACTIVITY_DAYS,
                all_sync_days=RECENT_ACTIVITY_DAYS + 1,
                earliest_date=self._earliest_date,
            )
            previous_raw = existing.get("raw_provider_data")
            if not isinstance(previous_raw, dict):
                previous_raw = {}
            merged = dict(existing)
            merged["synced_at"] = existing.get("synced_at") or fetched_at
            truncated = len(payload) == RECENT_ACTIVITY_LIMIT
            merged["activities_synced_at"] = existing.get(
                "activities_synced_at", existing.get("synced_at")
            )
            merged["recent_activities"] = self._merge_activity_rows(
                recent["recent_activities"],
                existing.get("recent_activities"),
                deletion_window.start,
                deletion_window.end,
                fetched_at,
                zone,
                truncated=truncated,
            )
            merged["raw_provider_data"] = {
                **previous_raw,
                "activities": self._merge_activity_rows(
                    payload,
                    previous_raw.get("activities"),
                    deletion_window.start,
                    deletion_window.end,
                    fetched_at,
                    zone,
                    truncated=truncated,
                ),
            }
            merged["provider_sync"] = {
                **(existing.get("provider_sync") or {}),
                "analysis_activity_refresh": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "records": len(payload),
                    "limit": RECENT_ACTIVITY_LIMIT,
                },
            }
            with self._database_manager.unit_of_work() as db:
                ingest_snapshot = {
                    **recent,
                    "raw_provider_data": {"activities": payload},
                }
                if truncated:
                    ingest_intervals_partial_snapshot(db, ingest_snapshot, zone=zone)
                else:
                    ingest_intervals_snapshot(
                        db,
                        ingest_snapshot,
                        zone=zone,
                        activity_days=RECENT_ACTIVITY_DAYS,
                        all_sync_days=RECENT_ACTIVITY_DAYS + 1,
                        earliest_date=self._earliest_date,
                    )
                # Coverage is provider-wide, while this read fetches activities
                # only. Keep the prior summary and its freshness unchanged.
                self._snapshot_storage.save(
                    db, merged, zone=zone, update_full_sync=None
                )

            self._publish_ready()
            return {
                "status": "partial",
                "activities": len(payload),
                "truncated": truncated,
                "reconciliation_pending": True,
                "window_days": RECENT_ACTIVITY_DAYS,
                "limit": RECENT_ACTIVITY_LIMIT,
                "refreshed_at": fetched_at,
                "limitations": [
                    "Die Randtage dieses Teilfensters bleiben bis zu einer vollständigen Synchronisierung unverändert."
                ],
            }
        finally:
            self._lock.release()

    @staticmethod
    def _merge_activity_rows(
        fetched: list[dict[str, Any]],
        previous: object,
        start: Any,
        end: Any,
        fetched_at: str,
        zone: tzinfo,
        *,
        truncated: bool,
    ) -> list[dict[str, Any]]:
        old_rows = previous if isinstance(previous, list) else []
        if truncated:
            retained = old_rows
        else:
            retrieved_at = datetime.fromisoformat(fetched_at)
            retained = [
                row
                for row in old_rows
                if not isinstance(row, dict)
                or (
                    day := intervals_row_local_date(
                        row, zone=zone, retrieved_at=retrieved_at
                    )
                )
                is None
                or day < start
                or day > end
            ]
        return deduplicate_api_records(fetched + retained)

    def _configured_today(self):
        # The provider window uses athlete local time when available.
        zone = self._zone_provider() or UTC
        return self._utc_now_date(zone)

    def _utc_now_date(self, zone: tzinfo):
        value = datetime.fromisoformat(self._utc_now())
        return value.astimezone(zone).date() if value.tzinfo else value.date()

    def _publish_ready(self) -> None:
        payload = {"provider": INTERVALS_ID, "area": "activities", "status": "ready"}
        publish = getattr(self._event_publisher, "publish", None)
        if publish is not None:
            publish("provider", payload)
        else:
            self._event_publisher("provider", payload)
