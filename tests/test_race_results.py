"""Race results of past competitions from their linked sessions."""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from datetime import date
from typing import Any
from unittest.mock import Mock

from support import dispatch_route

from backend.activities.session_purpose import COMPETITION_SOURCE_LABEL
from backend.http_api.athlete_get import AthleteGetRoutes
from backend.planning.race_results import with_race_results

TODAY = date(2026, 11, 7)


def _race(
    competition_id: str | None, source: str = "Garmin Connect", **values: Any
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": "act_1",
        "sport": "run",
        "moving_duration_s": 2380.0,
        "elapsed_duration_s": 2400.0,
        "distance_m": 10000.0,
        "avg_speed_mps": 4.17,
        "avg_hr": 171.0,
        "source": "Garmin Connect",
        "sources": {"purpose": source},
        **values,
    }
    if competition_id is not None:
        summary["competition_id"] = competition_id
    return summary


def _reader(rows: dict[date, list[dict[str, Any]]]) -> Mock:
    def read(days: Sequence[date]) -> dict[date, list[dict[str, Any]]]:
        return {day: rows.get(day, []) for day in days}

    return Mock(side_effect=read)


def _routes(race_results: Mock, competitions: list[dict[str, Any]]) -> AthleteGetRoutes:
    return AthleteGetRoutes(
        Mock(),
        Mock(return_value=Mock(get=Mock(return_value={}))),
        Mock(return_value=Mock(list=Mock(return_value=competitions))),
        Mock(),
        Mock(),
        Mock(),
        race_results=race_results,
    )


class RaceResultTests(unittest.TestCase):
    def test_a_past_competition_gets_its_linked_session_result(self) -> None:
        day = date(2026, 11, 1)
        reader = _reader({day: [_race(None, id="act_0"), _race("c-1")]})

        result = with_race_results(
            [{"id": "c-1", "event_date": "2026-11-01"}], TODAY, reader
        )

        self.assertEqual(
            result[0]["result"],
            {
                "sport": "run",
                "duration_s": 2400.0,
                "source": "Garmin Connect",
                "distance_m": 10000.0,
                "avg_speed_mps": 4.17,
            },
        )
        reader.assert_called_once_with([day])

    def test_moving_time_stands_in_without_elapsed_time(self) -> None:
        day = date(2026, 11, 1)
        reader = _reader({day: [_race("c-1", elapsed_duration_s=None)]})

        result = with_race_results(
            [{"id": "c-1", "event_date": "2026-11-01"}], TODAY, reader
        )

        self.assertEqual(result[0]["result"]["duration_s"], 2380.0)

    def test_future_undated_and_unlinked_competitions_get_no_result(self) -> None:
        competitions = [
            {"id": "c-future", "event_date": "2026-12-01"},
            {"id": "c-undated", "event_date": "not-a-date"},
            {"id": "c-unlinked", "event_date": "2026-11-01"},
        ]
        reader = _reader({date(2026, 11, 1): [_race("c-other")]})

        result = with_race_results(competitions, TODAY, reader)

        self.assertEqual(result, competitions)
        reader.assert_called_once_with([date(2026, 11, 1)])

    def test_today_takes_a_provider_race_but_not_the_date_hint(self) -> None:
        hinted = _reader({TODAY: [_race("c-1", source=COMPETITION_SOURCE_LABEL)]})
        raced = _reader({TODAY: [_race("c-1")]})
        today = [{"id": "c-1", "event_date": TODAY.isoformat()}]

        self.assertNotIn("result", with_race_results(today, TODAY, hinted)[0])
        self.assertIn("result", with_race_results(today, TODAY, raced)[0])

    def test_no_read_without_past_competitions(self) -> None:
        reader = _reader({})

        with_race_results([{"id": "c-1", "event_date": "2027-01-01"}], TODAY, reader)

        reader.assert_not_called()


class ProfileRouteTests(unittest.TestCase):
    def test_profile_read_carries_race_results(self) -> None:
        competitions = [{"id": "c-1", "event_date": "2026-11-01"}]
        race_results = Mock(return_value=[{**competitions[0], "result": {}}])
        handler = Mock()

        self.assertTrue(
            dispatch_route(_routes(race_results, competitions), handler, "/api/profile")
        )

        race_results.assert_called_once_with(competitions)
        payload = handler.send_json.call_args.args[1]
        self.assertEqual(payload["competitions"][0]["result"], {})

    def test_a_failed_result_read_keeps_the_profile(self) -> None:
        competitions = [{"id": "c-1", "event_date": "2026-11-01"}]
        handler = Mock()
        failing = Mock(side_effect=RuntimeError("locked"))

        with self.assertLogs("intervals_coach", "WARNING") as logs:
            dispatch_route(_routes(failing, competitions), handler, "/api/profile")

        payload = handler.send_json.call_args.args[1]
        self.assertEqual(payload["competitions"], competitions)
        self.assertNotIn("locked", "".join(logs.output))


if __name__ == "__main__":
    unittest.main()
