"""Cohesive local training analysis read use cases."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import (
    stored_activity_key,
    summary_duration_s,
    summary_is_indoor,
    summary_local_date,
)
from backend.activities.detail_analysis_reads import analysis_summaries
from backend.activities.detail_store import summary_fingerprint
from backend.canonical.stored_sports import resolve_workout_sport
from backend.errors import AppError
from backend.performance.canonical_inputs import (
    CanonicalPerformanceSource,
    activity_summaries_for,
    activity_summaries_with_sync_time,
)
from backend.performance.comparisons import recurring_training_comparisons
from backend.performance.season_inputs import (
    SeasonSource,
    read_activity_summaries,
    read_season_load_inputs,
)
from backend.performance.tag_impact import tag_impact
from backend.performance.training_report import training_report


def report_sport(value: Any) -> str | None:
    """Return the report sport filter: "all" or a canonical sport, else None.

    A previous Intervals.icu-style token (for example "VirtualRide") resolves to
    its canonical sport, as the other HTTP and Coach inputs accept it.
    """
    text = str(value or "all").strip()
    if text == "all":
        return text
    resolved = resolve_workout_sport(text) if len(text) <= 40 else None
    return None if resolved is None else resolved.sport.value


class TrainingRecordsService:
    def __init__(
        self,
        *,
        database_manager: Any,
        read_equipment: Callable[[], dict[str, Any]],
        read_record: Callable[[str, str], dict[str, Any]] | None,
        canonical: CanonicalPerformanceSource,
    ) -> None:
        self._canonical = canonical
        self._database_manager = database_manager
        self._read_equipment = read_equipment
        self._read_record = read_record

    def training_records(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        values = values or {}
        if values.get("record_type") or values.get("record_id"):
            kind, record_id = (
                values.get("record_type"),
                str(values.get("record_id") or ""),
            )
            if kind != "equipment":
                raise AppError(400, "Unbekannte Datensatzart.")
            try:
                uuid.UUID(record_id)
            except ValueError as exc:
                raise AppError(400, "Ungültige Datensatz-ID.") from exc
            if self._read_record is None:
                raise AppError(
                    503, "Einzelne Trainingsdatensätze sind nicht verfügbar."
                )
            return self._read_record(kind, record_id)
        return {"equipment": self._read_equipment()}

    def comparisons(self) -> dict[str, Any]:
        return recurring_training_comparisons(self.observations())

    def observations(self) -> list[dict[str, Any]]:
        summaries = activity_summaries_for(self._canonical)
        fingerprints = self._fingerprints()
        known = {stored_activity_key(summary): summary for summary in summaries}
        records = []
        for stored in analysis_summaries(self._database_manager):
            summary = known.get(stored["activity_id"])
            if summary is None or stored["summary_sha256"] != fingerprints.get(
                stored["activity_id"]
            ):
                continue
            sport = summary.get("sport")
            records.append(
                {
                    **stored,
                    "date": summary_local_date(summary),
                    "sport": sport,
                    "activity_type": sport,
                    "environment": "indoor"
                    if summary_is_indoor(summary)
                    else "outdoor",
                    "source": summary.get("source") or "Intervals.icu",
                    "name": summary.get("name"),
                    "average_temp": summary.get("avg_temp_c"),
                    "duration": summary_duration_s(summary),
                    "device": str(summary.get("recorded_by") or "unknown")[:200],
                }
            )
        records.sort(key=lambda row: row["date"], reverse=True)
        return records

    def _fingerprints(self) -> dict[str, str]:
        """Fingerprint of each stored Intervals.icu payload, by stored activity key.

        A stored analysis carries the fingerprint of the payload it was computed
        from; only the raw rows of the same reader can tell whether it is current.
        """
        reader = self._canonical.activity_summary_reader()
        read_rows = getattr(reader, "activity_rows", None)
        if read_rows is None:
            return {}
        with self._canonical.database_manager().reader() as db:
            rows = read_rows(db)
        return {str(row.get("id")): summary_fingerprint(row) for row in rows}

    def endurance(self) -> dict[str, Any]:
        records = [
            row for row in self.observations() if row["aerobic"].get("status") == "ok"
        ]
        return {
            "status": "ok" if records else "insufficient_data",
            "activities": records,
            "scope": "Bis zu 100 lokal gespeicherte Detaildatensätze; nur aktuelle Aktivitäten mit geeigneten Originaldaten.",
            "comparison": "Individual observations, no inferred fitness trend. Compare sport, duration, intensity, terrain, temperature and indoor/outdoor conditions.",
        }


class TrainingProfileSelectionService:
    def __init__(self, today: Callable[[], date]) -> None:
        self._today = today

    def power_profiles(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        today = self._today()
        eligible_records = [
            row for row in records if str(row.get("date") or "") <= today.isoformat()
        ]
        valid = [
            row
            for row in eligible_records
            if (row.get("power_profile") or {}).get("status") == "ok"
            or (row.get("running_profile") or {}).get("status") == "ok"
        ]
        # Keep one compatibility winner per sport/duration.
        compatibility = self._compatibility_profiles(eligible_records)
        # Keep all cached records in the window so coverage reports include
        # activities whose streams are incomplete and therefore yield unknown
        # points. Candidates below still require a measured profile point.
        windows = {
            str(days): self._profile_window(eligible_records, today, days)
            for days in (28, 90)
        }
        return {
            "status": "ok" if compatibility or valid else "insufficient_data",
            "best": compatibility,
            "activities": records,
            "windows": windows,
            "running": {
                "name": "running_best_efforts",
                "type": "running",
                "windows": {key: value["running"] for key, value in windows.items()},
            },
            "method": "original-stream-integral-v1",
            "scope": "Beobachtete Fenster aus lokal gespeicherten Aktivitäten. Fehlende oder ungültige Fenster bleiben unbekannt; keine FTP- oder Tempo-Schätzung.",
        }

    @staticmethod
    def _compatibility_profiles(
        eligible_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        compatibility = []
        for environment in ("outdoor", "indoor"):
            for duration in (5, 60, 300, 1200):
                candidates = [
                    (p.get("watts"), row)
                    for row in eligible_records
                    if row.get("sport") == "ride"
                    and row.get("environment") == environment
                    for p in (row.get("power_profile") or {}).get("points", [])
                    if p.get("duration_seconds") == duration
                    and p.get("watts") is not None
                ]
                if candidates:
                    watts, row = max(candidates, key=lambda item: item[0])
                    compatibility.append(
                        {
                            "sport": "ride",
                            "type": row.get("activity_type") or "ride",
                            "environment": environment,
                            "duration_seconds": duration,
                            "watts": watts,
                            "activity_id": row["activity_id"],
                            "date": row["date"],
                            "observed_at": row["observed_at"],
                            "source": row.get("source") or "original activity stream",
                            "device": row.get("device") or "unknown",
                        }
                    )
        return compatibility

    @staticmethod
    def _profile_window(
        records: list[dict[str, Any]], today: date, days: int
    ) -> dict[str, Any]:
        start = today - timedelta(days=days - 1)
        eligible = [
            row
            for row in records
            if start.isoformat() <= str(row.get("date") or "") <= today.isoformat()
        ]
        source = "Intervals.icu original streams via local activity detail cache"
        usable = [
            row
            for row in eligible
            if (row.get("power_profile") or {}).get("status") == "ok"
            or (row.get("running_profile") or {}).get("status") == "ok"
        ]
        result: dict[str, Any] = {
            "date_start": start.isoformat(),
            "date_end": today.isoformat(),
            "source": source,
            "cache_coverage": {
                "records": len(eligible),
                "cached_records": len(eligible),
                "usable_records": len(usable),
                "unknown_records": len(eligible) - len(usable),
                "eligible_activities": [row["activity_id"] for row in eligible],
            },
            "power": [],
            "running": {"speed": [], "distance": []},
        }
        for environment in ("outdoor", "indoor"):
            for duration in (5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600):
                candidates = _power_candidates(eligible, environment, duration)
                result["power"].append(
                    TrainingProfileSelectionService._winner(
                        candidates,
                        ("ride", environment),
                        duration,
                        "watts",
                        "duration_seconds",
                    )
                )
        for key, field, values in (
            ("speed", "speed_mps", (60, 300, 1200)),
            ("distance", "seconds", (1000, 5000)),
        ):
            for value in values:
                candidates = _running_candidates(eligible, key, field, value)
                result["running"][key].append(
                    TrainingProfileSelectionService._winner(
                        candidates,
                        ("run", None),
                        value,
                        field,
                        "duration_seconds" if key == "speed" else "distance_meters",
                        minimum=key == "distance",
                    )
                )
        return result

    @staticmethod
    def _winner(
        candidates: list[tuple[dict[str, Any], dict[str, Any]]],
        sport: tuple[str, str | None],
        value: int,
        field: str,
        label: str,
        minimum: bool = False,
    ) -> dict[str, Any]:
        if not candidates:
            name, wanted_environment = sport
            return {
                "sport": name,
                **(
                    {}
                    if wanted_environment is None
                    else {"environment": wanted_environment}
                ),
                label: value,
                field: None,
                "status": "unknown",
                "reason": "No complete valid local window.",
            }
        point, row = (min if minimum else max)(
            candidates, key=lambda item: item[0][field]
        )
        actual_sport = row.get("sport", sport[0])
        return {
            "sport": actual_sport,
            "type": row.get("activity_type") or actual_sport,
            "environment": row.get("environment") or "outdoor",
            label: value,
            field: point[field],
            "activity_id": row.get("activity_id"),
            "date": row.get("date"),
            "observed_at": row.get("observed_at"),
            "status": "ok",
            "source": point.get("source")
            or row.get("source")
            or "original activity stream",
            "device": row.get("device") or "unknown",
        }


class TrainingReportReadService:
    def __init__(
        self,
        *,
        read_snapshot: Callable[[], Any],
        read_plan: Callable[[], Any],
        read_checkins: Callable[[], Any],
        read_feedback: Callable[[], list[dict[str, Any]]],
        today: Callable[[], date],
        load_scenarios: Callable[..., dict[str, Any]],
        season_source: SeasonSource,
        canonical: CanonicalPerformanceSource,
    ) -> None:
        self._read_snapshot = read_snapshot
        self._read_plan = read_plan
        self._read_checkins = read_checkins
        self._read_feedback = read_feedback
        self._today = today
        self._load_scenarios = load_scenarios
        self._season_source = season_source
        self._canonical = canonical

    def scenarios(
        self, values: dict[str, Any], timezone: str = "UTC"
    ) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise AppError(400, "Das Szenario muss ein Objekt sein.")
        today = self._today()
        with self._season_source.database_manager().read_snapshot() as db:
            snapshot = self._read_snapshot()
            inputs = read_season_load_inputs(
                self._season_source, db, today=today, timezone=timezone
            )
        return self._load_scenarios(
            snapshot or {},
            self._read_plan() or {},
            today,
            values,
            inputs=inputs,
        )

    def read(self, values: dict[str, Any], timezone: str = "UTC") -> dict[str, Any]:
        today = self._today()
        try:
            start = date.fromisoformat(
                str(
                    values.get("start")
                    or (today - timedelta(days=today.weekday())).isoformat()
                )
            )
            days = int(values.get("days", 7))
        except (TypeError, ValueError) as exc:
            raise AppError(400, "Ungültiger Berichtszeitraum.") from exc
        sport = report_sport(values.get("sport"))
        if (
            days not in {7, 28}
            or not date(2010, 1, 1) <= start <= today
            or sport is None
        ):
            raise AppError(400, "Ungültiger Berichtszeitraum oder Sportfilter.")
        summaries, observed_at = activity_summaries_with_sync_time(self._canonical)
        return training_report(
            start=start,
            days=days,
            today=today,
            sport=sport,
            plan=self._read_plan(),
            checkins=self._read_checkins(),
            activity_feedback=self._read_feedback(),
            timezone=timezone,
            activity_summaries=summaries,
            observed_at=observed_at,
        )


class TrainingDerivedReadService:
    def __init__(
        self,
        *,
        read_checkins: Callable[[], Any],
        read_recovery: Callable[[], dict[str, Any]],
        read_performance: Callable[[], dict[str, Any]],
        today: Callable[[], date],
        canonical: CanonicalPerformanceSource,
    ) -> None:
        self._read_checkins = read_checkins
        self._read_recovery = read_recovery
        self._read_performance = read_performance
        self._today = today
        self._canonical = canonical

    def impact(self, timezone: str = "UTC") -> dict[str, Any]:
        return tag_impact(
            self._read_checkins(),
            self._read_recovery(),
            self._today(),
            timezone,
            activity_summaries=activity_summaries_for(self._canonical),
        )

    def body_history(self) -> dict[str, Any]:
        history = self._read_performance().get("history")
        body = history.get("body") if isinstance(history, dict) else None
        return body if isinstance(body, dict) else {"status": "insufficient_data"}

    def sleep_timing_variability(self) -> dict[str, Any]:
        regularity = self._read_recovery().get("regularity")
        if isinstance(regularity, dict):
            return regularity
        return {"status": "insufficient_data"}


class TrainingSeasonReadService:
    def __init__(
        self,
        *,
        read_snapshot: Callable[[], Any],
        read_competitions: Callable[[], list[dict[str, Any]]],
        read_observations: Callable[[], list[dict[str, Any]]],
        today: Callable[[], date],
        season_preparation: Callable[..., dict[str, Any]],
        season_source: SeasonSource,
    ) -> None:
        self._read_snapshot = read_snapshot
        self._read_competitions = read_competitions
        self._read_observations = read_observations
        self._today = today
        self._season_preparation = season_preparation
        self._season_source = season_source

    def season(self, timezone: str = "UTC") -> dict[str, Any]:
        with self._season_source.database_manager().read_snapshot() as db:
            return self._season_preparation(
                self._read_snapshot() or {},
                self._read_competitions(),
                self._today(),
                timezone,
                self._read_observations(),
                activity_summaries=lambda start, end: read_activity_summaries(
                    self._season_source, db, start, end
                ),
            )


@dataclass(frozen=True)
class TrainingReportServices:
    records: TrainingRecordsService
    profiles: TrainingProfileSelectionService
    report: TrainingReportReadService
    derived: TrainingDerivedReadService
    season: TrainingSeasonReadService
    timezone: Callable[[], str]


def _power_candidates(
    eligible: list[dict[str, Any]], environment: str, duration: int
) -> list:
    return [
        (point, row)
        for row in eligible
        if row.get("sport") == "ride" and row.get("environment") == environment
        for point in (row.get("power_profile") or {}).get("duration_curve", [])
        if point.get("duration_seconds") == duration and point.get("watts") is not None
    ]


def _running_candidates(
    eligible: list[dict[str, Any]], key: str, field: str, value: int
) -> list:
    return [
        (point, row)
        for row in eligible
        if row.get("sport") == "run"
        for point in (row.get("running_profile") or {}).get(key, [])
        if point.get(field) is not None
        and point.get("duration_seconds", point.get("distance_meters")) == value
    ]
