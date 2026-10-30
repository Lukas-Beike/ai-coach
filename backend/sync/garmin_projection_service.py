"""Public and Coach projections of the persisted Garmin snapshot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.activities.duplicates import filter_garmin_activities
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.observability import Redactor
from backend.performance import freshness as performance_freshness
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance import garmin_projection
from backend.performance.garmin_canonical import GarminCanonicalState, read_garmin_state
from backend.performance.morning_battery_service import MorningBodyBatteryService
from backend.provider_credentials import garmin_tokens_connected
from backend.providers.garmin import GarminClientFactory
from backend.runtime.ports import ActivityRowReader, ObservationReader
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


def _recovery_presence(
    snapshot: dict[str, Any], state: GarminCanonicalState
) -> dict[str, bool]:
    """Report which recovery sections exist, from the canonical observations."""
    return {
        "sleep": state.has_sleep,
        # A weekly-only HRV section has no canonical observation; it stays on the snapshot.
        "hrv": state.has_hrv or bool(snapshot.get("hrv")),
        "resting_hr": state.has_resting_hr,
        "readiness": state.has_readiness,
    }


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

    def _observation_state(self) -> GarminCanonicalState:
        """Read the Garmin observations."""
        with self._database_manager.reader() as db:
            return read_garmin_state(self._canonical.observations(), db)

    def _canonical_read(
        self, observations: ObservationReader | None = None
    ) -> tuple[GarminCanonicalState, list[Any]]:
        """Read the Garmin observations and Intervals.icu rows from one source."""
        sources = self._canonical
        with self._database_manager.reader() as db:
            state = read_garmin_state(observations or sources.observations(), db)
            rows = list(sources.activity_rows().activity_rows(db))
        return state, rows

    def public_state(
        self,
        snapshot: dict[str, Any] | None = None,
        *,
        observations: ObservationReader | None = None,
    ) -> dict[str, Any]:
        """Project the Garmin status; ``snapshot`` reuses the caller's own read."""
        if snapshot is None:
            snapshot = self._garmin_payload_service.recent_view()
        state, intervals_rows = self._canonical_read(observations)
        performance_metrics = performance_garmin_metrics.garmin_performance_metrics(
            snapshot,
            self._local_now().date(),
            state.metrics,
        )
        filtered_activities, skipped = filter_garmin_activities(
            snapshot.get("activities"), intervals_rows
        )
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
        recovery = _recovery_presence(snapshot, state)

        return {
            "available": self._garmin_sync_service.available(),
            "configured": bool(
                self._config.garmin_fixture_path
                or self._config.garmin_email
                or tokens_connected
            ),
            "source": snapshot.get("source")
            or ("library" if self._garmin_client_factory.available() else None),
            "last_sync_at": last_sync_at,
            **(
                {"metric_export_status": metric_export_status}
                if metric_export_status
                else {}
            ),
            "metric_export_enabled": metric_export_enabled,
            "last_error": parsed_error,
            "pagination": snapshot.get("provider_sync", {}).get("pagination", {}),
            "source_freshness": performance_freshness.garmin_source_freshness(
                snapshot, self._local_now().date()
            ),
            "activities": len(filtered_activities),
            "duplicate_activities_skipped": skipped,
            "has_sleep": recovery["sleep"],
            "has_hrv": recovery["hrv"],
            "has_resting_hr": recovery["resting_hr"],
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
            "has_readiness": recovery["readiness"],
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
            "morning_body_battery": self._morning_body_battery_service.current(
                snapshot
            ),
        }

    def coach_context(self, include_performance: bool = False) -> dict[str, Any]:
        snapshot = self._garmin_payload_service.recent_view(
            RECENT_VIEW_DAYS if include_performance else COACH_RECOVERY_DAYS
        )
        context = {
            "synced_at": snapshot.get("synced_at"),
            "start": snapshot.get("start"),
            "end": snapshot.get("end"),
            "source_freshness": performance_freshness.garmin_source_freshness(
                snapshot, self._local_now().date()
            ),
            "recovery": {
                "sleep": garmin_projection.compact_garmin_recovery(
                    snapshot.get("sleep")
                ),
                "hrv": garmin_projection.compact_garmin_recovery(snapshot.get("hrv")),
                "resting_hr": garmin_projection.compact_garmin_recovery(
                    snapshot.get("resting_hr")
                ),
                "readiness": garmin_projection.compact_garmin_recovery(
                    snapshot.get("readiness")
                ),
                "body_battery": self._morning_body_battery_service.current(snapshot)
                or {},
            },
            "scope": "Nur der aktuellste Garmin-Recovery-Datensatz. Leistungswerte und Aktivitäten stehen in den deduplizierten bzw. abgeleiteten Abschnitten.",
            "errors": [
                self._redactor.redact_text(str(error))[:300]
                for error in snapshot.get("errors", [])
                if error
            ][:20],
        }
        if include_performance:
            state = self._observation_state()
            context["performance"] = (
                performance_garmin_metrics.garmin_performance_context(
                    snapshot,
                    self._local_now().date(),
                    state.metrics,
                )
            )
            context["scope"] = (
                "Kein Intervals.icu-Snapshot vorhanden; Garmin-Leistungswerte und der aktuellste Recovery-Datensatz werden als Fallback verwendet."
            )
        return context
