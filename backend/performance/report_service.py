"""Cohesive training report read and archive use cases."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
from backend.activities.identity import intervals_activity_device_source
from backend.errors import AppError
from backend.performance.comparisons import recurring_training_comparisons
from backend.performance.season_preparation import load_scenarios, season_preparation
from backend.performance.tag_impact import tag_impact
from backend.performance.training_report import canonical_rows, training_report
from backend.runtime.clock import utc_now as system_utc_now


class TrainingRecordsService:
    def __init__(
        self,
        *,
        database_manager: Any,
        read_snapshot: Callable[[], Any],
        read_equipment: Callable[[], dict[str, Any]],
        read_record: Callable[[str, str], dict[str, Any]] | None,
    ) -> None:
        self._database_manager = database_manager
        self._read_snapshot = read_snapshot
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
        rows, _ = canonical_rows(self._read_snapshot() or {})
        known = {str(row.get("id")): row for row in rows}
        records = []
        for stored in ActivityDetailStore(self._database_manager).analysis_summaries():
            row = known.get(stored["activity_id"])
            if row is None or stored["summary_sha256"] != summary_fingerprint(row):
                continue
            records.append(
                {
                    **stored,
                    "date": str(row.get("start_date_local") or "")[:10],
                    "sport": row.get("type") or row.get("sport"),
                    "activity_type": row.get("type") or row.get("sport"),
                    "source": row.get("source") or "Intervals.icu",
                    "name": row.get("name"),
                    "average_temp": row.get("average_temp"),
                    "duration": row.get("moving_time"),
                    "device": str(
                        row.get("device_name")
                        or intervals_activity_device_source(row)
                        or "unknown"
                    )[:200],
                }
            )
        records.sort(key=lambda row: row["date"], reverse=True)
        return records

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
        for sport in ("Ride", "VirtualRide"):
            for duration in (5, 60, 300, 1200):
                candidates = [
                    (p.get("watts"), row)
                    for row in eligible_records
                    if row.get("sport") == sport
                    for p in (row.get("power_profile") or {}).get("points", [])
                    if p.get("duration_seconds") == duration
                    and p.get("watts") is not None
                ]
                if candidates:
                    watts, row = max(candidates, key=lambda item: item[0])
                    compatibility.append(
                        {
                            "sport": sport,
                            "type": row.get("activity_type") or sport,
                            "environment": "indoor"
                            if sport == "VirtualRide"
                            else "outdoor",
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
        for sport in ("Ride", "VirtualRide"):
            for duration in (5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600):
                candidates = _power_candidates(eligible, sport, duration)
                result["power"].append(
                    TrainingProfileSelectionService._winner(
                        candidates, sport, duration, "watts", "duration_seconds"
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
                        "Run",
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
        sport: str,
        value: int,
        field: str,
        label: str,
        minimum: bool = False,
    ) -> dict[str, Any]:
        if not candidates:
            return {
                "sport": sport,
                label: value,
                field: None,
                "status": "unknown",
                "reason": "No complete valid local window.",
            }
        point, row = (min if minimum else max)(
            candidates, key=lambda item: item[0][field]
        )
        actual_sport = row.get("sport", sport)
        environment = (
            "indoor"
            if actual_sport in {"VirtualRide", "VirtualRun", "IndoorCycling"}
            else "outdoor"
        )
        return {
            "sport": actual_sport,
            "type": row.get("activity_type") or actual_sport,
            "environment": environment,
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
    ) -> None:
        self._read_snapshot = read_snapshot
        self._read_plan = read_plan
        self._read_checkins = read_checkins
        self._read_feedback = read_feedback
        self._today = today

    def scenarios(
        self, values: dict[str, Any], timezone: str = "UTC"
    ) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise AppError(400, "Das Szenario muss ein Objekt sein.")
        return load_scenarios(
            self._read_snapshot() or {},
            self._read_plan() or {},
            self._today(),
            values,
            timezone,
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
        sport = str(values.get("sport") or "all")
        if (
            days not in {7, 28}
            or not date(2010, 1, 1) <= start <= today
            or not re.fullmatch(r"[A-Za-z]{1,40}", sport)
        ):
            raise AppError(400, "Ungültiger Berichtszeitraum oder Sportfilter.")
        return training_report(
            self._read_snapshot(),
            start=start,
            days=days,
            today=today,
            sport=sport,
            plan=self._read_plan(),
            checkins=self._read_checkins(),
            activity_feedback=self._read_feedback(),
            timezone=timezone,
        )


class TrainingDerivedReadService:
    def __init__(
        self,
        *,
        read_snapshot: Callable[[], Any],
        read_checkins: Callable[[], Any],
        read_recovery: Callable[[], dict[str, Any]],
        read_performance: Callable[[], dict[str, Any]],
        today: Callable[[], date],
    ) -> None:
        self._read_snapshot = read_snapshot
        self._read_checkins = read_checkins
        self._read_recovery = read_recovery
        self._read_performance = read_performance
        self._today = today

    def impact(self, timezone: str = "UTC") -> dict[str, Any]:
        return tag_impact(
            self._read_checkins(),
            self._read_recovery(),
            self._read_snapshot() or {},
            self._today(),
            timezone,
        )

    def body_history(self) -> dict[str, Any]:
        history = self._read_performance().get("history")
        body = history.get("body") if isinstance(history, dict) else None
        return body if isinstance(body, dict) else {"status": "insufficient_data"}

    def sleep_regularity(self) -> dict[str, Any]:
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
    ) -> None:
        self._read_snapshot = read_snapshot
        self._read_competitions = read_competitions
        self._read_observations = read_observations
        self._today = today

    def season(self, timezone: str = "UTC") -> dict[str, Any]:
        return season_preparation(
            self._read_snapshot() or {},
            self._read_competitions(),
            self._today(),
            timezone,
            self._read_observations(),
        )


class TrainingReportArchiveService:
    def __init__(
        self,
        *,
        database_manager: Any,
        read_report: Callable[[dict[str, Any]], dict[str, Any]],
        utc_now: Callable[[], str] = system_utc_now,
    ) -> None:
        self._database_manager = database_manager
        self._read_report = read_report
        self._utc_now = utc_now

    def archive(self, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise AppError(400, "Der Berichtsauftrag muss ein Objekt sein.")
        if set(values) - {"start", "days", "sport"}:
            raise AppError(400, "Der Berichtsauftrag enthält unbekannte Felder.")
        report = self._read_report(values)
        serialized = json.dumps(
            report, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        report_id = hashlib.sha256(serialized.encode()).hexdigest()
        with self._database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO NOTHING",
                (f"training_report:{report_id}", serialized, self._utc_now()),
            )
        return {"ok": True, "report_id": report_id, "report": report}

    def archives(self) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            rows = db.execute(
                "SELECT key, value FROM kv WHERE key LIKE 'training_report:%' ORDER BY updated_at DESC, key LIMIT 50"
            ).fetchall()
        return {
            "reports": [
                {"id": row["key"].split(":", 1)[1], "report": json.loads(row["value"])}
                for row in rows
            ]
        }


@dataclass(frozen=True)
class TrainingReportServices:
    records: TrainingRecordsService
    profiles: TrainingProfileSelectionService
    report: TrainingReportReadService
    derived: TrainingDerivedReadService
    season: TrainingSeasonReadService
    archive: TrainingReportArchiveService
    timezone: Callable[[], str]


def _power_candidates(
    eligible: list[dict[str, Any]], sport: str, duration: int
) -> list:
    return [
        (point, row)
        for row in eligible
        if row.get("sport") == sport
        for point in (row.get("power_profile") or {}).get("duration_curve", [])
        if point.get("duration_seconds") == duration and point.get("watts") is not None
    ]


def _running_candidates(
    eligible: list[dict[str, Any]], key: str, field: str, value: int
) -> list:
    return [
        (point, row)
        for row in eligible
        if row.get("sport") in {"Run", "VirtualRun", "TrailRun"}
        for point in (row.get("running_profile") or {}).get(key, [])
        if point.get(field) is not None
        and point.get("duration_seconds", point.get("distance_meters")) == value
    ]
