"""Public and Coach projections of the canonical Garmin values and sync status."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.canonical.activity_summary import ActivitySummary
from backend.canonical.vocabulary import ProviderId
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.observability import Redactor
from backend.performance import freshness as performance_freshness
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance.freshness import GarminSyncStatus
from backend.performance.garmin_canonical import (
    GarminCanonicalState,
    read_garmin_recovery,
    read_garmin_state,
)
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.provider_credentials import garmin_tokens_connected
from backend.providers.garmin import GarminClientFactory
from backend.runtime.ports import (
    ActivityRowReader,
    ActivitySummaryReader,
    ObservationReader,
)
from backend.sync.garmin import (
    RECENT_VIEW_DAYS,
    GarminPayloadService,
    GarminSyncStateService,
)
from backend.sync.garmin_service import GarminSyncService

# The recovery context shows the latest record; two weeks cover a missed sync.
COACH_RECOVERY_DAYS = 14


@dataclass(frozen=True)
class GarminCanonicalSources:
    """Lazy canonical readers; the selector decides per read whether tables serve."""

    activity_rows: Callable[[], ActivityRowReader]
    observations: Callable[[], ObservationReader]
    activity_summaries: Callable[[], ActivitySummaryReader]


def _garmin_sessions(summaries: tuple[ActivitySummary, ...]) -> tuple[int, int]:
    """Count the Garmin sessions: kept ones, and those an Intervals.icu record shares.

    As before the canonical sessions, a Garmin activity is skipped as a duplicate
    only of an Intervals.icu recording; a Garmin copy beside Wahoo alone stays.
    """
    garmin = ProviderId.GARMIN.value
    intervals = ProviderId.INTERVALS.value
    sessions = [
        record_ids
        for summary in summaries
        if isinstance(record_ids := summary.get("record_ids"), dict)
        and garmin in record_ids
    ]
    shared = sum(1 for record_ids in sessions if intervals in record_ids)
    return len(sessions) - shared, shared


class GarminProjectionService:
    """Build read-only Garmin state views from explicitly owned dependencies."""

    def __init__(
        self,
        config: Config,
        garmin_payload_service: GarminPayloadService,
        garmin_sync_service: GarminSyncService,
        garmin_sync_state_service: GarminSyncStateService,
        morning_body_battery_service: MorningBodyBatteryService,
        garmin_client_factory: GarminClientFactory,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        redactor: Redactor,
        local_now: Callable[[], datetime],
        *,
        canonical: GarminCanonicalSources,
    ) -> None:
        self._canonical = canonical
        self._config = config
        self._garmin_payload_service = garmin_payload_service
        self._garmin_sync_service = garmin_sync_service
        self._garmin_sync_state_service = garmin_sync_state_service
        self._morning_body_battery_service = morning_body_battery_service
        self._garmin_client_factory = garmin_client_factory
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._redactor = redactor
        self._local_now = local_now

    def _canonical_read(
        self, observations: ObservationReader | None = None
    ) -> tuple[GarminCanonicalState, tuple[ActivitySummary, ...]]:
        """Read the Garmin observations and the recent sessions from one source."""
        sources = self._canonical
        start = self._local_now().date() - timedelta(days=RECENT_VIEW_DAYS - 1)
        with self._database_manager.reader() as db:
            state = read_garmin_state(observations or sources.observations(), db)
            summaries = sources.activity_summaries().activity_summaries(db, start=start)
        return state, summaries

    def public_state(
        self,
        status: GarminSyncStatus | None = None,
        *,
        observations: ObservationReader | None = None,
    ) -> dict[str, Any]:
        """Project the Garmin card: canonical values, ``status`` for the sync status.

        ``status`` reuses the caller's own read of the sync status.
        """
        if status is None:
            status = self._garmin_payload_service.sync_status()
        today = self._local_now().date()
        state, summaries = self._canonical_read(observations)
        performance_metrics = performance_garmin_metrics.garmin_performance_metrics(
            status, today, state.metrics
        )
        activities, skipped = _garmin_sessions(summaries)
        parsed_error = self._garmin_sync_state_service.core_error_entries() or None
        parsed_error = self._redactor.sanitize_log_value(parsed_error)
        with self._database_manager.reader() as db:
            last_sync_at = self._key_value_repository.get(db, "last_garmin_sync_at")
            metric_export_status = self._key_value_repository.get(
                db, "last_garmin_metric_export_status"
            )
            metric_export_enabled = (
                self._key_value_repository.get(db, "garmin_metric_export_enabled")
                == "true"
            )
            tokens_connected = garmin_tokens_connected(
                lambda key: self._key_value_repository.get(db, key),
                self._config.garmin_tokenstore,
            )

        return {
            "available": self._garmin_sync_service.available(),
            "configured": bool(
                self._config.garmin_fixture_path
                or self._config.garmin_email
                or tokens_connected
            ),
            "source": status.source
            or ("library" if self._garmin_client_factory.available() else None),
            "last_sync_at": last_sync_at,
            **(
                {"metric_export_status": metric_export_status}
                if metric_export_status
                else {}
            ),
            "metric_export_enabled": metric_export_enabled,
            "last_error": parsed_error,
            "pagination": dict(status.pagination),
            "source_freshness": performance_freshness.garmin_source_freshness(
                status, today
            ),
            "activities": activities,
            "duplicate_activities_skipped": skipped,
            "has_sleep": state.has_sleep,
            "has_hrv": state.has_hrv,
            "has_resting_hr": state.has_resting_hr,
            "has_thresholds": any(
                performance_metrics[key]["value"] is not None
                for key in (
                    "cycling_ftp_watts",
                    "run_threshold_watts",
                    "run_threshold_pace_seconds_per_km",
                    "bike_threshold_hr_bpm",
                    "run_threshold_hr_bpm",
                )
            ),
            "has_readiness": state.has_readiness,
            "has_race_predictions": bool(state.metrics.race_predictions),
            "has_weight": performance_metrics["weight_kg"]["value"] is not None,
            "has_max_hr": any(
                performance_metrics[key]["value"] is not None
                for key in ("cycling_max_hr_bpm", "running_max_hr_bpm")
            ),
            "has_vo2max": any(
                performance_metrics[key]["value"] is not None
                for key in (
                    "cycling_vo2max_ml_kg_min",
                    "running_vo2max_ml_kg_min",
                )
            ),
            "has_estimated_run_times": any(
                performance_metrics[key]["value"] is not None
                for key in (
                    "run_5k_seconds",
                    "run_10k_seconds",
                    "run_half_marathon_seconds",
                    "run_marathon_seconds",
                )
            ),
            "morning_body_battery": self._morning_body_battery_service.current(),
        }

    def coach_context(self, include_performance: bool = False) -> dict[str, Any]:
        """The latest canonical Garmin recovery records and the sync status.

        The status, the recovery records and the performance values are read in
        one read transaction, so a sync committing in between cannot mix them.
        """
        today = self._local_now().date()
        with self._database_manager.reader() as db:
            status = self._garmin_payload_service.sync_status_in(db)
            observations = self._canonical.observations()
            recovery = read_garmin_recovery(
                observations,
                db,
                start=today - timedelta(days=COACH_RECOVERY_DAYS - 1),
            )
            state = read_garmin_state(observations, db) if include_performance else None
        context = {
            "synced_at": status.synced_at,
            "start": status.start,
            "end": status.end,
            "source_freshness": performance_freshness.garmin_source_freshness(
                status, today
            ),
            "recovery": {
                **recovery,
                "body_battery": self._morning_body_battery_service.current() or {},
            },
            "scope": "Nur der aktuellste Garmin-Recovery-Datensatz. Leistungswerte und Aktivitäten stehen in den deduplizierten bzw. abgeleiteten Abschnitten.",
            "errors": [
                self._redactor.redact_text(str(error))[:300]
                for error in status.errors
                if error
            ][:20],
        }
        if state is not None:
            context["performance"] = (
                performance_garmin_metrics.garmin_performance_context(
                    status, today, state.metrics
                )
            )
            context["scope"] = (
                "Kein Intervals.icu-Snapshot vorhanden; Garmin-Leistungswerte und der aktuellste Recovery-Datensatz werden als Fallback verwendet."
            )
        return context
