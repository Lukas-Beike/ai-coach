"""Focused tests for Coach activity read-tool orchestration."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from activity_row_support import SnapshotActivityRows
from canonical_detail_support import NOW, open_manager, seed_intervals_activity

from backend.activities.activity_reference import ActivityReferences
from backend.activities.detail_projection import (
    COACH_ACTIVITY_DETAIL_MAX_LAPS,
    COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS,
)
from backend.canonical.vocabulary import MetricKind
from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.coach.context import coach_context_json_size
from backend.errors import AppError
from backend.http_api.compact_activity_rows import CompactActivityRows
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.runtime.ports import ObservationSourceSelector
from backend.sync.activity_detail_canonical import CanonicalDetailWriter
from backend.sync.canonical_table_reader import CanonicalTableReader

LEGACY_KEYS = {
    "activity",
    "session_analysis",
    "activity_id",
    "local_activity_id",
    "snapshot_synced_at",
}


class CoachActivityReadToolServiceTests(unittest.TestCase):
    def test_report_defaults_to_requested_period_without_unrelated_analysis_reads(self):
        report = Mock()
        report.read.return_value = {"start": "2026-09-01", "totals": {"sessions": 2}}
        records = SimpleNamespace(endurance=Mock(), comparisons=Mock())
        derived = SimpleNamespace(
            impact=Mock(), body_history=Mock(), sleep_timing_variability=Mock()
        )
        reports = SimpleNamespace(
            report=report,
            records=records,
            derived=derived,
            profiles=SimpleNamespace(power_profiles=Mock()),
            season=SimpleNamespace(season=Mock()),
            timezone=lambda: "UTC",
        )
        service = CoachActivityReadToolService(
            Mock(), Mock(), Mock(), date.today, reports
        )
        result = service.execute(
            "get_training_report", {"start": "2026-09-01", "days": 7}
        )
        self.assertEqual(result["report"]["totals"]["sessions"], 2)
        records.endurance.assert_not_called()
        derived.impact.assert_not_called()
        report.read.assert_called_once_with({"start": "2026-09-01", "days": 7}, "UTC")
        self.assertEqual(result["projection"]["requested_sections"], ["report"])

    def test_report_can_select_comparisons_and_rejects_unknown_section(self):
        report = Mock()
        records = SimpleNamespace(comparisons=Mock(), endurance=Mock())
        records.comparisons.return_value = {"status": "insufficient_data", "groups": []}
        reports = SimpleNamespace(
            report=report,
            records=records,
            derived=SimpleNamespace(
                impact=Mock(), body_history=Mock(), sleep_timing_variability=Mock()
            ),
            profiles=SimpleNamespace(power_profiles=Mock()),
            season=SimpleNamespace(season=Mock()),
            timezone=lambda: "UTC",
        )
        service = CoachActivityReadToolService(
            Mock(), Mock(), Mock(), date.today, reports
        )
        result = service.execute("get_training_report", {"sections": ["comparisons"]})
        self.assertEqual(result["comparisons"]["status"], "insufficient_data")
        report.read.assert_not_called()
        with self.assertRaises(AppError):
            service.execute("get_training_report", {"sections": ["unknown"]})

    def test_report_can_select_body_history_and_sleep_timing_variability(self):
        report = Mock()
        derived = SimpleNamespace(body_history=Mock(), sleep_timing_variability=Mock())
        derived.body_history.return_value = {"weight": []}
        derived.sleep_timing_variability.return_value = {"status": "ok"}
        reports = SimpleNamespace(
            report=report,
            records=SimpleNamespace(endurance=Mock(), comparisons=Mock()),
            derived=derived,
            profiles=SimpleNamespace(power_profiles=Mock()),
            season=SimpleNamespace(season=Mock()),
            timezone=lambda: "UTC",
        )
        service = CoachActivityReadToolService(
            Mock(), Mock(), Mock(), date.today, reports
        )
        result = service.execute(
            "get_training_report",
            {"sections": ["body_history", "sleep_timing_variability"]},
        )
        self.assertEqual(result["body_history"], {"weight": []})
        self.assertEqual(result["sleep_timing_variability"]["status"], "ok")
        report.read.assert_not_called()

    def test_retired_sleep_regularity_section_is_rejected(self):
        service = CoachActivityReadToolService(
            Mock(), Mock(), Mock(), date.today, Mock()
        )
        with self.assertRaises(AppError) as raised:
            service.execute("get_training_report", {"sections": ["sleep_regularity"]})
        self.assertEqual(400, raised.exception.status)

    def test_recent_activities_applies_defaults_bounds_and_today(self):
        activity_read = Mock()
        activity_read.recent.return_value = {"activities": []}
        today = date(2026, 9, 23)
        service = CoachActivityReadToolService(
            activity_read, Mock(), Mock(), lambda: today
        )

        result = service.execute("list_recent_activities", {})

        self.assertEqual(result, {"ok": True, "activities": []})
        activity_read.recent.assert_called_once_with(30, 100, today=today)
        activity_read.reset_mock()
        service.execute("list_recent_activities", {"days": 9999, "limit": 0})
        activity_read.recent.assert_called_once_with(3660, 1, today=today)

    def test_recent_activities_invalid_values_preserve_app_error_contract(self):
        service = CoachActivityReadToolService(Mock(), Mock(), Mock(), date.today)

        for arguments in ({"days": "bad"}, {"limit": None}):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(AppError) as caught,
            ):
                service.execute("list_recent_activities", arguments)
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(
                caught.exception.message,
                "Aktivitätszeitraum oder Limit ist ungültig.",
            )
            self.assertEqual(caught.exception.reason, "invalid_list_request")

    def test_detail_returns_the_v1_document_with_its_envelope(self):
        raw_activity = {
            "id": "synthetic-1",
            "name": "Synthetic tempo",
            "type": "Run",
            "start_date_local": "2026-09-22T07:00:00",
            "average_speed": 3.2,
            "average_heartrate": 166,
            "average_watts": 245,
            "provider_extra": "must not pass",
        }
        other = {**raw_activity, "id": "synthetic-2", "name": "Other run"}
        manager = _sessions(self, raw_activity, other)
        _store_streams(manager, "synthetic-1", {"time": [0, 1], "watts": [200, 250]})
        garmin = Mock(recent_view=Mock(return_value={"recent_wellness": []}))
        profile = Mock(get=Mock(return_value={"weight_kg": "70"}))
        service = _detail_tool(manager, [raw_activity, other], garmin, profile)

        result = service.execute("get_activity_details", {"activity_id": "synthetic-1"})

        self.assertTrue(result["ok"])
        self.assertEqual("activity_detail.v1", result["contract"])
        self.assertEqual("Synthetic tempo", result["session"]["name"])
        self.assertEqual(
            [200, 250], result["streams"]["channels"]["power_w"]["values"]
        )
        self.assertEqual(
            "bounded sanitized activity_detail.v1 document of exactly one local "
            "session; providers: Intervals.icu; recorded by: unknown",
            result["data_scope"],
        )
        self.assertTrue(result["activity_validation"]["available"])
        self.assertEqual(
            "synthetic-1", result["activity_validation"]["activity"]["activity_id"]
        )
        self.assertEqual(
            {"activity_feedback", "equipment", "activity_validation"},
            {"activity_feedback", "equipment", "activity_validation"} & set(result),
        )
        self.assertFalse(LEGACY_KEYS & set(result))
        text = json.dumps(result)
        self.assertNotIn("provider_extra", text)
        self.assertNotIn("synthetic-2", text)
        self.assertNotIn("Other run", text)
        garmin.recent_view.assert_called_once_with()
        profile.get.assert_called_once_with()

    def test_detail_result_size_does_not_grow_with_the_recording(self):
        raw_activity = {
            "id": "synthetic-1",
            "type": "Ride",
            "start_date_local": "2026-09-22T07:00:00",
        }
        laps = [
            {"type": "work", "start_time": index * 30, "end_time": index * 30 + 30}
            for index in range(COACH_ACTIVITY_DETAIL_MAX_LAPS)
        ]
        sizes = []
        for points in (8_000, 16_000):
            with self.subTest(points=points):
                manager = _sessions(self, raw_activity)
                _store_streams(
                    manager,
                    "synthetic-1",
                    {
                        "time": list(range(points)),
                        "watts": [200 + index % 50 for index in range(points)],
                        "heartrate": [140 + index % 20 for index in range(points)],
                        "cadence": [90] * points,
                        "velocity_smooth": [9.5] * points,
                        "altitude": [100.0] * points,
                        "distance": [index * 9.5 for index in range(points)],
                    },
                    laps=laps,
                )
                service = _detail_tool(
                    manager,
                    [raw_activity],
                    Mock(recent_view=Mock(return_value={})),
                    Mock(get=Mock(return_value={})),
                )
                result = service.execute(
                    "get_activity_details", {"activity_id": "synthetic-1"}
                )
                streams = result["streams"]
                self.assertTrue(result["detail_data"]["display_sampled"])
                self.assertEqual(
                    COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS, len(streams["time_s"])
                )
                for channel in streams["channels"].values():
                    self.assertLessEqual(
                        len(channel["values"]), COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS
                    )
                self.assertLessEqual(
                    len(result["laps"]["laps"]), COACH_ACTIVITY_DETAIL_MAX_LAPS
                )
                sizes.append(coach_context_json_size(result))
        # Twice the recording only lengthens the sampled numbers, not the lists.
        self.assertLess(sizes[1], sizes[0] * 1.1)

    def test_unknown_tool_is_unclaimed_and_invalid_detail_ids_keep_error(self):
        activity_read = Mock()
        service = CoachActivityReadToolService(
            activity_read, Mock(), Mock(), date.today
        )
        self.assertIsNone(service.execute("list_workout_library", {}))
        activity_read.detail.side_effect = AppError(
            400,
            "Die Aktivität konnte nicht eindeutig zugeordnet werden.",
            reason="invalid_activity_request",
        )

        with self.assertRaises(AppError) as caught:
            service.execute("get_activity_details", {"activity_id": " "})
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.reason, "invalid_activity_request")

    def test_detail_passes_canonical_inputs_resolved_once_per_call(self):
        selector, service = _canonical_activity_tool(
            self, _activity_snapshot([{"id": "2026-09-22"}])
        )
        with patch(
            "backend.performance.activity_read_service.current_performance_context",
            return_value={},
        ) as project:
            service.execute("get_activity_details", {"activity_id": "synthetic-1"})
        canonical = project.call_args.kwargs["canonical"]
        self.assertEqual(canonical.wellness_day, date(2026, 9, 22))
        self.assertIsNotNone(canonical.recovery)
        selector.reader_for.assert_called_once()
        served_kinds = {
            call.args[1]
            for call in selector.reader_for.return_value.observations.call_args_list
        }
        self.assertIn(MetricKind.CTL, served_kinds)
        self.assertIn(MetricKind.ATL, served_kinds)

    def test_detail_without_wellness_rows_keeps_legacy_call_shape(self):
        selector, service = _canonical_activity_tool(self, _activity_snapshot([]))
        with patch(
            "backend.performance.activity_read_service.current_performance_context",
            return_value={},
        ) as project:
            service.execute("get_activity_details", {"activity_id": "synthetic-1"})
        self.assertNotIn("canonical", project.call_args.kwargs)
        # The wellness observations are now read to find the days, once per call.
        selector.reader_for.assert_called_once()


def _activity_snapshot(recent_wellness: list[dict]) -> dict:
    raw_activity = {
        "id": "synthetic-1",
        "type": "Run",
        "start_date_local": "2026-09-22T07:00:00",
        "moving_time": 3600,
    }
    return {
        "synced_at": "synthetic-sync",
        "recent_wellness": recent_wellness,
        "recent_activities": [{"id": "synthetic-1", "type": "Run"}],
        "raw_provider_data": {"activities": [raw_activity]},
    }


def _sessions(case: unittest.TestCase, *activities: dict):
    """Return a temporary database holding the canonical sessions of ``activities``."""
    directory = tempfile.TemporaryDirectory()
    case.addCleanup(directory.cleanup)
    manager = open_manager(directory.name)
    case.addCleanup(manager.close)
    for activity in activities:
        fields = {key: value for key, value in activity.items() if key != "id"}
        seed_intervals_activity(manager, activity["id"], **fields)
    return manager


def _store_streams(manager, activity_id: str, streams: dict, laps=None) -> None:
    activity = {"streams": streams, **({} if laps is None else {"laps": laps})}
    with manager.unit_of_work() as db:
        CanonicalDetailWriter().write_legacy(
            db,
            record={
                "activity_id": activity_id,
                "activity": activity,
                "observed_at": NOW,
                "full_resolution": True,
            },
            now=NOW,
        )


def _detail_tool(manager, activities: list[dict], garmin, profile):
    """Wire the Coach tool over the canonical detail read of ``manager``."""
    snapshot_repository = Mock()
    snapshot_repository.latest_snapshot.return_value = {
        "synced_at": "synthetic-sync",
        "recent_activities": [],
        "raw_provider_data": {"activities": activities},
    }
    feedback = Mock()
    feedback.list.return_value = []
    activity_read = ActivityAnalysisReadService(
        manager,
        snapshot_repository,
        CompactActivityRows(SnapshotActivityRows(snapshot_repository)),
        feedback,
        references=ActivityReferences(manager),
        session_records=CanonicalTableReader().session_activities,
    )
    return CoachActivityReadToolService(
        activity_read, garmin, profile, lambda: date(2026, 9, 23)
    )


def _canonical_activity_tool(case: unittest.TestCase, snapshot: dict):
    """Wire the coach tool over the real activity service with a selecting source."""
    sessions = _sessions(case, *snapshot["raw_provider_data"]["activities"])
    inner = Mock()
    inner.observations.return_value = ()
    selector = Mock(spec=ObservationSourceSelector)
    selector.reader_for.return_value = inner
    snapshot_reader = Mock()
    snapshot_reader.latest_snapshot.return_value = snapshot
    feedback = Mock()
    feedback.list.return_value = []
    manager = MagicMock()
    activity_read = ActivityAnalysisReadService(
        sessions,
        snapshot_reader,
        CompactActivityRows(SnapshotActivityRows(snapshot_reader)),
        feedback,
        canonical=CanonicalPerformanceSource(
            database_manager=lambda: manager,
            observation_reader=lambda: selector,
        ),
        references=ActivityReferences(sessions),
        session_records=CanonicalTableReader().session_activities,
    )
    garmin = Mock(recent_view=Mock(return_value={}))
    profile = Mock(get=Mock(return_value={}))
    service = CoachActivityReadToolService(
        activity_read, garmin, profile, lambda: date(2026, 9, 23)
    )
    return selector, service


if __name__ == "__main__":
    unittest.main()
