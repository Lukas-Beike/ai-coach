"""Session bundling parity with the legacy duplicate rules in duplicates.py.

Each pair case asserts the legacy result and the canonical result against one
expected value, so a drift on either side fails. Named deviation tests document
the cases where canonical records cannot carry what the legacy rule read.
"""

from __future__ import annotations

import json
import random
import unittest
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from unittest import mock
from zoneinfo import ZoneInfo

from backend.activities import canonical_sessions
from backend.activities.canonical_sessions import (
    ActivitySession,
    _Entry,
    _garmin_matches_intervals,
    _is_intervals,
    _is_intervals_ride,
    _order_key,
    _wahoo_and_garmin_copy_match,
    _wall_clock,
    bundle_sessions,
    wahoo_garmin_copy_match,
)
from backend.activities.duplicate_inspection import latest_wahoo_garmin_duplicate
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.sports import legacy_activity_family
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.providers.garmin_activity_mapping import map_garmin_activities
from backend.providers.intervals_activity_mapping import map_intervals_activities
from backend.sync.garmin_activity_duplicates import (
    garmin_activity_duplicates_intervals,
    intervals_cycling_activities_match,
)

BERLIN = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers"


def _load_fixture(provider: str, name: str) -> list[dict[str, Any]]:
    with (FIXTURES / provider / name).open(encoding="utf-8") as handle:
        loaded: list[dict[str, Any]] = json.load(handle)
    return loaded


def _map_intervals(rows: list[dict[str, Any]]) -> list[ActivityRecord]:
    result = map_intervals_activities(rows, zone=BERLIN, retrieved_at=RETRIEVED_AT)
    if len(result.records) != len(rows):
        raise AssertionError(f"Intervals rows not mapped: {result.issues!r}")
    return list(result.records)


def _map_garmin(rows: list[dict[str, Any]]) -> list[ActivityRecord]:
    result = map_garmin_activities(rows, zone=BERLIN, retrieved_at=RETRIEVED_AT)
    if len(result.records) != len(rows):
        raise AssertionError(f"Garmin rows not mapped: {result.issues!r}")
    return list(result.records)


def _bundle(*groups: Iterable[ActivityRecord]) -> tuple[ActivitySession, ...]:
    return bundle_sessions(
        [record for group in groups for record in group], zone=BERLIN
    )


def _duplicate_ids(
    sessions: tuple[ActivitySession, ...], provider: ProviderId
) -> set[str]:
    return {
        duplicate.activity_id
        for session in sessions
        for duplicate in session.duplicates
        if duplicate.provenance.provider is provider
    }


def garmin_ride(**fields: Any) -> dict[str, Any]:
    """Return a valid Garmin cycling row at 07:00 Berlin time, overridden by fields."""
    base: dict[str, Any] = {
        "activityId": 1,
        "activityType": {"typeKey": "cycling"},
        "startTimeLocal": "2026-06-01 07:00:00",
        "duration": 3600.0,
        "distance": 30000.0,
    }
    base.update(fields)
    return base


def intervals_ride(**fields: Any) -> dict[str, Any]:
    """Return a valid Intervals ride at 07:00 Berlin time, overridden by fields."""
    base: dict[str, Any] = {
        "id": "i-1",
        "type": "Ride",
        "start_date_local": "2026-06-01T07:00:00",
        "moving_time": 3600,
        "distance": 30000.0,
    }
    base.update(fields)
    return base


def _wahoo(**fields: Any) -> dict[str, Any]:
    return intervals_ride(**{"id": "wahoo-1", "device_name": "Wahoo ELEMNT", **fields})


def _garmin_copy(**fields: Any) -> dict[str, Any]:
    return intervals_ride(
        **{"id": "garmin-copy-1", "device_name": "Garmin Edge", **fields}
    )


def _canonical_garmin_duplicate(
    garmin_row: dict[str, Any], intervals_row: dict[str, Any]
) -> bool:
    sessions = _bundle(_map_garmin([garmin_row]), _map_intervals([intervals_row]))
    return bool(_duplicate_ids(sessions, ProviderId.GARMIN))


def _ride(
    activity_id: str,
    *,
    provider: ProviderId | None = ProviderId.INTERVALS,
    recorded_by: RecordingOrigin = RecordingOrigin.WAHOO,
    started_at: datetime = datetime(2026, 6, 1, 7, 0, tzinfo=BERLIN),
    duration_s: float | None = 3600.0,
    distance_m: float | None = 30000.0,
    sport: Sport = Sport.RIDE,
    elapsed_duration_s: float | None = None,
) -> ActivityRecord:
    """Build a canonical ride directly, for values the mappers never produce."""
    return ActivityRecord(
        activity_id=activity_id,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED
            if provider is not None
            else SourceKind.DERIVED,
            source_record_id=activity_id,
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED_AT if provider is not None else None,
            label=None,
        ),
        sport=sport,
        environment=Environment.UNKNOWN,
        started_at=started_at,
        duration_s=duration_s,
        distance_m=distance_m,
        load=None,
        load_model=LoadModel.UNKNOWN,
        avg_hr=None,
        avg_power=None,
        name=None,
        elapsed_duration_s=elapsed_duration_s,
    )


