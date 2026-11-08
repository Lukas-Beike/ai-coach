"""Local persistence and reconciliation for competition synchronization."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from backend.canonical.stored_sports import activity_type_environment
from backend.canonical.vocabulary import RemoteEntityKind
from backend.config import Config
from backend.db import DatabaseManager
from backend.db.remote_links import RemoteLinkRepository
from backend.db.repositories import KeyValueRepository
from backend.errors import INTERVALS_API_KEY_ERROR, AppError
from backend.observability import Redactor
from backend.planning import competitions as planning_competitions
from backend.planning.competition_service import CompetitionService
from backend.providers.intervals_workouts import planning_fields_from_intervals
from backend.runtime.events import StateEventBuffer
from backend.sync.authority import competition_push_manifest

_COMPETITION_SYNC_LOCK = threading.Lock()
_REMOTE_LINKS = RemoteLinkRepository()


def _same_remote_sport(row: dict[str, Any], data: dict[str, Any]) -> bool:
    """Return True when the remote competition names the same sport as the local row.

    Race types tell only virtual from unspecified, so indoor compares equal to
    virtual and outdoor to unspecified.
    """
    local = planning_competitions.competition_stored_sport(
        {
            "sport": row.get("sport"),
            "environment": row.get("environment"),
            "sport_detail": row.get("sport_detail"),
        }
    )
    remote = planning_competitions.competition_stored_sport(data)
    return local.sport is remote.sport and activity_type_environment(
        local.environment
    ) is activity_type_environment(remote.environment)


class CompetitionSyncReconciler:
    """Own local competition sync state while leaving provider calls outside."""

    def __init__(
        self, database_manager: DatabaseManager, uuid_factory: Callable[[], Any]
    ):
        self._database_manager = database_manager
        self._uuid_factory = uuid_factory

    def records(
        self, expected_manifest: list[dict[str, str]] | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self._database_manager.reader() as db:
            if (
                expected_manifest is not None
                and competition_push_manifest(db) != expected_manifest
            ):
                raise AppError(
                    409, "Der Wettkampfbestand hat sich seit der Freigabe geändert."
                )
            tombstones = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM competition_sync_tombstones ORDER BY created_at"
                ).fetchall()
            ]
            local_rows = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM competitions ORDER BY event_date, priority, name"
                ).fetchall()
            ]
        return tombstones, local_rows

    def clear_tombstones(self, tombstones: list[dict[str, Any]]) -> int:
        if not tombstones:
            return 0
        removed = 0
        with self._database_manager.unit_of_work() as db:
            for row in tombstones:
                result = db.execute(
                    "DELETE FROM competition_sync_tombstones WHERE id=? AND created_at=?",
                    (row["id"], row["created_at"]),
                )
                removed += max(0, result.rowcount)
        return removed

    def reconcile(
        self,
        plan: dict[str, Any],
        pushed: list[dict[str, Any]],
        local_rows: list[dict[str, Any]],
        *,
        now: str,
    ) -> dict[str, Any]:
        indexes = self._remote_indexes(plan, pushed)
        with self._database_manager.unit_of_work() as db:
            conflicts = self._synchronize_existing(db, local_rows, indexes, now)
        return {"conflicts": conflicts, "remote_events": indexes["remote_events"]}

    @staticmethod
    def _remote_indexes(
        plan: dict[str, Any], pushed: list[dict[str, Any]]
    ) -> dict[str, Any]:
        remote_events = [*plan["remote_events"], *pushed]
        return {
            "by_external": {
                str(event.get("external_id")): event
                for event in remote_events
                if event.get("external_id")
            },
            "by_id": {
                str(event.get("id")): event
                for event in remote_events
                if event.get("id")
            },
            "by_identity": plan["remote_by_identity"],
            "pushed_by_external": {
                str(event.get("external_id")): event
                for event in pushed
                if event.get("external_id")
            },
            "pushed_by_id": {
                str(event.get("id")): event for event in pushed if event.get("id")
            },
            "remote_events": remote_events,
        }

    @staticmethod
    def _remote_match(
        row: dict[str, Any], indexes: dict[str, Any]
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        external_id = str(
            row.get("external_id")
            or planning_competitions.competition_external_id(str(row["id"]))
        )
        remote = indexes["pushed_by_external"].get(external_id) or indexes[
            "by_external"
        ].get(external_id)
        if not remote and row.get("intervals_event_id"):
            remote_id = str(row["intervals_event_id"])
            remote = indexes["pushed_by_id"].get(remote_id) or indexes["by_id"].get(
                remote_id
            )
        identity_remote = (
            indexes["by_identity"].get(planning_competitions.competition_sync_key(row))
            if not row.get("intervals_event_id")
            else None
        )
        return external_id, remote, identity_remote

    @staticmethod
    def _record_conflict(
        db: Any, row: dict[str, Any], now: str, conflict: dict[str, Any] | str
    ) -> None:
        payload = (
            conflict
            if isinstance(conflict, str)
            else json.dumps(conflict, ensure_ascii=False)
        )
        db.execute(
            "UPDATE competitions SET sync_state='conflict', sync_conflict=?, updated_at=? WHERE id=?",
            (payload, now, row["id"]),
        )

    @staticmethod
    def _remote_missing_conflict(now: str) -> str:
        return json.dumps(
            {"type": "remote_missing", "detected_at": now}, ensure_ascii=False
        )

    def _reconcile_dirty(
        self,
        db: Any,
        row: dict[str, Any],
        remote: dict[str, Any] | None,
        identity_remote: dict[str, Any] | None,
        external_id: str,
        now: str,
    ) -> int:
        if identity_remote and not remote and row.get("sync_state") != "local_override":
            self._record_conflict(
                db,
                row,
                now,
                planning_competitions.competition_conflict_payload(
                    identity_remote, "identity_only", detected_at=now
                ),
            )
            return 1
        remote = remote or identity_remote
        if not planning_competitions.supported_competition_sport(
            row.get("sport"), row.get("environment")
        ):
            # The plan pushed nothing for this row, so its edit stays dirty.
            return 0
        if remote:
            db.execute(
                "UPDATE competitions SET intervals_event_id=?, external_id=?, sync_dirty=0, "
                "sync_state='synced', sync_conflict='', last_synced_at=?, updated_at=? WHERE id=?",
                (
                    str(remote.get("id") or row.get("intervals_event_id") or "")
                    or None,
                    external_id,
                    now,
                    now,
                    row["id"],
                ),
            )
            _REMOTE_LINKS.refresh_from_slots(
                db, RemoteEntityKind.COMPETITION, str(row["id"])
            )
            return 0
        if row.get("intervals_event_id"):
            self._record_conflict(db, row, now, self._remote_missing_conflict(now))
            return 1
        return 0

    def _reconcile_synced(
        self, db: Any, row: dict[str, Any], remote: dict[str, Any] | None, now: str
    ) -> int:
        """Flag a clean linked competition whose Intervals.icu event is gone.

        Intervals.icu is output only, so a clean row never takes remote values.
        """
        if remote is None and row.get("intervals_event_id"):
            self._record_conflict(db, row, now, self._remote_missing_conflict(now))
            return 1
        return 0

    def _synchronize_existing(
        self,
        db: Any,
        local_rows: list[dict[str, Any]],
        indexes: dict[str, Any],
        now: str,
    ) -> int:
        conflicts = 0
        for row in local_rows:
            current = db.execute(
                "SELECT * FROM competitions WHERE id=?", (row["id"],)
            ).fetchone()
            if current is None or dict(current) != row:
                continue
            row = self._prefer_remote_link(db, row)
            external_id, remote, identity_remote = self._remote_match(row, indexes)
            if row.get("sync_dirty"):
                conflicts += self._reconcile_dirty(
                    db, row, remote, identity_remote, external_id, now
                )
            else:
                conflicts += self._reconcile_synced(db, row, remote, now)
        return conflicts

    @staticmethod
    def _prefer_remote_link(db: Any, row: dict[str, Any]) -> dict[str, Any]:
        """Return the row with remote ids from its link; the slots are the fallback."""
        competition_id = str(row["id"])
        return {
            **row,
            "intervals_event_id": _REMOTE_LINKS.resolve_remote_id(
                db,
                RemoteEntityKind.COMPETITION,
                competition_id,
                row.get("intervals_event_id"),
            ),
            "external_id": _REMOTE_LINKS.resolve_remote_external_id(
                db,
                RemoteEntityKind.COMPETITION,
                competition_id,
                row.get("external_id"),
            ),
        }


class CompetitionSyncService:
    """Orchestrate competition sync while delegating local state to its reconciler."""

    def __init__(
        self,
        config: Config,
        client_factory: Callable[[], Any],
        reconciler: CompetitionSyncReconciler,
        competition_service: CompetitionService,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        publisher: StateEventBuffer,
        redactor: Redactor,
        logger: logging.Logger,
        now: Callable[[], str],
        competition_lock: Any | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._reconciler = reconciler
        self._competition_service = competition_service
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._publisher = publisher
        self._redactor = redactor
        self._logger = logger
        self._now = now
        self._competition_lock = (
            _COMPETITION_SYNC_LOCK if competition_lock is None else competition_lock
        )

    def sync(
        self,
        reason: str = "manual",
        expected_manifest: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        if not self._config.intervals_api_key:
            raise AppError(503, INTERVALS_API_KEY_ERROR, reason="not_configured")
        if not self._competition_lock.acquire(blocking=False):
            return {"status": "already_running"}

        try:
            self._set_kv("competition_sync_running", "1")
            self._set_kv(
                "competition_sync_status", "Zielwettkämpfe werden synchronisiert…"
            )
            client = self._client_factory()
            tombstones, local_rows = self._reconciler.records(expected_manifest)
            linked_ids = {
                str(row["intervals_event_id"])
                for row in local_rows
                if row.get("intervals_event_id")
            }
            remote_events = [
                planning_fields_from_intervals(event)
                for event in client.fetch_competition_events()
                if planning_competitions.is_remote_competition_event(event, linked_ids)
            ]
            plan = planning_competitions.competition_sync_plan(
                local_rows, tombstones, remote_events
            )
            outbound = list(plan["outbound"])
            delete_identifiers = plan["delete_identifiers"]
            deleted_remote = 0
            if delete_identifiers:
                client.bulk_delete_events(delete_identifiers)
                self._reconciler.clear_tombstones(tombstones)
                deleted_remote = len(delete_identifiers)
            pushed = (
                [
                    planning_fields_from_intervals(event)
                    for event in client.upsert_competition_events(outbound)
                ]
                if outbound
                else []
            )
            now = self._now()
            reconciled = self._reconciler.reconcile(
                plan,
                pushed,
                local_rows,
                now=now,
            )
            self._set_kv("last_competition_sync_at", now)
            self._set_kv("last_competition_sync_error", "")
            self._publisher.publish("coach", {"status": "changed"})
            return {
                "status": "ok",
                "synced_at": now,
                "pushed": len(outbound),
                "skipped": plan["skipped"],
                "skipped_items": [
                    {
                        "id": str(row["id"]),
                        "reason": planning_competitions.COMPETITION_SKIP_UNSUPPORTED_SPORT,
                    }
                    for row in local_rows
                    if row.get("sync_dirty")
                    and not planning_competitions.supported_competition_sport(
                        row.get("sport"), row.get("environment")
                    )
                ],
                "conflicts": reconciled["conflicts"],
                "removed": 0,
                "deleted_remote": deleted_remote,
                "total": len(self._competition_service.list()),
            }
        except Exception as exc:
            error = self._redactor.redact_text(str(exc))[:1000]
            self._set_kv("last_competition_sync_error", error)
            self._logger.exception(
                "Competition synchronization failed",
                extra={
                    "event": "competition_sync_failed",
                    "context": {"reason": reason},
                },
                exc_info=True,  # noqa: G202 - preserve the server error-log contract.
            )
            raise
        finally:
            try:
                self._set_kv("competition_sync_running", "0")
                self._set_kv("competition_sync_status", "")
            finally:
                self._competition_lock.release()

    def _set_kv(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)
