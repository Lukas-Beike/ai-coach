"""Coach and UI show the same value, status and scope per Epic S metric (#1433).

One synthetic fixture feeds both paths: the public performance state and the
analysis route the PWA reads, and the Coach context and `get_training_report`
tool. The Coach may drop display-only arrays but never changes a value, status,
method or period. Nothing here calls a model.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import Mock, patch

from canonical_recovery_support import recovery_only_inputs
from test_session_rpe_load import provider_rpe, summary

from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.coach.context import CoachPerformanceContextReader
from backend.http_api.analysis import AnalysisRoutes
from backend.http_api.public_performance import PublicPerformanceStateService
from backend.performance.freshness import GarminSyncStatus
from backend.performance.report_service import (
    TrainingDerivedReadService,
    TrainingReportReadService,
    TrainingReportServices,
)

TODAY = date(2026, 10, 30)
MONDAY = date(2026, 10, 19)
PROFILE = {"timezone": "UTC", "sleep_target_hours": 8}
# Display-only keys the Coach projection drops (`coach_performance_projection`).
UI_ONLY_BASELINE_KEYS = {"history", "measurement_context"}
UI_ONLY_TIMING_KEYS = {"sources", "points", "points_14", "points_84"}


def _wellness() -> list[dict[str, Any]]:
    rows = []
    for offset in range(31):
        day = TODAY - timedelta(days=offset)
        wake = datetime(day.year, day.month, day.day, 6, (offset * 7) % 50, tzinfo=UTC)
        rows.append(
            {
                "id": day.isoformat(),
                "hrv": 40 + offset % 7,
                "restingHR": 48 + offset % 4,
                "sleepSecs": 25200 + 600 * (offset % 5),
                "sleep_start_at": (wake - timedelta(hours=7)).isoformat(),
                "sleep_end_at": wake.isoformat(),
            }
        )
    return rows


def _garmin() -> dict[str, Any]:
    """A short second HRV series: it stays insufficient on both paths."""
    return {
        "hrv": [
            {
                "calendarDate": (TODAY - timedelta(days=day)).isoformat(),
                "lastNightAvg": 55,
            }
            for day in range(3)
        ]
    }


def _summaries() -> list[dict[str, Any]]:
    week = [MONDAY + timedelta(days=offset) for offset in (0, 2, 4)]
    return [
        summary("local", 60, week[0].isoformat()),
        summary("provider", 50, week[1].isoformat(), **provider_rpe(6)),
        summary("open", 40, week[2].isoformat()),
        # Outside the compared week: the Coach week report must not count it.
        summary("later", 30, TODAY.isoformat()),
    ]


def _feedback(keys: list[str]) -> list[dict[str, Any]]:
    ratings = {"local": 5, "later": 4}
    return [
        {"activity_id": key, "session_rpe": ratings[key]}
        for key in keys
        if key in ratings
    ]


def _without(row: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in keys}


class _Handler:
    path = "/api/analysis/power-profiles"

    def send_json(self, status: int, payload: Any) -> None:
        self.sent = (status, payload)


class CoachUiParityTests(unittest.TestCase):
    def setUp(self) -> None:
        summaries = _summaries()
        self.inputs = replace(
            recovery_only_inputs(_garmin(), _wellness()), activities=tuple(summaries)
        )
        garmin_payload = Mock()
        garmin_payload.sync_status.return_value = GarminSyncStatus()
        profile = Mock()
        profile.get.return_value = PROFILE
        self.ui = PublicPerformanceStateService(
            garmin_payload,
            profile,
            Mock(),
            lambda: TODAY,
            session_feedback=_feedback,
        ).from_inputs(self.inputs)["performance"]
        self.coach_context = CoachPerformanceContextReader(
            profile, garmin_payload, Mock(), lambda: TODAY
        ).current_performance(self.inputs)
        self.curves = {
            "method": "mean-max-curve",
            "method_version": 1,
            "status": "ok",
            "cycling": [{"duration_s": 180, "watts": 310, "effort_group": "a"}],
        }
        profiles = Mock()
        profiles.power_profiles.return_value = self.curves
        # Wired as `backend/http_api/assembly.py` does: the Coach report sections
        # read the services the analysis routes and the public state use.
        self.reports = TrainingReportServices(
            records=Mock(),
            profiles=profiles,
            report=TrainingReportReadService(
                read_synced_at=Mock(),
                read_plan=lambda: None,
                read_checkins=list,
                read_feedback=list,
                today=lambda: TODAY,
                load_scenarios=Mock(),
                season_source=Mock(),
                canonical=Mock(),
                session_feedback=_feedback,
            ),
            derived=TrainingDerivedReadService(
                read_checkins=list,
                read_recovery=lambda: self.ui["personal_recovery"],
                read_performance=lambda: self.ui,
                today=lambda: TODAY,
                canonical=Mock(),
            ),
            season=Mock(),
            timezone=lambda: "UTC",
        )
        self.tool = CoachActivityReadToolService(
            Mock(), garmin_payload, profile, lambda: TODAY, self.reports
        )
        self.summaries = summaries

    def coach_report(self, *sections: str, **arguments: Any) -> dict[str, Any]:
        with patch(
            "backend.performance.report_service.activity_summaries_with_sync_time",
            return_value=(self.summaries, None),
        ):
            result = self.tool.execute(
                "get_training_report", {"sections": list(sections), **arguments}
            )
        assert result is not None
        self.assertTrue(result["projection"]["complete"])
        return result

    def test_m1_week_load_matches_the_load_tab_week(self):
        coach = self.coach_report("report", start=MONDAY.isoformat(), days=7)["report"][
            "session_rpe_load"
        ]
        ui = self.ui["history"]["session_rpe_load"]
        (week,) = [item for item in ui["weeks"] if item["start"] == MONDAY.isoformat()]
        self.assertFalse(week["partial_period"])
        self.assertEqual(
            (coach["period"]["start"], coach["period"]["end"]),
            (week["start"], week["end"]),
        )
        self.assertEqual(
            coach["totals"], _without(week, {"start", "end", "partial_period"})
        )
        self.assertEqual(
            (coach["totals"]["value"], coach["totals"]["rated_sessions"]),
            (600.0, 2),
        )
        for key in (
            "metric_id",
            "method_id",
            "method_version",
            "unit",
            "status",
            "evidence_card",
            "limits",
        ):
            self.assertEqual(coach[key], ui[key], key)
        ui_days = {item["date"]: item for item in ui["days"]}
        for day in coach["days"]:
            self.assertEqual(day, ui_days[day["date"]])

    def test_m2_baselines_keep_value_status_and_scope(self):
        ui = self.ui["personal_recovery"]
        coach = self.coach_context["personal_recovery"]
        self.assertEqual(
            [_without(row, UI_ONLY_BASELINE_KEYS) for row in ui["baselines"]],
            coach["baselines"],
        )
        statuses = {
            (row["metric"], row["source_provider"]): row["status"]
            for row in coach["baselines"]
            if row["metric"] == "hrv"
        }
        self.assertEqual(
            {("hrv", "intervals"): "ok", ("hrv", "garmin"): "insufficient_data"},
            statuses,
        )
        for key in ("method", "as_of", "note", "sleep_deficits", "sleep_target_hours"):
            self.assertEqual(coach[key], ui[key], key)

    def test_m3_timing_matches_in_context_and_report_section(self):
        ui = self.ui["personal_recovery"]["regularity"]
        self.assertEqual("sleep-timing-variability-v2", ui["method"])
        coach = self.coach_context["personal_recovery"]["regularity"]
        section = self.coach_report("sleep_timing_variability")[
            "sleep_timing_variability"
        ]
        self.assertEqual(coach, section)
        self.assertEqual(
            _without(ui, UI_ONLY_TIMING_KEYS | {"series"}),
            _without(coach, {"series"}),
        )
        self.assertEqual(
            [_without(item, UI_ONLY_TIMING_KEYS) for item in ui["series"]],
            coach["series"],
        )

    def test_mean_max_curve_is_the_analysis_route_payload(self):
        handler = _Handler()
        auth = Mock()
        AnalysisRoutes(lambda: auth, lambda: self.reports).handle(handler, handler.path)
        self.assertEqual((200, self.curves), handler.sent)
        coach = self.coach_report("power_profiles")["power_profiles"]
        self.assertEqual(handler.sent[1], coach)


if __name__ == "__main__":
    unittest.main()