class GarminIntervalsPairTests(unittest.TestCase):
    """Garmin-provider record against one Intervals record, both rules at once."""

    def assert_pair(
        self, garmin_row: dict[str, Any], intervals_row: dict[str, Any], expected: bool
    ) -> None:
        self.assertEqual(
            expected,
            garmin_activity_duplicates_intervals(garmin_row, [intervals_row]),
            "legacy",
        )
        self.assertEqual(
            expected,
            _canonical_garmin_duplicate(garmin_row, intervals_row),
            "canonical",
        )

    def test_start_window_is_inclusive_at_thirty_minutes(self) -> None:
        self.assert_pair(
            garmin_ride(startTimeLocal="2026-06-01 06:30:00"), intervals_ride(), True
        )
        self.assert_pair(
            garmin_ride(startTimeLocal="2026-06-01 06:29:00"), intervals_ride(), False
        )
        self.assert_pair(
            garmin_ride(startTimeLocal="2026-06-01 07:30:00"), intervals_ride(), True
        )
        self.assert_pair(
            garmin_ride(startTimeLocal="2026-06-01 07:31:00"), intervals_ride(), False
        )

    def test_duration_floor_is_120_seconds_for_short_rides(self) -> None:
        short = intervals_ride(moving_time=1000)
        self.assert_pair(garmin_ride(duration=1120.0), short, True)
        self.assert_pair(garmin_ride(duration=1121.0), short, False)

    def test_duration_tolerance_is_ten_percent_of_intervals_for_long_rides(
        self,
    ) -> None:
        long_ride = intervals_ride(moving_time=5000)
        self.assert_pair(garmin_ride(duration=5500.0), long_ride, True)
        self.assert_pair(garmin_ride(duration=5501.0), long_ride, False)

    def test_distance_floor_is_500_metres_for_short_rides(self) -> None:
        short = intervals_ride(distance=4000.0)
        self.assert_pair(garmin_ride(distance=4500.0), short, True)
        self.assert_pair(garmin_ride(distance=4501.0), short, False)

    def test_distance_tolerance_is_ten_percent_of_intervals_for_long_rides(
        self,
    ) -> None:
        long_ride = intervals_ride(distance=88500.0)
        self.assert_pair(garmin_ride(distance=97350.0), long_ride, True)
        self.assert_pair(garmin_ride(distance=97351.0), long_ride, False)

    def test_missing_or_zero_distance_is_skipped_and_duration_still_decides(
        self,
    ) -> None:
        self.assert_pair(garmin_ride(distance=0), intervals_ride(), True)
        self.assert_pair(garmin_ride(distance=None), intervals_ride(), True)
        self.assert_pair(garmin_ride(), intervals_ride(distance=0), True)
        self.assert_pair(garmin_ride(duration=None), intervals_ride(), True)

    def test_garmin_moving_duration_is_a_second_duration_candidate(self) -> None:
        # Garmin duration is elapsed time (4500 s); Intervals reports moving time.
        walk = {"activityType": {"typeKey": "walking"}, "distance": 5000.0}
        intervals = intervals_ride(type="Walk", moving_time=3620, distance=5000.0)
        self.assert_pair(
            garmin_ride(duration=4500.0, movingDuration=3600.0, **walk), intervals, True
        )
        self.assert_pair(
            garmin_ride(duration=4500.0, movingDuration=3000.0, **walk),
            intervals,
            False,
        )
        self.assert_pair(garmin_ride(duration=4500.0, **walk), intervals, False)

    def test_garmin_elapsed_duration_may_match_the_intervals_elapsed_time(
        self,
    ) -> None:
        # Garmin sends no moving time for this walk; Intervals.icu moving time is
        # much shorter than the elapsed time of both recordings.
        walk = garmin_ride(
            activityType={"typeKey": "walking"}, duration=4500.0, distance=5000.0
        )
        intervals = intervals_ride(type="Walk", moving_time=2400, distance=5000.0)
        self.assert_pair(walk, {**intervals, "elapsed_time": 4520}, True)
        self.assert_pair(walk, {**intervals, "elapsed_time": 5200}, False)
        self.assert_pair(walk, intervals, False)
        # An agreeing elapsed time does not override the distance or the start.
        self.assert_pair(
            {**walk, "distance": 9000.0}, {**intervals, "elapsed_time": 4520}, False
        )
        self.assert_pair(
            {**walk, "startTimeLocal": "2026-06-01 07:31:00"},
            {**intervals, "elapsed_time": 4520},
            False,
        )

    def test_a_matching_moving_duration_does_not_override_distance(self) -> None:
        self.assert_pair(
            garmin_ride(duration=4500.0, movingDuration=3600.0, distance=40000.0),
            intervals_ride(moving_time=3620),
            False,
        )

    def test_missing_intervals_duration_leaves_distance_to_decide(self) -> None:
        self.assert_pair(garmin_ride(), intervals_ride(moving_time=None), True)

    def test_no_comparable_measurement_is_not_a_duplicate(self) -> None:
        self.assert_pair(
            garmin_ride(duration=None, distance=None), intervals_ride(), False
        )
        self.assert_pair(
            garmin_ride(duration=None, distance=None),
            intervals_ride(moving_time=None, distance=None),
            False,
        )

    def test_other_family_matches_any_sport_and_named_families_must_agree(
        self,
    ) -> None:
        self.assert_pair(
            garmin_ride(activityType={"typeKey": "walking"}), intervals_ride(), True
        )
        self.assert_pair(
            garmin_ride(activityType={"typeKey": "running"}),
            intervals_ride(),
            False,
        )
        self.assert_pair(
            garmin_ride(activityType={"typeKey": "running"}),
            intervals_ride(type="Other"),
            True,
        )

    def test_spring_forward_compares_wall_clock_not_elapsed_instants(self) -> None:
        # 01:50 CET and 03:10 CEST are 20 minutes apart on the instant but
        # 80 minutes apart on the wall clock, so neither rule matches them.
        self.assert_pair(
            garmin_ride(startTimeLocal="2026-03-29 03:10:00"),
            intervals_ride(start_date_local="2026-03-29T01:50:00"),
            False,
        )
        self.assert_pair(
            garmin_ride(startTimeLocal="2026-03-29 03:20:00"),
            intervals_ride(start_date_local="2026-03-29T03:00:00"),
            True,
        )

    def test_fall_back_overlap_uses_first_occurrence_on_both_sides(self) -> None:
        self.assert_pair(
            garmin_ride(startTimeLocal="2026-10-25 02:25:00"),
            intervals_ride(start_date_local="2026-10-25T02:10:00"),
            True,
        )


