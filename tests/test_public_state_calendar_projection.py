from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from backend.http_api.bootstrap_calendar import PublicStateCalendarProjection


class PublicStateCalendarProjectionTests(unittest.TestCase):
    def test_reads_calendar_data_in_order_and_projects_supplied_state(self) -> None:
        calls: list[tuple[str, object]] = []
        checkins = [{"date": "2026-09-23", "sleep": 8}]
        competitions = [{"name": "Gran Fondo"}]
        external_state = {"events": [{"name": "Camp"}], "running": True}
        daily_context = [{"date": "2026-09-23"}]
        calendar_result = {"calendar": [{"name": "Camp"}]}
        snapshot = {"recent_activities": [{"id": "activity-1"}]}
        canonical_planned = [{"canonical": True}]
        local_planned = [{"id": "planned-1"}]
        activities = [{"id": "activity-1"}]
        weather = {"days": []}
        calendar_window = {"start": "2026-09-01", "end": "2026-10-01"}

        class Checkins:
            def list(self, limit: int) -> list[dict[str, object]]:
                calls.append(("checkins", limit))
                return checkins

        class Competitions:
            def list(self) -> list[dict[str, object]]:
                calls.append(("competitions", None))
                return competitions

        class ExternalCalendar:
            def state(self, **kwargs: object) -> dict[str, object]:
                calls.append(("external_state", kwargs))
                return external_state

            def list_events(self, limit: int, *, training_relevant_only: bool) -> list[dict[str, str]]:
                calls.append(("external_events", (limit, training_relevant_only)))
                return [{"name": "Relevant event"}]

        class ExternalCalendarSync:
            def running(self) -> bool:
                calls.append(("running", None))
                return True

        class DailyContext:
            def build(self, *args: object) -> list[dict[str, str]]:
                calls.append(("daily_context", args))
                return daily_context

        projection = PublicStateCalendarProjection(
            Checkins(),
            Competitions(),
            ExternalCalendar(),
            ExternalCalendarSync(),
            DailyContext(),
            external_calendar_configured=True,
            external_calendar_window_days=56,
            default_workout_name="Geplante Einheit",
            today=lambda: date(2026, 9, 23),
        )

        with patch(
            "backend.http_api.bootstrap_calendar.calendar_read_model.project_planning_calendar",
            return_value=calendar_result,
        ) as project_calendar:
            result = projection.read(
                snapshot,
                canonical_planned,
                local_planned,
                activities,
                weather,
                calendar_window,
            )

        self.assertEqual(
            [name for name, _ in calls],
            [
                "checkins",
                "competitions",
                "running",
                "external_state",
                "external_events",
                "daily_context",
            ],
        )
        self.assertEqual(calls[0], ("checkins", 30))
        self.assertEqual(
            calls[3],
            (
                "external_state",
                {"configured": True, "running": True, "window_days": 56},
            ),
        )
        self.assertEqual(calls[4], ("external_events", (50, True)))
        self.assertEqual(
            calls[5],
            (
                "daily_context",
                (
                    snapshot,
                    canonical_planned,
                    weather,
                    checkins,
                    [{"name": "Relevant event"}],
                ),
            ),
        )
        self.assertIs(calls[5][1][1], canonical_planned)
        project_calendar.assert_called_once_with(
            local_planned,
            activities,
            weather,
            competitions,
            external_state["events"],
            today=date(2026, 9, 23),
            provider_window=calendar_window,
            default_name="Geplante Einheit",
        )
        self.assertEqual(result.checkins, checkins)
        self.assertEqual(result.competitions, competitions)
        self.assertEqual(result.external_calendar, external_state)
        self.assertEqual(result.daily_context, daily_context)
        self.assertEqual(result.calendar_projection, calendar_result)


if __name__ == "__main__":
    unittest.main()
