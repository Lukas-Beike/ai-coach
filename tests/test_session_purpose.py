"""Activity purpose: Garmin event types, session precedence and competition links."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.activities.session_purpose import (
    COMPETITION_SOURCE_LABEL,
    session_purpose,
    with_competitions,
)
from backend.canonical.mapping import IssueReason
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import ActivityPurpose
from backend.db import canonical_store
from backend.providers.garmin_activity_mapping import map_garmin_activities

BERLIN = ZoneInfo("Europe/Berlin")
RETRIEVED = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)


def _garmin(event_type: object) -> tuple[ActivityRecord, tuple[Any, ...]]:
    row: dict[str, Any] = {
        "activityId": 910101,
        "activityName": "Synthetic run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2026-10-08 09:00:00",
        "duration": 2400.0,
    }
    if event_type is not None:
        row["eventType"] = event_type
    result = map_garmin_activities([row], zone=BERLIN, retrieved_at=RETRIEVED)
    return result.records[0], result.issues


class GarminEventTypeTests(unittest.TestCase):
    def test_event_types_map_to_purposes(self) -> None:
        cases = (
            ({"typeId": 1, "typeKey": "race"}, ActivityPurpose.RACE),
            ({"typeId": 2, "typeKey": "transportation"}, ActivityPurpose.COMMUTE),
            ({"typeId": 9, "typeKey": "uncategorized"}, None),
            ({"typeKey": "training"}, None),
            ({"typeId": 9}, None),
            ("race", ActivityPurpose.RACE),
            (None, None),
        )
        for event_type, expected in cases:
            with self.subTest(event_type=event_type):
                record, issues = _garmin(event_type)
                self.assertIs(record.purpose, expected)
                self.assertEqual(issues, ())

    def test_a_key_that_is_not_text_is_one_issue(self) -> None:
        record, issues = _garmin({"typeKey": 7})

        self.assertIsNone(record.purpose)
        self.assertEqual(
            [(issue.field, issue.reason) for issue in issues],
            [("eventType", IssueReason.INVALID_TYPE)],
        )

    def test_purpose_survives_the_stored_details(self) -> None:
        record, _ = _garmin({"typeKey": "race"})
        details = canonical_store._activity_details(record)

        self.assertEqual(json.loads(details)["purpose"], "race")
        self.assertIs(
            canonical_store.activity_summary_values(details)["purpose"],
            ActivityPurpose.RACE,
        )
        self.assertNotIn(
            "purpose", canonical_store.activity_summary_values('{"purpose":"party"}')
        )


class SessionPurposeTests(unittest.TestCase):
    def test_race_wins_over_any_other_purpose(self) -> None:
        commute, _ = _garmin({"typeKey": "transportation"})
        race, _ = _garmin({"typeKey": "race"})
        plain, _ = _garmin(None)

        self.assertIs(session_purpose((commute, race)), race)
        self.assertIs(session_purpose((plain, commute)), commute)
        self.assertIsNone(session_purpose((plain,)))


def _summary(
    session_id: str,
    started: str,
    *,
    sport: str = "run",
    duration: float = 2400.0,
    purpose: str | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": session_id,
        "started_at": started + "+02:00",
        "started_at_local": started,
        "sport": sport,
        "moving_duration_s": duration,
        "sources": {"moving_duration_s": "Garmin Connect"},
    }
    if purpose is not None:
        summary["purpose"] = purpose
        summary["sources"]["purpose"] = "Garmin Connect"
    return summary


def _competition(
    competition_id: str = "c-1",
    *,
    day: str = "2026-10-11",
    sport: str = "run",
    starts_at_local: str | None = None,
) -> dict[str, Any]:
    return {
        "id": competition_id,
        "event_date": day,
        "sport": sport,
        "environment": None,
        "starts_at_local": starts_at_local,
    }


class CompetitionLinkTests(unittest.TestCase):
    def test_provider_races_are_linked_without_a_hint(self) -> None:
        warmup = _summary("act_w", "2026-10-11T09:00:00", duration=900.0)
        race = _summary("act_r", "2026-10-11T10:00:00", purpose="race")

        result = with_competitions([warmup, race], [_competition()])

        self.assertEqual(result[0], warmup)
        self.assertEqual(result[1]["competition_id"], "c-1")
        self.assertEqual(result[1]["sources"]["purpose"], "Garmin Connect")

    def test_hint_takes_the_session_nearest_the_start_time(self) -> None:
        early = _summary("act_a", "2026-10-11T08:00:00", duration=5000.0)
        near = _summary("act_b", "2026-10-11T10:05:00", duration=1200.0)

        result = with_competitions(
            [early, near], [_competition(starts_at_local="2026-10-11T10:00")]
        )

        self.assertNotIn("competition_id", result[0])
        self.assertEqual(result[1]["purpose"], "race")
        self.assertEqual(result[1]["competition_id"], "c-1")
        self.assertEqual(result[1]["sources"]["purpose"], COMPETITION_SOURCE_LABEL)
        self.assertNotIn("purpose", near)

    def test_hint_without_a_start_time_takes_the_longest_session(self) -> None:
        short = _summary("act_a", "2026-10-11T08:00:00", duration=900.0)
        long = _summary("act_b", "2026-10-11T10:00:00", duration=3600.0)

        result = with_competitions([short, long], [_competition()])

        self.assertEqual([row.get("competition_id") for row in result], [None, "c-1"])

    def test_other_sports_days_and_commutes_are_never_linked(self) -> None:
        rows = [
            _summary("act_ride", "2026-10-11T10:00:00", sport="ride"),
            _summary("act_day", "2026-10-12T10:00:00"),
            _summary("act_commute", "2026-10-11T07:00:00", purpose="commute"),
        ]

        self.assertEqual(with_competitions(rows, [_competition()]), rows)

    def test_a_session_links_to_one_competition_only(self) -> None:
        only = _summary("act_a", "2026-10-11T10:00:00")

        result = with_competitions([only], [_competition("c-2"), _competition("c-1")])

        self.assertEqual(result[0]["competition_id"], "c-1")

    def test_unsupported_competition_sport_links_nothing(self) -> None:
        rows = [_summary("act_a", "2026-10-11T10:00:00")]

        self.assertEqual(with_competitions(rows, [_competition(sport="Schach")]), rows)


class CompetitionReviewCaseTests(unittest.TestCase):
    def test_a_stored_midnight_start_counts_as_unknown(self) -> None:
        shakeout = _summary("act_a", "2026-10-11T07:00:00", duration=1200.0)
        race = _summary("act_b", "2026-10-11T10:00:00", duration=5400.0)

        result = with_competitions(
            [shakeout, race], [_competition(starts_at_local="2026-10-11T00:00:00")]
        )

        self.assertEqual([row.get("competition_id") for row in result], [None, "c-1"])

    def test_each_competition_takes_one_provider_race_and_no_hint(self) -> None:
        prologue = _summary("act_p", "2026-10-11T09:00:00", purpose="race")
        main = _summary("act_m", "2026-10-11T14:00:00", purpose="race")
        jog = _summary("act_j", "2026-10-11T16:00:00", duration=9000.0)

        result = with_competitions(
            [prologue, main, jog],
            [
                _competition("c-1", starts_at_local="2026-10-11T09:00"),
                _competition("c-2", starts_at_local="2026-10-11T14:00"),
                _competition("c-3"),
            ],
        )

        self.assertEqual(
            [row.get("competition_id") for row in result], ["c-1", "c-2", None]
        )
        self.assertNotIn("purpose", result[2])

    def test_indoor_and_outdoor_must_agree_when_known(self) -> None:
        outdoor = _summary(
            "act_o", "2026-10-11T08:00:00", sport="ride", duration=9000.0
        )
        outdoor["environment"] = "outdoor"
        virtual = _summary(
            "act_v", "2026-10-11T18:00:00", sport="ride", duration=3600.0
        )
        virtual["environment"] = "virtual"
        race = {**_competition(sport="ride"), "environment": "virtual"}

        result = with_competitions([outdoor, virtual], [race])

        self.assertEqual([row.get("competition_id") for row in result], [None, "c-1"])

    def test_hint_needs_half_the_planned_duration(self) -> None:
        jog = _summary("act_j", "2026-10-11T10:00:00", duration=1500.0)
        planned = {**_competition(), "planned_duration_s": 3600}

        self.assertEqual(with_competitions([jog], [planned]), [jog])

    def test_a_session_without_a_start_ranks_last(self) -> None:
        broken = _summary("act_x", "2026-10-11T10:00:00")
        broken["started_at_local"] = "2026-10-11"
        timed = _summary("act_t", "2026-10-11T09:00:00")
        broken_day = {**_competition(), "event_date": "2026-10-11"}

        result = with_competitions(
            [timed, broken], [{**broken_day, "starts_at_local": "2026-10-11T10:00"}]
        )

        self.assertEqual([row.get("competition_id") for row in result], ["c-1", None])


class SelectorCompetitionTests(CanonicalReadFixture):
    def test_reader_serves_purpose_and_competition_link(self) -> None:
        self.garmin["activities"][0]["eventType"] = {"typeKey": "race"}
        populate(self)
        self.execute(
            "INSERT INTO competitions(id, name, event_date, sport, priority, distance, "
            "target, course_profile, notes, created_at, updated_at) "
            "VALUES ('c-run', 'Stadtlauf', '2026-10-09', 'run', 'A', '10 km', '', '', "
            "'', '2026-10-01T00:00:00', '2026-10-01T00:00:00')"
        )

        summaries = self.read(make_selector(self).activity_summaries)
        by_sport = {
            row["sport"]: row
            for row in summaries
            if row["started_at_local"][:10] in {"2026-10-08", "2026-10-09"}
        }

        self.assertEqual(by_sport["ride"]["purpose"], "race")
        self.assertEqual(by_sport["ride"]["sources"]["purpose"], "Garmin Connect")
        self.assertNotIn("competition_id", by_sport["ride"])
        self.assertEqual(by_sport["run"]["purpose"], "race")
        self.assertEqual(by_sport["run"]["competition_id"], "c-run")

    def test_a_limited_read_links_over_the_whole_oldest_day(self) -> None:
        populate(self)
        self.execute(
            "INSERT INTO competitions(id, name, event_date, sport, priority, distance, "
            "target, course_profile, notes, created_at, updated_at) "
            "VALUES ('c-run', 'Lauf', '2026-03-29', 'run', 'A', '', '', '', '', "
            "'2026-10-01T00:00:00', '2026-10-01T00:00:00')"
        )
        selector = make_selector(self)

        full = {
            row["id"]: row.get("competition_id")
            for row in self.read(selector.activity_summaries)
        }
        limited = self.read(selector.activity_summaries, limit=5)

        self.assertEqual(len(limited), 5)
        for row in limited:
            self.assertEqual(row.get("competition_id"), full[row["id"]])
        self.assertEqual(list(full.values()).count("c-run"), 1)

    def test_the_reader_applies_the_planned_duration(self) -> None:
        populate(self)
        self.execute(
            "INSERT INTO competitions(id, name, event_date, sport, priority, distance, "
            "target, course_profile, notes, planned_duration_s, created_at, "
            "updated_at) VALUES ('c-long', 'Marathon', '2026-10-09', 'run', 'A', "
            "'42 km', '', '', '', 36000, '2026-10-01T00:00:00', "
            "'2026-10-01T00:00:00')"
        )

        summaries = self.read(make_selector(self).activity_summaries)

        self.assertNotIn("c-long", [row.get("competition_id") for row in summaries])


if __name__ == "__main__":
    unittest.main()