class DocumentedDeviationTests(unittest.TestCase):
    """Cases where canonical records cannot reproduce a legacy field read.

    The canonical duration is ``duration`` (or ``movingTime``) for Garmin and
    ``moving_time`` (or ``elapsed_time``) for Intervals, as the mappers document.
    The legacy rules read only one field per side, so these differ on purpose.
    """

    def test_intervals_without_moving_time_uses_elapsed_time(self) -> None:
        # Legacy skips the duration comparison when moving_time is absent. The
        # canonical duration is elapsed_time (4500 s), which differs from the
        # Garmin 3600 s by more than the tolerance.
        row = intervals_ride(moving_time=None, elapsed_time=4500)
        self.assertTrue(garmin_activity_duplicates_intervals(garmin_ride(), [row]))
        self.assertFalse(_canonical_garmin_duplicate(garmin_ride(), row))

    def test_zero_intervals_moving_time_falls_back_to_elapsed_time(self) -> None:
        # Legacy compares a zero moving_time as zero and only the Garmin elapsed
        # duration (4500 s) with elapsed_time, so it rejects the pair. The
        # canonical duration ignores the zero and uses elapsed_time (3600 s),
        # which the Garmin moving duration matches.
        garmin = garmin_ride(duration=4500.0, movingDuration=3600.0)
        row = intervals_ride(moving_time=0, elapsed_time=3600)
        self.assertFalse(garmin_activity_duplicates_intervals(garmin, [row]))
        self.assertTrue(_canonical_garmin_duplicate(garmin, row))

    def test_zero_garmin_duration_falls_back_to_moving_time_only_in_legacy(
        self,
    ) -> None:
        # Legacy reads ``duration or movingTime``, so a zero duration falls back
        # to movingTime. The canonical duration keeps the zero it was sent.
        row = garmin_ride(duration=0.0, movingTime=3600.0)
        self.assertTrue(garmin_activity_duplicates_intervals(row, [intervals_ride()]))
        self.assertFalse(_canonical_garmin_duplicate(row, intervals_ride()))

    def test_nonexistent_garmin_wall_time_moves_forward_in_canonical(self) -> None:
        # 02:50 does not exist on the spring-forward day. Legacy compares the
        # naive 02:50 (20 minutes from 03:10). Canonical localises it to 03:50
        # CEST (40 minutes from 03:10), as local_time documents.
        garmin = garmin_ride(startTimeLocal="2026-03-29 02:50:00")
        row = intervals_ride(start_date_local="2026-03-29T03:10:00")
        self.assertTrue(garmin_activity_duplicates_intervals(garmin, [row]))
        self.assertFalse(_canonical_garmin_duplicate(garmin, row))


