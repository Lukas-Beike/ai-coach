"""Deterministic Coach cases for the recovery comparison wording (#1426).

Each case builds synthetic observations, projects them as the Coach receives them
and checks structure and text: what the context says about coverage and limits.
Nothing here calls a model, so it shows the context and instruction text, not how
well a model answers (docs/coach-dialogue-evaluation.md).
"""

import json
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import Mock

from canonical_recovery_support import (
    mapped_personal_recovery,
    mapped_recovery_inputs,
    recovery_only_inputs,
)
from performance_claim_support import claim_wording_violations
from test_athlete_checkins import FakeManager

from backend.athlete.checkins import CheckinService
from backend.canonical.records import MeasurementContext
from backend.canonical.vocabulary import MetricKind
from backend.coach.context import (
    CoachPerformanceContextReader,
    CoachPlanningContextReader,
    CoachStructuredContextService,
    coach_performance_projection,
)
from backend.coach.context_selection import CoachContextSelection
from backend.coach.prompt import COACH_PROMPT
from backend.db.repositories import CheckinRepository
from backend.performance.freshness import GarminSyncStatus
from backend.performance.personal_recovery import personal_recovery

TODAY = date(2026, 10, 2)
NO_CLEARANCE = "Keine Diagnose, keine Trainingsfreigabe und keine Trainingsänderung"


def _wellness(nights: int, *, shift: int = 0, hrv: int = 42) -> list[dict[str, Any]]:
    return [
        {
            "id": (TODAY - timedelta(days=shift + index)).isoformat(),
            "hrv": hrv,
            "restingHR": 50,
        }
        for index in range(nights + 1)
    ]


def _coach_view(
    wellness: list[dict[str, Any]], garmin: dict[str, Any] | None = None
) -> dict[str, Any]:
    recovery = mapped_personal_recovery(wellness, garmin or {}, {}, TODAY)
    view = coach_performance_projection({"personal_recovery": recovery})
    return view["personal_recovery"]


class _StoredRecoveryReader(CoachPerformanceContextReader):
    """The real reader with the canonical recovery inputs a database read would give."""

    def __init__(self, inputs: Any, *args: Any) -> None:
        super().__init__(*args)
        self._inputs = inputs

    def read_sources(self) -> Any:
        return self._inputs, None


def _coach_context(wellness: list[dict[str, Any]], checkins: CheckinService) -> Any:
    """Build the Coach context through the real structured context service."""
    profile = Mock()
    profile.get.return_value = {"name": "Athlete", "timezone": "UTC"}
    garmin_payload = Mock()
    garmin_payload.sync_status.return_value = GarminSyncStatus()
    reader = _StoredRecoveryReader(
        recovery_only_inputs({}, wellness),
        profile,
        garmin_payload,
        Mock(),
        lambda: TODAY,
    )
    service = CoachStructuredContextService(
        checkins,
        Mock(),
        Mock(),
        CoachPlanningContextReader(
            Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), lambda: TODAY
        ),
        reader,
    )
    selection = CoachContextSelection(
        "focused", frozenset({"local_feedback", "current_performance"})
    )
    return service.build(selection=selection)


