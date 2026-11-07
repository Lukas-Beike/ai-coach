"""Race results of past competitions from their linked sessions."""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any
from unittest.mock import Mock

from backend.http_api.athlete_get import AthleteGetRoutes
from backend.planning.race_results import MAX_RESULT_DAYS, with_race_results

TODAY = date(2026, 11, 7)


def _race(competition_id: str | None, **values: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": "act_1",
        "moving_duration_s": 2400.0,
        "distance_m": 10000.0,
        "avg_speed_mps": 4.17,
        "avg_hr": 171.0,
        "source": "Garmin Connect",
        "sources": {"purpose": "Garmin Connect"},
        **values,
    }
    if competition_id is not None:
        summary["competition_id"] = competition_id
    return summary


class RaceResultTests(unittest.TestCase):
    def test_a_past_competition_gets_its_linked_session_result(self) -> None:
        reads: list[date] = []

        def summaries_on(day: date) -> list[dict[str, Any]]:
            reads.append(day)
            return [_race(None, id="act_0"), _race("c-1")]

        result = with_race_results(
            [{"id": "c-1", "event_date": "2026-11-01"}], TODAY, summaries_on
        )

        self.assertEqual(
            result[0]["result"],
            {
                "activity_id": "act_1",
                "duration_s": 2400.0,
                "source": "Garmin Connect",
                "distance_m": 10000.0,
                "avg_speed_mps": 4.17,
                "avg_hr": 171.0,
            },
        )
        self.assertEqual(reads, [date(2026, 11, 1)])

    def test_future_undated_and_unlinked_competitions_get_no_result(self) -> None:
        competitions = [
            {"id": "c-future", "event_date": "2026-12-01"},
            {"id": "c-undated", "event_date": "not-a-date"},
            {"id": "c-unlinked", "event_date": "2026-11-01"},
        ]
        summaries_on = Mock(return_value=[_race("c-other")])

        result = with_race_results(competitions, TODAY, summaries_on)

        self.assertEqual(result, competitions)
        summaries_on.assert_called_once_with(date(2026, 11, 1))

    def test_one_read_per_day_and_a_bounded_number_of_days(self) -> None:
        competitions = [
            {
                "id": f"d-{index}",
                "event_date": date.fromordinal(
                    TODAY.toordinal() - index // 2
                ).isoformat(),
            }
            for index in range(2 * MAX_RESULT_DAYS + 10)
        ]
        summaries_on = Mock(return_value=None)

        with_race_results(competitions, TODAY, summaries_on)

        self.assertEqual(summaries_on.call_count, MAX_RESULT_DAYS)
        self.assertEqual(summaries_on.call_args_list[0].args[0], TODAY)


class ProfileRouteTests(unittest.TestCase):
    def test_profile_read_carries_race_results(self) -> None:
        competitions = [{"id": "c-1", "event_date": "2026-11-01"}]
        race_results = Mock(return_value=[{**competitions[0], "result": {}}])
        routes = AthleteGetRoutes(
            Mock(),
            Mock(),
            Mock(return_value=Mock(get=Mock(return_value={}))),
            Mock(return_value=Mock(list=Mock(return_value=competitions))),
            Mock(),
            Mock(),
            Mock(),
            race_results=race_results,
        )
        handler = Mock()

        self.assertTrue(routes.handle(handler, "/api/profile"))

        race_results.assert_called_once_with(competitions)
        payload = handler.send_json.call_args.args[1]
        self.assertEqual(payload["competitions"][0]["result"], {})


if __name__ == "__main__":
    unittest.main()