class WahooGarminRideTests(unittest.TestCase):
    """Two Intervals rides: a Wahoo recording and a Garmin copy of it."""

    def assert_wahoo_pair(
        self, left: dict[str, Any], right: dict[str, Any], expected: bool
    ) -> None:
        self.assertEqual(expected, intervals_cycling_activities_match(left, right))
        sessions = _bundle(_map_intervals([left, right]))
        paired = [session for session in sessions if session.duplicates]
        self.assertEqual(expected, bool(paired), "canonical")
        if paired:
            self.assertEqual("wahoo-1", paired[0].primary.activity_id)
            self.assertEqual("garmin-copy-1", paired[0].duplicates[0].activity_id)

    def test_matching_wahoo_and_garmin_copy_pair(self) -> None:
        self.assert_wahoo_pair(_wahoo(), _garmin_copy(), True)

    def test_start_window_is_inclusive_at_thirty_minutes(self) -> None:
        self.assert_wahoo_pair(
            _wahoo(), _garmin_copy(start_date_local="2026-06-01T07:30:00"), True
        )
        self.assert_wahoo_pair(
            _wahoo(), _garmin_copy(start_date_local="2026-06-01T07:31:00"), False
        )

    def test_duration_tolerance_is_relative_to_the_larger_side(self) -> None:
        self.assert_wahoo_pair(_wahoo(), _garmin_copy(moving_time=4000), True)
        self.assert_wahoo_pair(_wahoo(), _garmin_copy(moving_time=4001), False)

    def test_distance_floor_is_500_metres(self) -> None:
        self.assert_wahoo_pair(
            _wahoo(distance=1000.0), _garmin_copy(distance=1500.0), True
        )
        self.assert_wahoo_pair(
            _wahoo(distance=1000.0), _garmin_copy(distance=1501.0), False
        )

    def test_missing_or_zero_measurements_never_match(self) -> None:
        self.assert_wahoo_pair(_wahoo(), _garmin_copy(distance=None), False)
        self.assert_wahoo_pair(_wahoo(), _garmin_copy(distance=0), False)
        self.assert_wahoo_pair(_wahoo(), _garmin_copy(moving_time=None), False)

    def test_only_cycling_rides_pair(self) -> None:
        self.assert_wahoo_pair(_wahoo(), _garmin_copy(type="Run"), False)
        self.assert_wahoo_pair(_wahoo(type="Run"), _garmin_copy(), False)

    def test_intervals_zero_moving_time_falls_back_to_elapsed_time(self) -> None:
        # Legacy rejects a zero moving_time outright. Canonical uses the 3600 s
        # elapsed_time, which matches the Wahoo ride.
        self.assertFalse(
            intervals_cycling_activities_match(
                _wahoo(), _garmin_copy(moving_time=0, elapsed_time=3600)
            )
        )
        sessions = _bundle(
            _map_intervals([_wahoo(), _garmin_copy(moving_time=0, elapsed_time=3600)])
        )
        self.assertTrue(any(session.duplicates for session in sessions))

    def test_zero_canonical_duration_never_matches(self) -> None:
        # The mappers never produce a zero duration, so build the record directly.
        sessions = _bundle(
            [
                _ride("wahoo-1", recorded_by=RecordingOrigin.WAHOO, duration_s=0.0),
                _ride(
                    "garmin-copy-1",
                    recorded_by=RecordingOrigin.GARMIN,
                    duration_s=3600.0,
                ),
            ]
        )
        self.assertFalse(any(session.duplicates for session in sessions))


class FixtureParityTests(unittest.TestCase):
    """Parity on the shared provider fixtures."""

    def setUp(self) -> None:
        self.intervals_rows = _load_fixture("intervals", "activities.json")
        self.garmin_rows = _load_fixture("garmin", "activities.json")

    def test_garmin_fixture_duplicates_match_the_pairwise_rule(self) -> None:
        legacy_removed = {
            str(row["activityId"])
            for row in self.garmin_rows
            if garmin_activity_duplicates_intervals(row, self.intervals_rows)
        }
        count = len(legacy_removed)
        sessions = _bundle(
            _map_garmin(self.garmin_rows), _map_intervals(self.intervals_rows)
        )
        self.assertEqual(1, count)
        self.assertEqual({"910001"}, legacy_removed)
        self.assertEqual(legacy_removed, _duplicate_ids(sessions, ProviderId.GARMIN))

    def test_intervals_fixture_alone_has_no_duplicates(self) -> None:
        sessions = _bundle(_map_intervals(self.intervals_rows))
        self.assertEqual(len(self.intervals_rows), len(sessions))
        self.assertTrue(all(not session.duplicates for session in sessions))

    def test_dst_fixture_runs_match_only_their_wall_clock_neighbour(self) -> None:
        # i-act-002 (01:59 CET) and i-act-003 (03:01 CEST) are 2 minutes apart on
        # the instant and 62 minutes apart on the wall clock.
        before, after = (
            row
            for row in self.intervals_rows
            if row["id"] in ("i-act-002", "i-act-003")
        )
        garmin_run = {
            "activityId": 920001,
            "activityType": {"typeKey": "running"},
            "startTimeLocal": "2026-03-29 03:01:00",
            "duration": 2300.0,
            "distance": 7200.0,
        }
        self.assertFalse(garmin_activity_duplicates_intervals(garmin_run, [before]))
        self.assertTrue(garmin_activity_duplicates_intervals(garmin_run, [after]))
        self.assertFalse(_canonical_garmin_duplicate(garmin_run, before))
        self.assertTrue(_canonical_garmin_duplicate(garmin_run, after))

    def test_fixture_ride_recorded_twice_matches_legacy_wahoo_rule(self) -> None:
        ride = next(row for row in self.intervals_rows if row["id"] == "i-act-001")
        wahoo = dict(ride, id="w-1", device_name="Wahoo ELEMNT")
        copy = dict(
            ride,
            id="g-1",
            device_name="Garmin Edge 1040",
            external_id="garmin-1",
            moving_time=5410,
            distance=88600.0,
        )
        self.assertTrue(intervals_cycling_activities_match(wahoo, copy))
        sessions = _bundle(_map_intervals([wahoo, copy]))
        self.assertEqual(1, len(sessions))
        self.assertEqual("w-1", sessions[0].primary.activity_id)
        self.assertEqual(["g-1"], [d.activity_id for d in sessions[0].duplicates])


