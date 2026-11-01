"""Cohesive local training analysis read use cases."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.performance.canonical_inputs import (
    CanonicalPerformanceSource,
    activity_summaries_and_rows,
    activity_summaries_for,
    activity_summaries_with_sync_time,
)
from backend.performance.comparisons import recurring_training_comparisons
from backend.performance.mean_max_curve import (
    SessionCurve,
    SessionCurveReader,
    input_fingerprint,
)
from backend.performance.power_profile import (
    LEGACY_POWER_DURATIONS,
    METHOD_ID,
    METHOD_VERSION,
    POWER_DURATIONS,
    RUNNING_DISTANCES,
    RUNNING_DURATIONS,
)
from backend.performance.season_inputs import (
    SeasonSource,
    read_activity_summaries,
    read_season_load_inputs,
)
from backend.performance.session_rpe_load import FeedbackLookup, feedback_by_session
from backend.performance.tag_impact import tag_impact
from backend.performance.training_report import training_report

# Analysis windows of the power and running profiles, shortest first.
PROFILE_WINDOW_DAYS = (28, 90)


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
        summaries, rows = activity_summaries_and_rows(self._canonical)
        fingerprints = {str(row.get("id")): summary_fingerprint(row) for row in rows}
        known = {stored_activity_key(summary): summary for summary in summaries}
        records = []
        for stored in analysis_summaries(self._database_manager):
            summary = known.get(stored["activity_id"])
            if summary is None or stored["summary_sha256"] != fingerprints.get(
                stored["activity_id"]
            ):
                continue
            records.append(
                {
                    **stored,
                    **summary_fields(summary),
                    # Stored analyses come from the Intervals.icu detail.
                    "source": "Intervals.icu"
                    if ProviderId.INTERVALS.value in (summary.get("record_ids") or {})
                    else summary.get("source") or "Intervals.icu",
                    "average_temp": summary.get("avg_temp_c"),
                    "duration": summary_duration_s(summary),
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
    def __init__(
        self,
        today: Callable[[], date],
        *,
        canonical: CanonicalPerformanceSource | None = None,
        curves: SessionCurveReader | None = None,
    ) -> None:
        self._today = today
        self._canonical = canonical
        self._curves = curves

    def curve_records(self) -> list[dict[str, Any]]:
        """Ride and run sessions of the longest window with their session curves.

        Sessions without full-resolution streams stay in the list with empty
        profiles, so the coverage counts them as unknown.
        """
        if self._canonical is None or self._curves is None:
            raise RuntimeError("power profiles need the canonical source and curves")
        reader = self._canonical.activity_summary_reader()
        if reader is None:
            raise RuntimeError("power profiles need the canonical activity summaries")
        today = self._today()
        start = today - timedelta(days=PROFILE_WINDOW_DAYS[-1] - 1)
        # One spare day on each side; the local date below decides membership.
        first, last = start - timedelta(days=1), today + timedelta(days=1)
        with self._canonical.database_manager().read_snapshot() as db:
            sessions = [
                summary
                for summary in reader.activity_summaries(db, start=first, end=last)
                if summary.get("sport") in ("ride", "run")
                and start.isoformat()
                <= summary_local_date(summary)
                <= today.isoformat()
            ]
            fingerprints = {
                str(row.get("id")): summary_fingerprint(row)
                for row in reader.activity_rows(db, start=first, end=last)
            }
            curves = self._curves.curves(
                db, [str(summary.get("id") or "") for summary in sessions], fingerprints
            )
        records = [
            _curve_record(summary, curves.get(str(summary.get("id") or "")))
            for summary in sessions
        ]
        records.sort(key=lambda row: row["date"], reverse=True)
        return records

    def power_profiles(
        self, records: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        if records is None:
            records = self.curve_records()
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
            for days in PROFILE_WINDOW_DAYS
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
            "method": METHOD_ID,
            "method_version": METHOD_VERSION,
            "input_fingerprint": _records_fingerprint(eligible_records),
            "scope": "Beobachtete Bestwerte der letzten 90 Tage aus lokal gespeicherten Messreihen in voller Auflösung; heruntergerechnete Reihen zählen nicht. Fehlende oder ungültige Fenster bleiben unbekannt. Bestwerte mit gleicher effort_group stammen aus derselben Belastung und sind voneinander abhängig. Keine FTP-, CP- oder Tempo-Schätzung.",
        }

    @staticmethod
    def _compatibility_profiles(
        eligible_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        compatibility = []
        for environment in ("outdoor", "indoor"):
            for duration in LEGACY_POWER_DURATIONS:
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
        source = "local full-resolution activity streams"
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
            "input_fingerprint": _records_fingerprint(eligible),
            "power": [],
            "running": {"speed": [], "distance": []},
        }
        for environment in ("outdoor", "indoor"):
            for duration in POWER_DURATIONS:
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
            ("speed", "speed_mps", RUNNING_DURATIONS),
            ("distance", "seconds", RUNNING_DISTANCES),
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
        _mark_effort_groups(result["power"])
        _mark_effort_groups(
            [*result["running"]["speed"], *result["running"]["distance"]]
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
            "start_seconds": point.get("start_seconds"),
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
        read_synced_at: Callable[[Any], str | None],
        read_plan: Callable[[], Any],
        read_checkins: Callable[[], Any],
        read_feedback: Callable[[], list[dict[str, Any]]],
        today: Callable[[], date],
        load_scenarios: Callable[..., dict[str, Any]],
        season_source: SeasonSource,
        canonical: CanonicalPerformanceSource,
        session_feedback: FeedbackLookup | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._read_synced_at = read_synced_at
        self._read_plan = read_plan
        self._read_checkins = read_checkins
        self._read_feedback = read_feedback
        self._session_feedback = session_feedback
        self._now = now
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
            synced_at = self._read_synced_at(db)
            inputs = read_season_load_inputs(
                self._season_source, db, today=today, timezone=timezone
            )
        return self._load_scenarios(
            synced_at,
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
        period = [
            summary
            for summary in summaries
            if start.isoformat()
            <= summary_local_date(summary, timezone)
            <= min(today, start + timedelta(days=days - 1)).isoformat()
        ]
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
            session_feedback=feedback_by_session(period, self._session_feedback),
            computed_at=None
            if self._now is None
            else self._now().isoformat(timespec="seconds"),
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
        read_synced_at: Callable[[Any], str | None],
        read_competitions: Callable[[], list[dict[str, Any]]],
        read_observations: Callable[[], list[dict[str, Any]]],
        today: Callable[[], date],
        season_preparation: Callable[..., dict[str, Any]],
        season_source: SeasonSource,
    ) -> None:
        self._read_synced_at = read_synced_at
        self._read_competitions = read_competitions
        self._read_observations = read_observations
        self._today = today
        self._season_preparation = season_preparation
        self._season_source = season_source

    def season(self, timezone: str = "UTC") -> dict[str, Any]:
        with self._season_source.database_manager().read_snapshot() as db:
            return self._season_preparation(
                self._read_synced_at(db),
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


def summary_fields(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Session fields every analysis row takes from its canonical summary."""
    sport = summary.get("sport")
    return {
        "date": summary_local_date(summary),
        "sport": sport,
        "activity_type": sport,
        "environment": "indoor" if summary_is_indoor(summary) else "outdoor",
        "name": summary.get("name"),
        "device": str(
            summary.get("device_name") or summary.get("recorded_by") or "unknown"
        )[:200],
    }