def _baselines(view: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    return [item for item in view["baselines"] if item["metric"] == metric]


class RecoveryCoachCases(unittest.TestCase):
    def assert_coach_text_is_clean(self, view: dict[str, Any]) -> None:
        self.assertIn(NO_CLEARANCE, view["note"])
        self.assertEqual(
            [], claim_wording_violations(json.dumps(view, ensure_ascii=False))
        )

    def test_small_data_amount_gives_no_position(self):
        view = _coach_view(_wellness(9))
        for item in _baselines(view, "hrv") + _baselines(view, "resting_hr"):
            self.assertEqual("insufficient_data", item["status"])
            self.assertEqual(9, item["nights"])
            self.assertEqual(
                "Mindestens 14 frühere passende Nächte erforderlich.", item["reason"]
            )
            for key in ("position", "median", "lower", "upper"):
                self.assertNotIn(key, item)
        self.assert_coach_text_is_clean(view)

    def test_fresh_device_change_starts_a_separate_short_series(self):
        garmin = {
            "hrv": [
                {
                    "calendarDate": (TODAY - timedelta(days=day)).isoformat(),
                    "lastNightAvg": 55,
                }
                for day in range(3)
            ]
        }
        view = _coach_view(_wellness(30), garmin)
        series = {item["source_provider"]: item for item in _baselines(view, "hrv")}
        self.assertEqual({"intervals", "garmin"}, set(series))
        self.assertEqual("ok", series["intervals"]["status"])
        self.assertEqual(
            ("insufficient_data", 2),
            (series["garmin"]["status"], series["garmin"]["nights"]),
        )
        self.assertNotIn("position", series["garmin"])
        self.assert_coach_text_is_clean(view)

    def test_fresh_device_model_change_restarts_the_same_provider_series(self):
        garmin = {
            "hrv": [
                {
                    "calendarDate": (TODAY - timedelta(days=day)).isoformat(),
                    "lastNightAvg": 55,
                }
                for day in range(31)
            ]
        }
        inputs = mapped_recovery_inputs(garmin, [])
        device = MeasurementContext(device_model="Forerunner 965", window="overnight")
        hrv = tuple(
            replace(item, provenance=replace(item.provenance, context=device))
            if (TODAY - item.observed_on).days <= 2
            else item
            for item in inputs.of(MetricKind.HRV_RMSSD)
        )
        inputs = replace(
            inputs, observations={**inputs.observations, MetricKind.HRV_RMSSD: hrv}
        )
        recovery = personal_recovery({}, TODAY, canonical=inputs)
        view = coach_performance_projection({"personal_recovery": recovery})[
            "personal_recovery"
        ]
        (item,) = _baselines(view, "hrv")
        self.assertEqual(
            ("insufficient_data", 2, "2026-09-30", "known"),
            (
                item["status"],
                item["nights"],
                item["context_changed_on"],
                item["continuity"],
            ),
        )
        self.assertIn("Messkontext geändert", item["reason"])
        self.assertNotIn("measurement_context", item)
        self.assertIn("Forerunner 965", json.dumps(recovery, ensure_ascii=False))
        self.assertNotIn("position", item)
        self.assert_coach_text_is_clean(view)

    def test_stale_values_keep_the_old_value_without_a_position(self):
        view = _coach_view(_wellness(30, shift=3))
        for item in _baselines(view, "hrv"):
            self.assertEqual("insufficient_data", item["status"])
            self.assertEqual("Messung veraltet.", item["reason"])
            self.assertEqual("2026-09-29", item["observed_at"])
            self.assertEqual(42.0, item["value"])
            self.assertNotIn("position", item)
        self.assert_coach_text_is_clean(view)

    def test_contradictory_heavy_checkin_beside_an_unremarkable_value(self):
        manager = FakeManager()
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
        checkins = CheckinService(
            manager,
            CheckinRepository(lambda: "2026-10-02T07:00:00+00:00"),
            lambda: TODAY,
        )
        checkins.save({"soreness": 8, "day_form": "Beine schwer"})

        context = _coach_context(_wellness(30), checkins)

        saved = context["local_feedback"]["today"]
        self.assertEqual((8, "Beine schwer"), (saved["soreness"], saved["day_form"]))
        recovery = context["current_performance"]["personal_recovery"]
        (hrv,) = _baselines(recovery, "hrv")
        self.assertEqual(("ok", "within"), (hrv["status"], hrv["position"]))
        self.assertNotIn("Beine schwer", json.dumps(recovery, ensure_ascii=False))
        self.assert_coach_text_is_clean(recovery)
        self.assertIn("contradictory", COACH_PROMPT)
        self.assertIn("Never diagnose disease or injury.", COACH_PROMPT)


def _sleep_view(hours: list[float | None], profile: dict[str, Any]) -> dict[str, Any]:
    """Coach view of Intervals sleep: ``hours[0]`` is today, None a missing night."""
    wellness = [
        {"id": (TODAY - timedelta(days=index)).isoformat(), "sleepSecs": hour * 3600}
        for index, hour in enumerate(hours)
        if hour is not None
    ]
    recovery = mapped_personal_recovery(wellness, {}, profile, TODAY)
    return coach_performance_projection({"personal_recovery": recovery})[
        "personal_recovery"
    ]


def _garmin_nights(count: int) -> dict[str, Any]:
    """Garmin sleep periods 22:00-06:00 UTC, waking on the last ``count`` days."""
    nights = []
    for offset in range(count):
        end = datetime(TODAY.year, TODAY.month, TODAY.day, 6, tzinfo=UTC) - timedelta(
            days=offset
        )
        nights.append(
            {
                "calendarDate": end.date().isoformat(),
                "sleepStartTimestampGMT": int(
                    (end - timedelta(hours=8)).timestamp() * 1000
                ),
                "sleepEndTimestampGMT": int(end.timestamp() * 1000),
            }
        )
    return {"sleep": nights}


class SleepCoachCases(unittest.TestCase):
    """M3 (#1429): estimated duration, own goal, known shortfall, unknown coverage."""

    def test_shortfall_counts_known_nights_against_the_own_goal(self):
        view = _sleep_view(
            [6.5, 7.0, None, 8.5, 6.0, 7.5, 7.0], {"sleep_target_hours": "8"}
        )
        (sleep,) = _baselines(view, "sleep")
        self.assertEqual(("Intervals.icu", 6.5), (sleep["source"], sleep["value"]))
        self.assertIn("Schätzung des jeweiligen Geräts", view["note"])
        self.assertEqual(8.0, view["sleep_target_hours"])
        (shortfall,) = view["sleep_deficits"]
        self.assertEqual(
            (6, "partial", 8.0, 6.0),
            (
                shortfall["known_nights"],
                shortfall["status"],
                shortfall["target_hours"],
                shortfall["deficit_hours"],
            ),
        )
        self.assertIn("fehlende Nächte", view["note"])
        self.assertEqual(
            [], claim_wording_violations(json.dumps(view, ensure_ascii=False))
        )

    def test_no_goal_gives_no_shortfall(self):
        view = _sleep_view([6.0] * 7, {})
        self.assertEqual(
            ([], None), (view["sleep_deficits"], view["sleep_target_hours"])
        )
        (sleep,) = _baselines(view, "sleep")
        self.assertEqual(6.0, sleep["value"])

    def test_short_timing_history_gives_no_deviation(self):
        recovery = mapped_personal_recovery(
            [], _garmin_nights(10), {"timezone": "UTC"}, TODAY
        )
        view = coach_performance_projection({"personal_recovery": recovery})
        (series,) = view["personal_recovery"]["regularity"]["series"]
        self.assertEqual(
            ("insufficient_data", 9),
            (series["status"], series["coverage"]["baseline_nights"]),
        )
        self.assertEqual({None}, set(series["baseline"].values()))
        self.assertNotIn("points", series)
        self.assertEqual(
            {None},
            {
                point["onset_deviation_minutes"]
                for point in recovery["regularity"]["points_14"]
            },
        )


if __name__ == "__main__":
    unittest.main()