class LatestWahooDifferenceTests(unittest.TestCase):
    def test_latest_wahoo_duplicate_only_reports_pairs_with_newest_activity(
        self,
    ) -> None:
        # The Wahoo ride and its Garmin copy are older than a newer run. The
        # latest-pair view only considers pairs containing the newest
        # activity, so it reports nothing. Session bundling reports the pair.
        wahoo = _wahoo()
        copy = _garmin_copy()
        newest_run = intervals_ride(
            id="i-run", type="Run", start_date_local="2026-06-02T07:00:00"
        )
        records = _map_intervals([wahoo, copy, newest_run])
        self.assertIsNone(latest_wahoo_garmin_duplicate(records, zone=BERLIN))
        sessions = _bundle(_map_intervals([wahoo, copy, newest_run]))
        paired = [session for session in sessions if session.duplicates]
        self.assertEqual(1, len(paired))
        self.assertEqual("wahoo-1", paired[0].primary.activity_id)


class PublicCopyMatchTests(unittest.TestCase):
    def test_public_predicate_applies_the_pair_rule_on_the_wall_clock(self) -> None:
        wahoo, copy = _map_intervals([_wahoo(), _garmin_copy()])
        late = _map_intervals([_garmin_copy(start_date_local="2026-06-01T07:31:00")])[0]

        self.assertTrue(wahoo_garmin_copy_match(wahoo, copy, zone=BERLIN))
        self.assertFalse(wahoo_garmin_copy_match(wahoo, late, zone=BERLIN))


