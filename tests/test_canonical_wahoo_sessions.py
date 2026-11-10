"""Wahoo-provider rules of canonical session bundling, as rule tables."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.canonical_sessions import ActivitySession, bundle_sessions
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    ActivityLinkKind,
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)

BERLIN = ZoneInfo("Europe/Berlin")
FETCHED = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
START = datetime(2026, 6, 1, 7, 0, tzinfo=BERLIN)


def record(
    provider: ProviderId,
    identifier: str,
    *,
    origin: RecordingOrigin = RecordingOrigin.UNKNOWN,
    sport: Sport = Sport.RIDE,
    started_at: datetime = START,
    duration_s: float | None = 3600.0,
    distance_m: float | None = 30000.0,
    moving_duration_s: float | None = None,
    elapsed_duration_s: float | None = None,
) -> ActivityRecord:
    return ActivityRecord(
        activity_id=identifier,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=identifier,
            recorded_by=origin,
            retrieved_at=FETCHED,
            label=None,
        ),
        sport=sport,
        environment=Environment.OUTDOOR,
        started_at=started_at,
        duration_s=duration_s,
        distance_m=distance_m,
        load=None,
        load_model=LoadModel.UNKNOWN,
        avg_hr=None,
        avg_power=None,
        name=None,
        moving_duration_s=moving_duration_s,
        elapsed_duration_s=elapsed_duration_s,
    )


def intervals_wahoo(**fields: Any) -> ActivityRecord:
    return record(
        ProviderId.INTERVALS,
        "i-1",
        origin=RecordingOrigin.WAHOO,
        **fields,
    )


def wahoo(**fields: Any) -> ActivityRecord:
    return record(ProviderId.WAHOO, "w-1", **fields)


def garmin(**fields: Any) -> ActivityRecord:
    return record(ProviderId.GARMIN, "g-1", **fields)


def links(sessions: tuple[ActivitySession, ...]) -> set[tuple[str, str, str]]:
    return {
        (session.primary.activity_id, duplicate.activity_id, kind.value)
        for session in sessions
        for duplicate, kind in zip(session.duplicates, session.link_kinds, strict=True)
    }


class WahooAgainstIntervalsTests(unittest.TestCase):
    def _bundle(self, *records: ActivityRecord) -> tuple[ActivitySession, ...]:
        return bundle_sessions(records, zone=BERLIN)

    def test_intervals_copy_is_a_heuristic_duplicate_of_the_matching_ride(self) -> None:
        sessions = self._bundle(intervals_wahoo(), wahoo())
        self.assertEqual(links(sessions), {("w-1", "i-1", "heuristic")})
        self.assertEqual(len(sessions), 1)

    def test_rule_table(self) -> None:
        cases: dict[str, tuple[dict[str, Any], bool]] = {
            "start at the window edge": (
                {"started_at": START + timedelta(minutes=30)},
                True,
            ),
            "start beyond the window": (
                {"started_at": START + timedelta(minutes=31)},
                False,
            ),
            "start before the window edge": (
                {"started_at": START - timedelta(minutes=30)},
                True,
            ),
            "sport family mismatch": ({"sport": Sport.RUN}, False),
            "other sport agrees with anything": ({"sport": Sport.OTHER}, True),
            "duration at the floor tolerance": ({"duration_s": 3720.0}, True),
            "duration just past the floor": ({"duration_s": 3721.0}, True),
            "duration far apart": ({"duration_s": 7200.0}, False),
            "distance within tolerance": ({"distance_m": 32500.0}, True),
            "distance far apart": ({"distance_m": 45000.0}, False),
            "missing distance is skipped": ({"distance_m": None}, True),
            "zero distance is skipped": ({"distance_m": 0.0}, True),
            "missing everything compares nothing": (
                {"duration_s": None, "distance_m": None},
                False,
            ),
        }
        for name, (fields, expected) in cases.items():
            with self.subTest(name):
                sessions = self._bundle(intervals_wahoo(), wahoo(**fields))
                self.assertEqual(len(sessions) == 1, expected)

    def test_duration_tolerance_edge_is_ten_percent_above_the_floor(self) -> None:
        # 10 % of 3600 s is 360 s: the tolerance is max(120 s, 360 s).
        near = self._bundle(intervals_wahoo(), wahoo(duration_s=3960.0))
        far = self._bundle(intervals_wahoo(), wahoo(duration_s=3961.0))
        self.assertEqual((len(near), len(far)), (1, 2))

    def test_only_wahoo_recorded_intervals_copies_qualify(self) -> None:
        for origin in (RecordingOrigin.GARMIN, RecordingOrigin.UNKNOWN):
            with self.subTest(origin=origin):
                other = record(ProviderId.INTERVALS, "i-1", origin=origin)
                self.assertEqual(len(self._bundle(other, wahoo())), 2)

    def test_wahoo_leads_over_intervals_whatever_the_start_order(self) -> None:
        earlier_wahoo = wahoo(started_at=START - timedelta(minutes=10))
        sessions = self._bundle(intervals_wahoo(), earlier_wahoo)
        self.assertEqual(links(sessions), {("w-1", "i-1", "heuristic")})

    def test_wall_clock_is_compared_across_the_autumn_dst_change(self) -> None:
        # 02:30 occurs twice on 2026-10-25 in Berlin; 02:50 CEST vs 02:20 CET are
        # 30 minutes apart on the wall clock but 90 minutes apart as instants.
        first = datetime(2026, 10, 25, 2, 50, tzinfo=BERLIN, fold=0)
        second = datetime(2026, 10, 25, 2, 20, tzinfo=BERLIN, fold=1)
        sessions = self._bundle(
            intervals_wahoo(started_at=first), wahoo(started_at=second)
        )
        self.assertEqual(len(sessions), 1)

    def test_wall_clock_is_compared_across_the_spring_dst_change(self) -> None:
        before = datetime(2026, 3, 29, 1, 50, tzinfo=BERLIN)
        after = datetime(2026, 3, 29, 3, 10, tzinfo=BERLIN)
        sessions = self._bundle(
            intervals_wahoo(started_at=before), wahoo(started_at=after)
        )
        # Wall clock 01:50 versus 03:10 is 80 minutes apart: outside the window.
        self.assertEqual(len(sessions), 2)


class GarminAgainstWahooTests(unittest.TestCase):
    def _bundle(self, *records: ActivityRecord) -> tuple[ActivitySession, ...]:
        return bundle_sessions(records, zone=BERLIN)

    def test_garmin_ride_is_a_duplicate_of_a_standalone_wahoo_ride(self) -> None:
        sessions = self._bundle(garmin(), wahoo())
        self.assertEqual(links(sessions), {("w-1", "g-1", "heuristic")})

    def test_wahoo_is_primary_even_when_garmin_starts_earlier(self) -> None:
        sessions = self._bundle(
            garmin(started_at=START - timedelta(minutes=5)), wahoo()
        )
        self.assertEqual(links(sessions), {("w-1", "g-1", "heuristic")})

    def test_rule_table(self) -> None:
        cases: dict[str, tuple[dict[str, Any], bool]] = {
            "duration beyond tolerance": ({"duration_s": 7200.0}, False),
            "distance beyond tolerance": ({"distance_m": 60000.0}, False),
            "missing duration": ({"duration_s": None}, False),
            "missing distance falls back to duration and a close start": (
                {"distance_m": None},
                True,
            ),
            "zero distance falls back to duration and a close start": (
                {"distance_m": 0.0},
                True,
            ),
            "missing distance beyond the close start": (
                {"distance_m": None, "started_at": START + timedelta(minutes=11)},
                False,
            ),
            "distance with a wider start": (
                {"started_at": START + timedelta(minutes=25)},
                True,
            ),
            "outside the window": (
                {"started_at": START + timedelta(minutes=31)},
                False,
            ),
            "run is not a cycling ride": ({"sport": Sport.RUN}, False),
            "strength is not a cycling ride": ({"sport": Sport.STRENGTH}, False),
            "an unclassified sport is compatible": ({"sport": Sport.OTHER}, True),
        }
        for name, (fields, expected) in cases.items():
            with self.subTest(name):
                sessions = self._bundle(garmin(**fields), wahoo())
                self.assertEqual(len(sessions) == 1, expected)

    def test_copies_of_other_sports_bundle_on_duration(self) -> None:
        for sport, distance in (
            (Sport.RUN, 10000.0),
            (Sport.WALK, 4000.0),
            (Sport.YOGA, None),
            (Sport.STRENGTH, 0.0),
            (Sport.RIDE, None),
        ):
            with self.subTest(sport.value, distance=distance):
                sessions = self._bundle(
                    garmin(sport=sport, distance_m=distance),
                    wahoo(
                        sport=sport,
                        distance_m=None if distance is None else distance + 50.0,
                        started_at=START + timedelta(minutes=2),
                    ),
                )
                self.assertEqual(links(sessions), {("w-1", "g-1", "heuristic")})

    def test_a_distance_disagreement_blocks_copies_of_any_sport(self) -> None:
        sessions = self._bundle(
            garmin(sport=Sport.RUN, distance_m=10000.0),
            wahoo(sport=Sport.RUN, distance_m=14000.0),
        )
        self.assertEqual(len(sessions), 2)

    def test_moving_and_elapsed_durations_are_candidates(self) -> None:
        cases = {
            "moving against the other timer": (
                {"duration_s": 3900.0, "moving_duration_s": 3300.0},
                {"duration_s": 3300.0},
            ),
            "elapsed against elapsed": (
                {"duration_s": 3900.0, "elapsed_duration_s": 3900.0},
                {"duration_s": 3300.0, "elapsed_duration_s": 3900.0},
            ),
        }
        for name, (garmin_fields, wahoo_fields) in cases.items():
            with self.subTest(name):
                sessions = self._bundle(garmin(**garmin_fields), wahoo(**wahoo_fields))
                self.assertEqual(links(sessions), {("w-1", "g-1", "heuristic")})
        with self.subTest("no duration pair agrees"):
            sessions = self._bundle(garmin(duration_s=3900.0), wahoo(duration_s=3300.0))
            self.assertEqual(len(sessions), 2)

    def test_two_separate_sessions_never_merge_across_sports(self) -> None:
        # A run and a strength session close together stay apart.
        sessions = self._bundle(
            garmin(sport=Sport.RUN, distance_m=None, duration_s=1800.0),
            wahoo(sport=Sport.STRENGTH, distance_m=None, duration_s=1800.0),
        )
        self.assertEqual(len(sessions), 2)

    def test_two_sessions_on_one_day_stay_apart(self) -> None:
        sessions = self._bundle(
            garmin(),
            record(ProviderId.GARMIN, "g-2", started_at=START + timedelta(hours=6)),
            wahoo(),
        )
        self.assertEqual(links(sessions), {("w-1", "g-1", "heuristic")})
        self.assertEqual(len(sessions), 2)

    def test_a_watch_recording_and_a_relayed_copy_both_join_the_wahoo_session(
        self,
    ) -> None:
        relayed = record(
            ProviderId.GARMIN,
            "g-relay",
            origin=RecordingOrigin.WAHOO,
            started_at=START + timedelta(minutes=4),
        )
        watch = record(
            ProviderId.GARMIN,
            "g-watch",
            origin=RecordingOrigin.GARMIN,
            started_at=START + timedelta(minutes=1),
            duration_s=3700.0,
        )
        sessions = self._bundle(relayed, watch, wahoo())
        self.assertEqual(
            links(sessions),
            {("w-1", "g-relay", "heuristic"), ("w-1", "g-watch", "heuristic")},
        )

    def test_one_origin_still_takes_one_garmin_record_per_session(self) -> None:
        sessions = self._bundle(
            record(
                ProviderId.GARMIN,
                "g-1",
                origin=RecordingOrigin.GARMIN,
                started_at=START + timedelta(minutes=1),
            ),
            record(
                ProviderId.GARMIN,
                "g-2",
                origin=RecordingOrigin.GARMIN,
                started_at=START + timedelta(minutes=2),
            ),
            wahoo(),
        )
        self.assertEqual(len(sessions), 2)

    def test_garmin_joins_the_intervals_session_through_wahoo(self) -> None:
        # The Garmin ride starts 31 minutes after the Intervals copy, so it cannot
        # match it, but it starts 29 minutes after the Wahoo ride that does.
        sessions = self._bundle(
            intervals_wahoo(started_at=START - timedelta(minutes=2)),
            wahoo(),
            garmin(started_at=START + timedelta(minutes=29)),
        )
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].primary.activity_id, "w-1")
        self.assertEqual(
            {d.activity_id for d in sessions[0].duplicates}, {"i-1", "g-1"}
        )

    def test_garmin_matching_intervals_directly_keeps_that_link(self) -> None:
        sessions = self._bundle(intervals_wahoo(), garmin(), wahoo())
        self.assertEqual(
            links(sessions), {("w-1", "g-1", "heuristic"), ("w-1", "i-1", "heuristic")}
        )

    def test_link_kinds_run_parallel_to_duplicates_and_stay_out_of_equality(
        self,
    ) -> None:
        session = self._bundle(garmin(), wahoo())[0]
        self.assertEqual(len(session.link_kinds), len(session.duplicates))
        self.assertEqual(session.link_kinds, (ActivityLinkKind.HEURISTIC,))
        self.assertEqual(session, ActivitySession(session.primary, session.duplicates))

    def test_bundling_is_deterministic_for_any_input_order(self) -> None:
        records = [intervals_wahoo(), wahoo(), garmin()]
        expected = links(self._bundle(*records))
        self.assertEqual(links(self._bundle(*reversed(records))), expected)


if __name__ == "__main__":
    unittest.main()
