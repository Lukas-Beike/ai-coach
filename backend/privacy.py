"""Local privacy deletion, the privacy export and their builder."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.activities.route_store import clear_routes
from backend.athlete.profile import DEFAULT_PROFILE, ProfileService
from backend.backup.database import EXPORT_TIME_LIMIT_SECONDS, MIN_EXPORT_FREE_BYTES
from backend.backup.export import (
    PrivacyArchiveExportConfig,
    PrivacyArchiveExportService,
)
from backend.backup.recovery_copies import RecoveryCopies
from backend.canonical.vocabulary import RemoteEntityKind
from backend.db import activity_detail_store
from backend.db.manager import DATABASE_LOCK, DatabaseManager, secure_deletion
from backend.db.repositories import KeyValueRepository
from backend.diagnostics.logs import RecentLogEntriesService
from backend.errors import AppError
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.competition_service import CompetitionService
from backend.planning.revision import PlanningRevisionService
from backend.provider_credentials import (
    GARMIN_TOKENSTORE_DISCONNECTED,
    GARMIN_TOKENSTORE_STATE_KEY,
)
from backend.providers.openai_requests import OpenAIResponsesClient
from backend.runtime import clock as runtime_clock
from backend.runtime import maintenance as runtime_maintenance
from backend.runtime.maintenance import MaintenanceGate

MAX_PRIVACY_EXPORT_BYTES = 100_000_000
PRIVACY_DELETE_CONFIRMATION_TEXT = "LOKALE DATEN LÖSCHEN"
GPS_TRACKS_DELETE_CONFIRMATION_TEXT = "GPS-SPUREN LÖSCHEN"

PRIVACY_DELETE_SCOPE = (
    (
        "chats",
        "Chats, Coach-Werkzeug- und Aktionsprotokolle",
        (
            "messages",
            "coach_commands",
            "coach_plan_artifacts",
            "coach_action_proposals",
        ),
    ),
    ("snapshots", "Trainings-Snapshots", ("snapshots",)),
    (
        "library",
        "Workout-Bibliothek und geplante Einheiten",
        ("workout_library", "planned_units", "remote_links"),
    ),
    (
        "competitions",
        "Wettkämpfe und Sync-Vormerkungen",
        ("competitions", "competition_sync_tombstones", "remote_links"),
    ),
    ("plans", "Trainingspläne", ("training_plans", "planning_state")),
    ("checkins", "Tages-Check-ins", ("athlete_checkins",)),
    ("feedback", "Aktivitätsfeedback", ("activity_feedback",)),
    (
        "nutrition",
        "Ernährungsprotokolle und Kalorientracking",
        (
            "nutrition_logs",
            "nutrition_sync_dates",
            "nutrition_templates",
            "nutrition_products",
        ),
    ),
    ("adaptive", "Adaptive Plananpassungen", ("plan_adjustments",)),
    (
        "calendars",
        "Kalenderquellen, Kandidaten, lokale Kalenderereignisse und ihre Einordnung",
        (
            "public_event_sources",
            "public_event_candidates",
            "external_calendar_events",
            "external_calendar_decisions",
        ),
    ),
    ("sessions", "Anmeldesitzungen", ("sessions",)),
    (
        "settings",
        "Profil, Einstellungen, Zugangsdaten, Garmin-Verbindung und Garmin-Tokens, Syncstatus und lokale Caches",
        ("kv",),
    ),
    ("history", "Lokale Änderungshistorie", ("change_history",)),
    (
        "provider_status",
        "Bereinigter Provider-Refresh-Verlauf",
        (
            "provider_refresh_history",
            "sync_job_items",
            "sync_jobs",
            "provider_sync_cursors",
        ),
    ),
    (
        "provider_data",
        "Kanonische Provider-Aktivitäten, Beobachtungen und Provider-Records",
        # Children first: detail rows reference their set, sets reference
        # activity_records and analysis rows and records reference sessions.
        # The schema v15 sleep, zone, status and gear tables and the schema
        # v17 power curve reference none.
        (
            "observations",
            "power_curve_points",
            "power_curve_fetches",
            "sleep_periods",
            "zone_configurations",
            "categorical_observations",
            "gear_activity_links",
            "gear_items",
            "activity_stream_channels",
            "activity_laps",
            "activity_zone_times",
            "activity_strength_sets",
            "activity_detail_sets",
            "activity_detail_analysis",
            "activity_records",
            "activity_sessions",
            "provider_records",
            "remote_links",
        ),
    ),
)
# remote_links is one table listed in three groups: each group reports (and the
# deletion removes) the links of the entities it owns. Metric-export links point
# at observations, so they belong to the provider data group.
_REMOTE_LINK_KINDS_BY_CATEGORY = {
    "library": (RemoteEntityKind.LIBRARY_WORKOUT, RemoteEntityKind.PLANNED_UNIT),
    "competitions": (RemoteEntityKind.COMPETITION,),
    "provider_data": (RemoteEntityKind.OBSERVATION,),
}
# Not a database table: files beside the database, reported next to the categories.
RECOVERY_COPIES_CATEGORY = "recovery_copies"
RECOVERY_COPIES_LABEL = (
    "Wiederherstellungskopien der Datenbank und Bereinigungsmarkierung"
)
# The server log files beside the database, erased last (#2137, G-209).
LOG_FILES_CATEGORY = "server_logs"
LOG_FILES_LABEL = "Server-Protokolldateien"
PRIVACY_REMOTE_SCOPE = (
    "Intervals.icu-Trainings-, Kalender- und Bibliotheksdaten bleiben unverändert.",
    (
        "Garmin-Konto und Garmin-Daten bleiben unverändert. Eine ältere "
        "Garmin-Token-Datei im Datenverzeichnis bleibt erhalten, wird aber nicht "
        "mehr verwendet."
    ),
    (
        "Wahoo-Konto und Wahoo-Daten bleiben unverändert; der Zugriff dieser "
        "App wird bei Wahoo widerrufen."
    ),
    "Externe Kalenderquelle und deren Anbieter bleiben unverändert.",
)


@dataclass(frozen=True)
class PrivacyDeleteDependencies:
    database_manager: DatabaseManager
    database_lock: AbstractContextManager[Any]
    key_value_repository: KeyValueRepository
    maintenance_gate: MaintenanceGate
    profile_mutation_coordinator: AbstractContextManager[Any]
    planning_revision_service: PlanningRevisionService
    openai_client: OpenAIResponsesClient
    logger: logging.Logger
    diagnostics_suspended: Callable[[], AbstractContextManager[None]]
    # Re-derives the runtime configuration once stored credentials are wiped.
    refresh_credentials: Callable[[], Any] | None = None
    # Discards a pending Garmin MFA login so it cannot store tokens afterwards.
    cancel_garmin_login: Callable[[], None] | None = None
    # Best-effort Wahoo disconnect: bumps the connection generation and revokes
    # the grant at Wahoo before the stored tokens are wiped.
    disconnect_wahoo: Callable[[], dict[str, Any]] | None = None
    # Copies saved by a restore or by the Intervals.icu purge of an earlier
    # release; erased with the data.
    recovery_copies: RecoveryCopies | None = None
    # Stops a running Coach turn so the maintenance drain does not wait for it.
    cancel_coach_turns: Callable[[], None] | None = None
    # The server log files; erased after everything else, so no later warning
    # of this erasure is lost.
    log_files: RecentLogEntriesService | None = None
    utc_now: Callable[[], str] = lambda: datetime.now(UTC).isoformat()


class PrivacyDeleteService:
    """Own the preview and maintenance-gated deletion of local user data."""

    def __init__(self, dependencies: PrivacyDeleteDependencies):
        self._dependencies = dependencies

    @staticmethod
    def _counts(db: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for category, _label, tables in PRIVACY_DELETE_SCOPE:
            counts[category] = sum(
                PrivacyDeleteService._table_count(db, category, table)
                for table in tables
            )
        return counts

    @staticmethod
    def _table_count(db: Any, category: str, table: str) -> int:
        if table == "remote_links":
            kinds = [kind.value for kind in _REMOTE_LINK_KINDS_BY_CATEGORY[category]]
            row = db.execute(
                "SELECT COUNT(*) AS count FROM remote_links "
                f"WHERE entity_kind IN ({', '.join('?' for _ in kinds)})",
                kinds,
            ).fetchone()
        else:
            row = db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])

    def preview(self) -> dict[str, Any]:
        dependencies = self._dependencies
        with dependencies.database_manager.read_snapshot() as db:
            counts = self._counts(db)
        categories = [
            {"id": category, "label": label, "records": counts[category]}
            for category, label, _tables in PRIVACY_DELETE_SCOPE
        ]
        if dependencies.recovery_copies is not None:
            categories.append(
                {
                    "id": RECOVERY_COPIES_CATEGORY,
                    "label": RECOVERY_COPIES_LABEL,
                    "records": dependencies.recovery_copies.count(),
                }
            )
        if dependencies.log_files is not None:
            categories.append(
                {
                    "id": LOG_FILES_CATEGORY,
                    "label": LOG_FILES_LABEL,
                    "records": dependencies.log_files.count(),
                }
            )
        return {
            "status": "preview",
            "confirmation_text": PRIVACY_DELETE_CONFIRMATION_TEXT,
            "categories": categories,
            "remote_untouched": list(PRIVACY_REMOTE_SCOPE),
            "openai_conversation": (
                "Eine vorhandene OpenAI-Konversation wird vor dem Löschen zum Löschen angefragt; "
                "ein Fehlschlag wird separat ausgewiesen. Gewöhnliche Coach-Antworten speichert "
                "OpenAI nicht (store: false). Antworten des Anhang-Dialogs und von "
                "Hintergrundläufen liegen dort bis zur Aufbewahrungsfrist von OpenAI; diese App "
                "löscht sie nicht einzeln."
            ),
        }

    def gps_state(self) -> dict[str, Any]:
        """The "GPS-Spuren speichern" setting and how many activities hold a track."""
        with self._dependencies.database_manager.read_snapshot() as db:
            return {
                "enabled": activity_detail_store.gps_tracks_enabled(db),
                "stored_tracks": activity_detail_store.stored_track_count(db),
                "confirmation_text": GPS_TRACKS_DELETE_CONFIRMATION_TEXT,
            }

    def set_gps_tracks(self, enabled: Any) -> dict[str, Any]:
        """Turn the storage of new GPS tracks on or off; stored tracks stay."""
        if not isinstance(enabled, bool):
            raise AppError(400, "enabled muss true oder false sein.")
        dependencies = self._dependencies
        with (
            dependencies.database_lock,
            dependencies.database_manager.unit_of_work() as db,
        ):
            dependencies.key_value_repository.set(
                db, activity_detail_store.GPS_TRACKS_KEY, "1" if enabled else "0"
            )
        return {"status": "ok", **self.gps_state()}

    def delete_gps_tracks(self, confirm: Any) -> dict[str, Any]:
        """Delete every stored GPS position and the derived routes after confirmation."""
        if confirm != GPS_TRACKS_DELETE_CONFIRMATION_TEXT:
            raise AppError(400, "Zum Löschen muss GPS-SPUREN LÖSCHEN bestätigt werden.")
        dependencies = self._dependencies
        with dependencies.maintenance_gate.restore(dependencies.cancel_coach_turns):
            with (
                dependencies.database_lock,
                dependencies.database_manager.unit_of_work() as db,
                secure_deletion(db),
            ):
                deleted = activity_detail_store.delete_stored_tracks(db)
                clear_routes(dependencies.key_value_repository, db)
            self._reclaim_after_commit()
        return {"status": "ok", "deleted_tracks": deleted, **self.gps_state()}

    def _reclaim_after_commit(self) -> None:
        """Drop the deleted pages from the database file and the WAL.

        Runs after the commit under the held maintenance gate. The delete is
        already durable, so a failure is logged and never fails the request;
        both statements are atomic and leave the data unchanged on error. The
        manager's writer excludes every other write; VACUUM cannot run inside a
        unit of work, so no lock or outer transaction wraps it.
        """
        dependencies = self._dependencies
        try:
            complete = dependencies.database_manager.reclaim_space()
        except Exception as exc:  # noqa: BLE001 - the committed delete stands
            dependencies.logger.warning(
                "Deleted database pages could not be reclaimed",
                extra={
                    "event": "privacy_space_reclaim_failed",
                    "context": {"error_class": type(exc).__name__},
                },
            )
            return
        if complete is False:
            dependencies.logger.warning(
                "Deleted database pages stay in the write-ahead log",
                extra={"event": "privacy_space_reclaim_incomplete"},
            )

    def _erase_log_files(self, deleted_counts: dict[str, int]) -> bool:
        """Erase the server log files last; report a failure, never raise it."""
        log_files = self._dependencies.log_files
        if log_files is None:
            return False
        try:
            count = log_files.count()
            log_files.clear()
        except OSError as exc:
            self._dependencies.logger.warning(
                "Server log files could not be deleted",
                extra={
                    "event": "privacy_log_files_delete_failed",
                    "context": {"error_class": type(exc).__name__},
                },
            )
            return True
        deleted_counts[LOG_FILES_CATEGORY] = count
        return False

    def delete(self, confirm: Any) -> dict[str, Any]:
        if confirm != PRIVACY_DELETE_CONFIRMATION_TEXT:
            raise AppError(
                400,
                "Zum Löschen muss LOKALE DATEN LÖSCHEN bestätigt werden.",
            )
        dependencies = self._dependencies
        with (
            dependencies.maintenance_gate.restore(dependencies.cancel_coach_turns),
            dependencies.profile_mutation_coordinator,
        ):
            with dependencies.database_manager.reader() as db:
                conversation_id = (
                    dependencies.key_value_repository.get(db, "openai_conversation_id")
                    or ""
                )
            remote_delete_attempted = bool(conversation_id)
            remote_deleted = False
            recovery_copies_failed = 0
            if conversation_id:
                try:
                    remote_deleted = dependencies.openai_client.delete_conversation(
                        conversation_id
                    )
                except Exception:
                    dependencies.logger.warning(
                        "Remote OpenAI conversation could not be deleted",
                        extra={"event": "privacy_remote_delete_failed"},
                        exc_info=True,
                    )
            if dependencies.cancel_garmin_login is not None:
                dependencies.cancel_garmin_login()
            wahoo_revoke_attempted = False
            wahoo_revoked = False
            if dependencies.disconnect_wahoo is not None:
                try:
                    outcome = dependencies.disconnect_wahoo()
                    wahoo_revoke_attempted = bool(
                        outcome.get("remote_revoke_attempted")
                    )
                    wahoo_revoked = bool(outcome.get("remote_revoked"))
                except Exception:
                    # The purge completes; the kv wipe below drops the tokens anyway.
                    wahoo_revoke_attempted = True
                    dependencies.logger.warning(
                        "Wahoo grant could not be revoked",
                        extra={"event": "privacy_wahoo_revoke_failed"},
                        exc_info=True,
                    )
            # Flushes stay blocked from before the delete until the cache is dropped,
            # so deleted diagnostics are neither served nor written back.
            with (
                dependencies.diagnostics_suspended(),
                dependencies.database_lock,
                dependencies.database_manager.unit_of_work() as db,
                secure_deletion(db),
            ):
                deleted_counts = self._counts(db)
                gps_tracks_enabled = activity_detail_store.gps_tracks_enabled(db)
                deleted_tables = dict.fromkeys(
                    table
                    for _category, _label, tables in PRIVACY_DELETE_SCOPE
                    for table in tables
                )
                for table in deleted_tables:
                    db.execute(f"DELETE FROM {table}")
                db.execute("DELETE FROM kv")
                # Keep a preserved legacy Garmin token file from being re-imported.
                dependencies.key_value_repository.set(
                    db, GARMIN_TOKENSTORE_STATE_KEY, GARMIN_TOKENSTORE_DISCONNECTED
                )
                dependencies.key_value_repository.set(
                    db, "profile", json.dumps(DEFAULT_PROFILE)
                )
                if not gps_tracks_enabled:
                    # A switched-off setting survives; absent means on (#2137, K-002).
                    dependencies.key_value_repository.set(
                        db, activity_detail_store.GPS_TRACKS_KEY, "0"
                    )
                dependencies.planning_revision_service.mark_reset_pending()
            self._reclaim_after_commit()
            if dependencies.recovery_copies is not None:
                # After the commit: a failed erase never leaves a half-wiped database.
                erased = dependencies.recovery_copies.erase()
                deleted_counts[RECOVERY_COPIES_CATEGORY] = erased.removed
                recovery_copies_failed = erased.failed
                if erased.failed:
                    dependencies.logger.warning(
                        "Recovery copies could not be deleted",
                        extra={
                            "event": "privacy_recovery_copy_delete_failed",
                            "context": {"failed": erased.failed},
                        },
                    )
            if dependencies.refresh_credentials is not None:
                dependencies.refresh_credentials()
            log_files_failed = self._erase_log_files(deleted_counts)
            return {
                "status": "ok",
                "local_data_deleted": True,
                "deleted_categories": deleted_counts,
                "recovery_copies_failed": recovery_copies_failed,
                "log_files_failed": log_files_failed,
                "remote_delete_attempted": remote_delete_attempted,
                "remote_conversation_deleted": remote_deleted,
                "wahoo_revoke_attempted": wahoo_revoke_attempted,
                "wahoo_revoked": wahoo_revoked,
                "remote_untouched": list(PRIVACY_REMOTE_SCOPE),
            }


@dataclass(frozen=True)
class PrivacyServices:
    delete_service: Callable[[], PrivacyDeleteService]
    archive_export_service: Callable[[], PrivacyArchiveExportService]


def build_privacy(
    *,
    database_manager: Callable[[], DatabaseManager],
    profile_service: Callable[[], ProfileService],
    competition_service: Callable[[], CompetitionService],
    adaptive_preview_service: Callable[[], AdaptiveReplanPreviewService],
    planning_revision_service: PlanningRevisionService,
    openai_client: Callable[[], OpenAIResponsesClient],
    local_now: Callable[[], datetime],
    diagnostics_suspended: Callable[[], AbstractContextManager[None]],
    refresh_credentials: Callable[[], Any],
    cancel_garmin_login: Callable[[], None],
    disconnect_wahoo: Callable[[], dict[str, Any]],
    cancel_coach_turns: Callable[[], None],
    log_files: Callable[[], RecentLogEntriesService],
) -> PrivacyServices:
    """The privacy export and the maintenance-gated local data purge.

    The database path and its directory come from the live database manager,
    and the lock, gate, key-value store and clock are the process-wide owners.

    Every owner is read when a service is built, so a restore, a swapped data
    directory or a replaced gate is seen by the next call. The late owners
    (diagnostics, Garmin, Wahoo, Coach) are only reached when the purge runs.
    """

    key_values = KeyValueRepository(runtime_clock.utc_now)
    logger = logging.getLogger("intervals_coach")

    def database_path() -> Path:
        return database_manager().path

    def data_dir() -> Path:
        return database_path().parent

    def delete_service() -> PrivacyDeleteService:
        return PrivacyDeleteService(
            PrivacyDeleteDependencies(
                database_manager=database_manager(),
                database_lock=DATABASE_LOCK,
                key_value_repository=key_values,
                maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
                profile_mutation_coordinator=profile_service().mutation_coordinator,
                planning_revision_service=planning_revision_service,
                openai_client=openai_client(),
                logger=logger,
                diagnostics_suspended=diagnostics_suspended,
                refresh_credentials=refresh_credentials,
                cancel_garmin_login=cancel_garmin_login,
                disconnect_wahoo=disconnect_wahoo,
                cancel_coach_turns=cancel_coach_turns,
                recovery_copies=RecoveryCopies(data_dir(), database_path().name),
                log_files=log_files(),
                utc_now=runtime_clock.utc_now,
            )
        )

    def archive_export_service() -> PrivacyArchiveExportService:
        return PrivacyArchiveExportService(
            database_manager(),
            key_values,
            profile_service(),
            competition_service(),
            adaptive_preview_service(),
            PrivacyArchiveExportConfig(
                data_dir(),
                database_path(),
                lambda: local_now().date(),
                runtime_clock.utc_now,
                maximum_bytes=MAX_PRIVACY_EXPORT_BYTES,
                minimum_free_bytes=MIN_EXPORT_FREE_BYTES,
                time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
            ),
        )

    return PrivacyServices(delete_service, archive_export_service)