class SessionStructureTests(unittest.TestCase):
    def test_empty_input_yields_no_sessions(self) -> None:
        self.assertEqual((), bundle_sessions([], zone=BERLIN))

    def test_accepts_any_iterable(self) -> None:
        records = _map_intervals([_wahoo(), _garmin_copy()])
        self.assertEqual(
            bundle_sessions(records, zone=BERLIN),
            bundle_sessions(iter(records), zone=BERLIN),
        )

    def test_an_elapsed_match_joins_only_a_session_without_a_garmin_record(
        self,
    ) -> None:
        # Two short walks 20 minutes apart. The first Garmin walk matches the early
        # copy by moving time; the second has no moving time, and its elapsed time
        # agrees with both copies.
        early, late = _map_intervals(
            [
                intervals_ride(
                    id="early",
                    type="Walk",
                    start_date_local="2026-06-01T07:00:00",
                    moving_time=1500,
                    elapsed_time=1800,
                    distance=2000.0,
                ),
                intervals_ride(
                    id="late",
                    type="Walk",
                    start_date_local="2026-06-01T07:20:00",
                    moving_time=1400,
                    elapsed_time=1800,
                    distance=2000.0,
                ),
            ]
        )
        walk = {"activityType": {"typeKey": "walking"}, "distance": 2000.0}
        first, second = _map_garmin(
            [
                garmin_ride(
                    **walk, activityId=1, duration=1800.0, movingDuration=1500.0
                ),
                garmin_ride(
                    **walk,
                    activityId=2,
                    startTimeLocal="2026-06-01 07:20:00",
                    duration=1800.0,
                ),
            ]
        )

        def members(
            sessions: tuple[ActivitySession, ...],
        ) -> set[frozenset[str | None]]:
            return {
                frozenset(
                    record.provenance.source_record_id
                    for record in (session.primary, *session.duplicates)
                )
                for session in sessions
            }

        self.assertEqual(
            {frozenset({"early", "1"}), frozenset({"late", "2"})},
            members(_bundle([early, late], [first, second])),
        )
        # Without its own copy the second walk joins no session.
        self.assertEqual(
            {frozenset({"early", "1"}), frozenset({"2"})},
            members(_bundle([early], [first, second])),
        )
        # Alone, the second walk joins the earlier copy by its elapsed time.
        self.assertEqual(
            {frozenset({"early", "2"}), frozenset({"late"})},
            members(_bundle([early, late], [second])),
        )

    def test_a_wahoo_record_is_not_matched_by_the_intervals_elapsed_time(
        self,
    ) -> None:
        copy = _ride("copy", elapsed_duration_s=4500.0)
        wahoo = _ride("wahoo", provider=ProviderId.WAHOO, duration_s=4500.0)
        garmin = _ride(
            "garmin",
            provider=ProviderId.GARMIN,
            recorded_by=RecordingOrigin.GARMIN,
            duration_s=4500.0,
        )

        self.assertFalse(_duplicate_ids(_bundle([copy, wahoo]), ProviderId.WAHOO))
        self.assertEqual(
            {"garmin"}, _duplicate_ids(_bundle([copy, garmin]), ProviderId.GARMIN)
        )

    def test_every_record_appears_in_exactly_one_session(self) -> None:
        intervals_rows = _load_fixture("intervals", "activities.json")
        garmin_rows = _load_fixture("garmin", "activities.json")
        derived = _ride("derived-1", provider=None, recorded_by=RecordingOrigin.UNKNOWN)
        records = [
            *_map_intervals(intervals_rows),
            *_map_intervals([_wahoo(), _garmin_copy(id="garmin-copy-2")]),
            *_map_garmin(garmin_rows),
            derived,
        ]
        sessions = bundle_sessions(records, zone=BERLIN)
        placed = [
            (record.provenance.provider, record.activity_id)
            for session in sessions
            for record in (session.primary, *session.duplicates)
        ]
        self.assertCountEqual(
            [(record.provenance.provider, record.activity_id) for record in records],
            placed,
        )
        derived_session = next(
            session
            for session in sessions
            if session.primary.activity_id == "derived-1"
        )
        self.assertEqual((), derived_session.duplicates)

    def test_order_is_deterministic_regardless_of_input_order(self) -> None:
        later = intervals_ride(id="late", start_date_local="2026-06-03T07:00:00")
        records = [
            *_map_intervals([_wahoo(), _garmin_copy(), later]),
            *_map_garmin([garmin_ride()]),
        ]
        forward = bundle_sessions(records, zone=BERLIN)
        backward = bundle_sessions(list(reversed(records)), zone=BERLIN)
        self.assertEqual(forward, backward)
        starts = [session.primary.started_at for session in forward]
        self.assertEqual(sorted(starts), starts)

    def test_first_match_wins_when_a_garmin_record_matches_two_intervals_rides(
        self,
    ) -> None:
        records = _map_intervals(
            [
                intervals_ride(id="early", start_date_local="2026-06-01T07:00:00"),
                intervals_ride(id="late", start_date_local="2026-06-01T07:20:00"),
            ]
        ) + _map_garmin([garmin_ride(startTimeLocal="2026-06-01 07:10:00")])
        sessions = bundle_sessions(records, zone=BERLIN)
        by_primary = {session.primary.activity_id: session for session in sessions}
        self.assertEqual(["1"], [d.activity_id for d in by_primary["early"].duplicates])
        self.assertEqual((), by_primary["late"].duplicates)

    def test_one_wahoo_ride_keeps_every_garmin_copy_once(self) -> None:
        records = _map_intervals(
            [
                _wahoo(),
                _garmin_copy(id="garmin-copy-1"),
                _garmin_copy(id="garmin-copy-2"),
            ]
        )
        sessions = bundle_sessions(records, zone=BERLIN)
        self.assertEqual(1, len(sessions))
        self.assertCountEqual(
            ["garmin-copy-1", "garmin-copy-2"],
            [d.activity_id for d in sessions[0].duplicates],
        )

    def test_garmin_copy_with_two_wahoo_candidates_takes_the_earlier_start(
        self,
    ) -> None:
        records = _map_intervals(
            [
                _wahoo(id="wahoo-early", start_date_local="2026-06-01T06:45:00"),
                _wahoo(id="wahoo-late", start_date_local="2026-06-01T07:10:00"),
                _garmin_copy(
                    id="garmin-copy-1", start_date_local="2026-06-01T07:10:00"
                ),
            ]
        )
        by_primary = {
            session.primary.activity_id: session
            for session in bundle_sessions(records, zone=BERLIN)
        }
        self.assertEqual(
            ["garmin-copy-1"],
            [d.activity_id for d in by_primary["wahoo-early"].duplicates],
        )
        self.assertEqual((), by_primary["wahoo-late"].duplicates)

    def test_garmin_record_resolves_to_a_direct_wahoo_target_before_a_copy(
        self,
    ) -> None:
        records = _map_intervals(
            [
                _wahoo(id="wahoo-1", start_date_local="2026-06-01T06:50:00"),
                _garmin_copy(
                    id="garmin-copy-1", start_date_local="2026-06-01T07:00:00"
                ),
            ]
        ) + _map_garmin([garmin_ride(startTimeLocal="2026-06-01 07:05:00")])
        sessions = bundle_sessions(records, zone=BERLIN)
        self.assertEqual(1, len(sessions))
        self.assertEqual("wahoo-1", sessions[0].primary.activity_id)
        self.assertCountEqual(
            ["garmin-copy-1", "1"],
            [d.activity_id for d in sessions[0].duplicates],
        )

    def test_garmin_record_joins_the_wahoo_session_through_a_garmin_copy(self) -> None:
        # The Garmin record matches the Garmin copy and the Wahoo ride. It joins
        # the Wahoo session, because the copy is already a duplicate there.
        records = [
            *_map_intervals([_wahoo(), _garmin_copy()]),
            *_map_garmin([garmin_ride()]),
        ]
        sessions = bundle_sessions(records, zone=BERLIN)
        self.assertEqual(1, len(sessions))
        self.assertEqual("wahoo-1", sessions[0].primary.activity_id)
        self.assertCountEqual(
            ["garmin-copy-1", "1"], [d.activity_id for d in sessions[0].duplicates]
        )

    def test_unmatched_garmin_record_is_its_own_session(self) -> None:
        records = _map_garmin([garmin_ride(startTimeLocal="2026-06-05 07:00:00")])
        sessions = bundle_sessions(records, zone=BERLIN)
        self.assertEqual(1, len(sessions))
        self.assertEqual((), sessions[0].duplicates)