def _curve_record(
    summary: Mapping[str, Any], curve: SessionCurve | None
) -> dict[str, Any]:
    fields = summary_fields(summary)
    profile = None
    if curve is not None:
        profile = curve.power if fields["sport"] == "ride" else curve.running
    return {
        **fields,
        "activity_id": stored_activity_key(summary),
        "observed_at": summary.get("started_at"),
        # Best values are credited to the providers of the streams they read.
        "source": None if profile is None else profile.get("source"),
        "power_profile": {} if curve is None else curve.power,
        "running_profile": {} if curve is None else curve.running,
        "fingerprint": None if curve is None else curve.fingerprint,
    }


def _records_fingerprint(records: list[dict[str, Any]]) -> str:
    """Every input that decides a window: session identity, day, kind and curve."""
    return input_fingerprint(
        [
            row.get("activity_id"),
            row.get("date"),
            row.get("sport"),
            row.get("environment"),
            row.get("fingerprint"),
        ]
        for row in records
    )


def _effort_span(point: dict[str, Any]) -> tuple[float, float] | None:
    start = point.get("start_seconds")
    length = point.get("duration_seconds")
    if length is None:
        length = point.get("seconds")
    if point.get("status") != "ok" or start is None or length is None:
        return None
    return float(start), float(start) + float(length)


def _mark_effort_groups(points: list[dict[str, Any]]) -> None:
    """Give best values whose windows overlap in one session the same effort group.

    Overlapping windows of one effort are not independent observations, so a
    later model fit must not treat them as separate efforts.
    """
    marked = [
        (point, span) for point in points if (span := _effort_span(point)) is not None
    ]
    parent = list(range(len(marked)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left, (point, span) in enumerate(marked):
        for right in range(left + 1, len(marked)):
            other, other_span = marked[right]
            if (
                point.get("activity_id") == other.get("activity_id")
                and span[0] < other_span[1]
                and other_span[0] < span[1]
            ):
                parent[root(right)] = root(left)
    groups: dict[int, int] = {}
    for index, (point, _span) in enumerate(marked):
        point["effort_group"] = groups.setdefault(root(index), len(groups) + 1)


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