DST_ANCHORS = (
    # Berlin springs forward at 01:00 UTC on 2026-03-29 (02:00 CET to 03:00 CEST).
    datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
    # Berlin falls back at 01:00 UTC on 2026-10-25 (03:00 CEST to 02:00 CET).
    datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
)
START_OFFSETS_MIN = (-61, -31, -30, -29, -1, 0, 1, 29, 30, 31, 61)
SAMPLE_PROVIDERS = (
    ProviderId.INTERVALS,
    ProviderId.INTERVALS,
    ProviderId.GARMIN,
    ProviderId.GARMIN,
    None,
)
SAMPLE_ORIGINS = (
    RecordingOrigin.WAHOO,
    RecordingOrigin.GARMIN,
    RecordingOrigin.UNKNOWN,
)
SAMPLE_SPORTS = (Sport.RIDE, Sport.RIDE, Sport.RIDE, Sport.RUN, Sport.WALK, Sport.OTHER)
SAMPLE_DURATIONS_S: tuple[float | None, ...] = (
    None,
    0.0,
    1.0,
    119.0,
    120.0,
    121.0,
    3600.0,
    3600.0,
    3660.0,
    4000.0,
    4200.0,
    5400.0,
)
SAMPLE_DISTANCES_M: tuple[float | None, ...] = (
    None,
    0.0,
    499.0,
    500.0,
    501.0,
    30000.0,
    30500.0,
    33000.0,
    60000.0,
    88500.0,
)
SCALE_START = datetime(2026, 1, 1, tzinfo=UTC)
# Each slot holds one Wahoo ride, one Garmin copy and one Garmin record: 5,001 total.
SCALE_SLOTS = 1667


def _quadratic_bundle_sessions(
    records: Iterable[ActivityRecord], *, zone: tzinfo
) -> tuple[ActivitySession, ...]:
    """Return sessions from the all-pairs comparison that the window search replaced.

    Every record is compared with every candidate in start order. The rule
    predicates are the module's own, so parity isolates the candidate search.
    """
    entries = [
        _Entry(record, _wall_clock(record, zone), legacy_activity_family(record.sport))
        for record in sorted(records, key=_order_key)
    ]
    duplicate_of: dict[int, int] = {}
    wahoo_rides = [
        index
        for index, entry in enumerate(entries)
        if _is_intervals_ride(entry.record, RecordingOrigin.WAHOO)
    ]
    garmin_copies = [
        index
        for index, entry in enumerate(entries)
        if _is_intervals_ride(entry.record, RecordingOrigin.GARMIN)
    ]
    for copy_index in garmin_copies:
        for wahoo_index in wahoo_rides:
            if _wahoo_and_garmin_copy_match(entries[wahoo_index], entries[copy_index]):
                duplicate_of[copy_index] = wahoo_index
                break
    unmatched = []
    for index, entry in enumerate(entries):
        if entry.record.provenance.provider is not ProviderId.GARMIN:
            continue
        for target_index, target in enumerate(entries):
            if _is_intervals(target.record) and _garmin_matches_intervals(
                entry, target
            ):
                duplicate_of[index] = duplicate_of.get(target_index, target_index)
                break
        else:
            unmatched.append(index)
    for index in unmatched:
        joined = {
            primary
            for duplicate, primary in duplicate_of.items()
            if entries[duplicate].record.provenance.provider is ProviderId.GARMIN
        }
        for target_index, target in enumerate(entries):
            if (
                _is_intervals(target.record)
                and duplicate_of.get(target_index, target_index) not in joined
                and _garmin_matches_intervals(entries[index], target, elapsed=True)
            ):
                duplicate_of[index] = duplicate_of.get(target_index, target_index)
                break
    members: dict[int, list[ActivityRecord]] = {
        index: [] for index in range(len(entries)) if index not in duplicate_of
    }
    for index, entry in enumerate(entries):
        if index in duplicate_of:
            members[duplicate_of[index]].append(entry.record)
    return tuple(
        ActivitySession(entries[primary].record, tuple(duplicates))
        for primary, duplicates in members.items()
    )


def _generated_records(seed: int, count: int = 300) -> list[ActivityRecord]:
    """Return a seeded mix of Intervals, Garmin and derived records around DST edges.

    Starts cluster around event instants so that candidates, ties and offsets at
    exactly the 30-minute boundary all occur. The DST anchors put starts on both
    sides of the spring gap and of the autumn overlap.
    """
    rng = random.Random(seed)
    events: list[datetime] = list(DST_ANCHORS)
    events.extend(
        datetime(2026, 1, 1, tzinfo=UTC)
        + timedelta(days=rng.randrange(365), hours=rng.randrange(24))
        for _ in range(12)
    )
    records: list[ActivityRecord] = []
    for index in range(count):
        if rng.random() < 0.5:
            offset = rng.choice(START_OFFSETS_MIN)
        else:
            offset = rng.randint(-150, 150)
        provider = rng.choice(SAMPLE_PROVIDERS)
        prefix = "d" if provider is None else provider.value[0]
        records.append(
            _ride(
                f"{prefix}-{index}",
                provider=provider,
                recorded_by=rng.choice(SAMPLE_ORIGINS),
                sport=rng.choice(SAMPLE_SPORTS),
                started_at=rng.choice(events) + timedelta(minutes=offset),
                duration_s=rng.choice(SAMPLE_DURATIONS_S),
                distance_m=rng.choice(SAMPLE_DISTANCES_M),
                elapsed_duration_s=rng.choice(SAMPLE_DURATIONS_S),
            )
        )
    return records


class WindowSearchParityTests(unittest.TestCase):
    """The window search returns exactly the sessions of the quadratic reference."""

    def assert_parity(
        self, records: list[ActivityRecord]
    ) -> tuple[ActivitySession, ...]:
        expected = _quadratic_bundle_sessions(records, zone=BERLIN)
        self.assertEqual(expected, bundle_sessions(records, zone=BERLIN))
        return expected

    def test_fixture_sets_match_the_quadratic_reference(self) -> None:
        intervals = _map_intervals(_load_fixture("intervals", "activities.json"))
        garmin = _map_garmin(_load_fixture("garmin", "activities.json"))
        for name, records in (
            ("intervals", intervals),
            ("garmin", garmin),
            ("combined", [*intervals, *garmin]),
        ):
            with self.subTest(name):
                sessions = self.assert_parity(records)
                if name == "combined":
                    self.assertTrue(any(session.duplicates for session in sessions))

    def test_inline_scenarios_match_the_quadratic_reference(self) -> None:
        scenarios = (
            [
                *_map_intervals([_wahoo(), _garmin_copy()]),
                *_map_garmin([garmin_ride()]),
            ],
            _map_intervals(
                [
                    intervals_ride(id="early", start_date_local="2026-06-01T07:00:00"),
                    intervals_ride(id="late", start_date_local="2026-06-01T07:20:00"),
                    _wahoo(id="w-1", start_date_local="2026-06-01T07:10:00"),
                    _garmin_copy(id="g-1", start_date_local="2026-06-01T07:10:00"),
                ]
            )
            + _map_garmin([garmin_ride(startTimeLocal="2026-06-01 07:10:00")]),
        )
        for index, records in enumerate(scenarios):
            with self.subTest(index):
                self.assert_parity(records)

    def test_generated_sets_match_the_quadratic_reference(self) -> None:
        for seed in range(4):
            with self.subTest(seed=seed):
                records = _generated_records(seed)
                sessions = self.assert_parity(records)
                self.assertTrue(any(session.duplicates for session in sessions))
                shuffled = list(records)
                random.Random(seed + 100).shuffle(shuffled)
                self.assert_parity(shuffled)


class WindowSearchEdgeTests(unittest.TestCase):
    def test_window_at_the_datetime_limits_saturates_instead_of_overflowing(
        self,
    ) -> None:
        low = datetime.min.replace(tzinfo=UTC)
        high = datetime.max.replace(tzinfo=UTC)
        records = [
            _ride(
                "intervals-low",
                recorded_by=RecordingOrigin.WAHOO,
                started_at=low + timedelta(minutes=10),
            ),
            _ride("garmin-low", provider=ProviderId.GARMIN, started_at=low),
            _ride(
                "intervals-high",
                recorded_by=RecordingOrigin.WAHOO,
                started_at=high - timedelta(minutes=10),
            ),
            _ride("garmin-high", provider=ProviderId.GARMIN, started_at=high),
        ]
        sessions = bundle_sessions(records, zone=UTC)
        pairs = {
            session.primary.activity_id: [d.activity_id for d in session.duplicates]
            for session in sessions
        }
        self.assertEqual(
            {"intervals-low": ["garmin-low"], "intervals-high": ["garmin-high"]},
            pairs,
        )


class WindowSearchScalingTests(unittest.TestCase):
    def test_five_thousand_records_compare_only_candidates_in_their_window(
        self,
    ) -> None:
        records: list[ActivityRecord] = []
        for slot in range(SCALE_SLOTS):
            started_at = SCALE_START + timedelta(hours=slot)
            records.append(
                _ride(
                    f"wahoo-{slot}",
                    recorded_by=RecordingOrigin.WAHOO,
                    started_at=started_at,
                )
            )
            records.append(
                _ride(
                    f"copy-{slot}",
                    recorded_by=RecordingOrigin.GARMIN,
                    started_at=started_at,
                )
            )
            records.append(
                _ride(
                    f"garmin-{slot}", provider=ProviderId.GARMIN, started_at=started_at
                )
            )
        with (
            mock.patch.object(
                canonical_sessions,
                "_wahoo_and_garmin_copy_match",
                wraps=canonical_sessions._wahoo_and_garmin_copy_match,
            ) as copy_checks,
            mock.patch.object(
                canonical_sessions,
                "_garmin_matches_intervals",
                wraps=canonical_sessions._garmin_matches_intervals,
            ) as garmin_checks,
        ):
            sessions = bundle_sessions(records, zone=BERLIN)
        self.assertEqual(5001, len(records))
        self.assertEqual(SCALE_SLOTS, len(sessions))
        self.assertTrue(all(len(session.duplicates) == 2 for session in sessions))
        # Slots are one hour apart, so each copy has one Wahoo candidate in its
        # window and each Garmin record has two Intervals candidates. The all-pairs
        # scan would make about 2.8 million copy and 5.6 million Garmin comparisons.
        self.assertEqual(SCALE_SLOTS, copy_checks.call_count)
        self.assertEqual(2 * SCALE_SLOTS, garmin_checks.call_count)


if __name__ == "__main__":
    unittest.main()
