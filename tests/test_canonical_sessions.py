"""Session bundling of Garmin- and Wahoo-provider records.

Stored Intervals.icu copies never reach the bundling (#2148); session linking
leaves them out, which ``test_session_linking`` covers.
"""

from __future__ import annotations

import itertools
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
    bundle_sessions,
)
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
from backend.providers.garmin_activity_mapping import map_garmin_activities

BERLIN = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers"


def _load_fixture(provider: str, name: str) -> list[dict[str, Any]]:
    with (FIXTURES / provider / name).open(encoding="utf-8") as handle:
        loaded: list[dict[str, Any]] = json.load(handle)
    return loaded


def _map_garmin(rows: list[dict[str, Any]]) -> list[ActivityRecord]:
    result = map_garmin_activities(rows, zone=BERLIN, retrieved_at=RETRIEVED_AT)
    if len(result.records) != len(rows):
        raise AssertionError(f"Garmin rows not mapped: {result.issues!r}")
    return list(result.records)


def _bundle(*groups: Iterable[ActivityRecord]) -> tuple[ActivitySession, ...]:
    return bundle_sessions(
        [record for group in groups for record in group], zone=BERLIN
    )


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


class PrimaryRankTests(unittest.TestCase):
    """The Wahoo record leads its session, whatever the input order."""

    def test_wahoo_leads_its_garmin_copies(self) -> None:
        wahoo = _ride("w-1", provider=ProviderId.WAHOO)
        watch = _ride(
            "g-1", provider=ProviderId.GARMIN, recorded_by=RecordingOrigin.GARMIN
        )
        relay = _ride("g-2", provider=ProviderId.GARMIN)

        for ordered in ([relay, watch, wahoo], [wahoo, watch, relay]):
            (session,) = bundle_sessions(ordered, zone=BERLIN)

            self.assertEqual("w-1", session.primary.activity_id)
            self.assertCountEqual(
                ["g-1", "g-2"], [d.activity_id for d in session.duplicates]
            )


class SessionStructureTests(unittest.TestCase):
    def test_garmin_and_wahoo_records_bundle_as_recorded(self) -> None:
        # Recorded before #2148 removed the Intervals.icu pairing: without such
        # copies, every Garmin and Wahoo session stays exactly as it was.
        def at(hour: int, minute: int) -> datetime:
            return datetime(2026, 6, 1, hour, minute, tzinfo=BERLIN)

        wahoo: dict[str, Any] = {
            "provider": ProviderId.WAHOO,
            "recorded_by": RecordingOrigin.WAHOO,
        }
        watch: dict[str, Any] = {
            "provider": ProviderId.GARMIN,
            "recorded_by": RecordingOrigin.GARMIN,
        }
        relay: dict[str, Any] = {
            "provider": ProviderId.GARMIN,
            "recorded_by": RecordingOrigin.WAHOO,
        }
        walk: dict[str, Any] = {"sport": Sport.WALK, "distance_m": None}
        records = [
            _ride("w-ride", started_at=at(7, 0), **wahoo),
            _ride(
                "g-watch",
                started_at=at(7, 1),
                duration_s=3590.0,
                distance_m=30100.0,
                **watch,
            ),
            _ride("g-relay", started_at=at(7, 0), **relay),
            _ride(
                "g-run",
                started_at=at(9, 0),
                sport=Sport.RUN,
                distance_m=10000.0,
                duration_s=3000.0,
                **watch,
            ),
            _ride("w-walk", started_at=at(12, 5), duration_s=1800.0, **walk, **wahoo),
            _ride("g-walk", started_at=at(12, 0), duration_s=1850.0, **walk, **watch),
            _ride("w-a", started_at=at(18, 0), **wahoo),
            _ride("w-b", started_at=at(18, 20), **wahoo),
            _ride("g-a", started_at=at(18, 1), **watch),
            _ride("g-b", started_at=at(18, 21), **watch),
            _ride("g-late", started_at=at(20, 0), **watch),
            _ride("w-late", started_at=at(20, 45), **wahoo),
        ]
        heuristic = ActivityLinkKind.HEURISTIC
        self.assertEqual(
            [
                ("w-ride", ("g-relay", "g-watch"), (heuristic, heuristic)),
                ("g-run", (), ()),
                ("w-walk", ("g-walk",), (heuristic,)),
                ("w-a", ("g-a",), (heuristic,)),
                ("w-b", ("g-b",), (heuristic,)),
                ("g-late", (), ()),
                ("w-late", (), ()),
            ],
            [
                (
                    session.primary.activity_id,
                    tuple(record.activity_id for record in session.duplicates),
                    session.link_kinds,
                )
                for session in bundle_sessions(records, zone=BERLIN)
            ],
        )

    def test_empty_input_yields_no_sessions(self) -> None:
        self.assertEqual((), bundle_sessions([], zone=BERLIN))

    def test_accepts_any_iterable(self) -> None:
        records = [
            _ride("w-1", provider=ProviderId.WAHOO),
            _ride("g-1", provider=ProviderId.GARMIN),
        ]
        self.assertEqual(
            bundle_sessions(records, zone=BERLIN),
            bundle_sessions(iter(records), zone=BERLIN),
        )

    def test_every_record_appears_in_exactly_one_session(self) -> None:
        garmin_rows = _load_fixture("garmin", "activities.json")
        derived = _ride("derived-1", provider=None, recorded_by=RecordingOrigin.UNKNOWN)
        records = [
            _ride("w-1", provider=ProviderId.WAHOO),
            _ride("g-copy", provider=ProviderId.GARMIN),
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
        records = [
            _ride("w-1", provider=ProviderId.WAHOO),
            _ride("g-copy", provider=ProviderId.GARMIN),
            _ride(
                "late",
                provider=ProviderId.WAHOO,
                started_at=datetime(2026, 6, 3, 7, 0, tzinfo=BERLIN),
            ),
            *_map_garmin([garmin_ride()]),
        ]
        forward = bundle_sessions(records, zone=BERLIN)
        backward = bundle_sessions(list(reversed(records)), zone=BERLIN)
        self.assertEqual(forward, backward)
        starts = [session.primary.started_at for session in forward]
        self.assertEqual(sorted(starts), starts)

    def test_unmatched_garmin_record_is_its_own_session(self) -> None:
        records = _map_garmin([garmin_ride(startTimeLocal="2026-06-05 07:00:00")])
        sessions = bundle_sessions(records, zone=BERLIN)
        self.assertEqual(1, len(sessions))
        self.assertEqual((), sessions[0].duplicates)


def _members(sessions: tuple[ActivitySession, ...]) -> set[frozenset[str]]:
    return {
        frozenset(
            record.activity_id for record in (session.primary, *session.duplicates)
        )
        for session in sessions
    }


def _assert_one_record_per_origin(
    test: unittest.TestCase, sessions: tuple[ActivitySession, ...]
) -> None:
    for session in sessions:
        keys = [
            (record.provenance.provider, record.provenance.recorded_by)
            for record in (session.primary, *session.duplicates)
        ]
        test.assertEqual(len(keys), len(set(keys)), session)


class OneToOneAssignmentTests(unittest.TestCase):
    """A session takes one record per provider and origin, closest pair first."""

    @staticmethod
    def _pair(
        name: str, minute: int, duration_s: float, distance_m: float | None = None
    ) -> list[ActivityRecord]:
        started_at = datetime(2026, 6, 1, 7, 0, tzinfo=BERLIN) + timedelta(
            minutes=minute
        )
        return [
            _ride(
                f"w-{name}",
                provider=ProviderId.WAHOO,
                started_at=started_at,
                duration_s=duration_s,
                distance_m=distance_m,
            ),
            _ride(
                f"g-{name}",
                provider=ProviderId.GARMIN,
                recorded_by=RecordingOrigin.GARMIN,
                started_at=started_at,
                duration_s=duration_s,
                distance_m=distance_m,
            ),
        ]

    def test_two_close_sessions_without_distance_each_keep_their_garmin_record(
        self,
    ) -> None:
        # Without a distance a copy must start within 10 minutes of its ride.
        records = [*self._pair("1", 0, 2400.0), *self._pair("2", 25, 2280.0)]
        sessions = _bundle(records)
        self.assertEqual(
            {frozenset({"w-1", "g-1"}), frozenset({"w-2", "g-2"})}, _members(sessions)
        )

    def test_three_sessions_in_fifty_minutes_with_mixed_distance(self) -> None:
        records = [
            *self._pair("1", 0, 1800.0, 10000.0),
            *self._pair("2", 25, 1500.0),
            *self._pair("3", 50, 1800.0, 10000.0),
        ]
        sessions = _bundle(list(reversed(records)))
        self.assertEqual(
            {
                frozenset({"w-1", "g-1"}),
                frozenset({"w-2", "g-2"}),
                frozenset({"w-3", "g-3"}),
            },
            _members(sessions),
        )

    def test_a_cheaper_pair_never_leaves_another_record_without_its_only_partner(
        self,
    ) -> None:
        # G-a pairs cheaper with W-1 (0.25) than with W-2 (0.28), but W-1 is the
        # only candidate of G-b: the maximal matching links both.
        def ride(name: str, provider: ProviderId, hour: int, minute: int, s: float):
            return _ride(
                name,
                provider=provider,
                recorded_by=RecordingOrigin.GARMIN,
                started_at=datetime(2026, 6, 1, hour, minute, tzinfo=BERLIN),
                duration_s=s,
            )

        records = [
            ride("w-1", ProviderId.WAHOO, 7, 0, 2400.0),
            ride("w-2", ProviderId.WAHOO, 7, 25, 2592.0),
            ride("g-a", ProviderId.GARMIN, 7, 0, 2592.0),
            ride("g-b", ProviderId.GARMIN, 6, 30, 2400.0),
        ]
        self.assertEqual(
            {frozenset({"w-1", "g-b"}), frozenset({"w-2", "g-a"})},
            _members(_bundle(records)),
        )

    def test_garmin_ride_joins_no_wahoo_session_that_already_has_garmin(
        self,
    ) -> None:
        wahoo = _ride("w", provider=ProviderId.WAHOO)
        garmin = [
            _ride(
                f"g-{index}",
                provider=ProviderId.GARMIN,
                recorded_by=RecordingOrigin.GARMIN,
            )
            for index in (1, 2)
        ]
        self.assertEqual(
            {frozenset({"w", "g-1"}), frozenset({"g-2"})},
            _members(_bundle([wahoo, *garmin])),
        )

    def test_matching_is_maximal_and_cheapest_against_brute_force(self) -> None:
        rng = random.Random(7)
        for _ in range(300):
            sources = list(range(rng.randint(1, 4)))
            primaries = list(range(10, 10 + rng.randint(1, 4)))
            edges = {
                source: {
                    primary: round(rng.random(), 2)
                    for primary in primaries
                    if rng.random() < 0.6
                }
                for source in sources
            }
            edges = {source: options for source, options in edges.items() if options}
            if not edges:
                continue
            best = (0, 0.0)
            for picks in itertools.product(
                *[[None, *sorted(edges[source])] for source in sorted(edges)]
            ):
                chosen = [primary for primary in picks if primary is not None]
                if len(chosen) != len(set(chosen)):
                    continue
                total = sum(
                    edges[source][primary]
                    for source, primary in zip(sorted(edges), picks, strict=True)
                    if primary is not None
                )
                best = max(best, (len(chosen), -total))
            matching: dict[int, int] = {}
            for group in canonical_sessions._candidate_groups(edges):
                matching.update(canonical_sessions._min_cost_matching(group, edges))
            self.assertEqual(len(set(matching.values())), len(matching))
            self.assertEqual(best[0], len(matching), edges)
            total = sum(edges[source][primary] for source, primary in matching.items())
            self.assertAlmostEqual(-best[1], total, places=9, msg=edges)

    def test_matching_with_float_noise_ties_terminates_one_to_one(self) -> None:
        # Equal costs in exact arithmetic that differ by float round-off.
        cost = 0.1 + 0.2
        edges = {
            source: {
                primary: cost + (source + primary) * 1e-17 for primary in (10, 11, 12)
            }
            for source in (0, 1, 2)
        }
        matching = canonical_sessions._min_cost_matching([0, 1, 2], edges)
        self.assertEqual(3, len(matching))
        self.assertEqual({10, 11, 12}, set(matching.values()))

    def test_generated_sessions_hold_one_record_per_provider_and_origin(
        self,
    ) -> None:
        for seed in range(4):
            with self.subTest(seed=seed):
                _assert_one_record_per_origin(
                    self, bundle_sessions(_generated_records(seed), zone=BERLIN)
                )


DST_ANCHORS = (
    # Berlin springs forward at 01:00 UTC on 2026-03-29 (02:00 CET to 03:00 CEST).
    datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
    # Berlin falls back at 01:00 UTC on 2026-10-25 (03:00 CEST to 02:00 CET).
    datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
)
START_OFFSETS_MIN = (-61, -31, -30, -29, -1, 0, 1, 29, 30, 31, 61)
SAMPLE_PROVIDERS = (
    ProviderId.WAHOO,
    ProviderId.WAHOO,
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
# Each slot holds one Wahoo ride and two Garmin records: 5,001 total.
SCALE_SLOTS = 1667


class _AllCandidates(canonical_sessions._WallWindow):
    """Window stand-in that offers every indexed entry as a candidate."""

    def near(self, wall: datetime) -> list[int]:
        return list(self._indices)


def _quadratic_bundle_sessions(
    records: Iterable[ActivityRecord], *, zone: tzinfo
) -> tuple[ActivitySession, ...]:
    """Return sessions from the all-pairs comparison that the window search replaced.

    Every record is compared with every candidate; the assignment and the rule
    predicates are the module's own, so parity isolates the candidate search.
    """
    with mock.patch.object(canonical_sessions, "_WallWindow", _AllCandidates):
        return bundle_sessions(records, zone=zone)


def _generated_records(seed: int, count: int = 300) -> list[ActivityRecord]:
    """Return a seeded mix of Wahoo, Garmin and derived records around DST edges.

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
        self.assert_parity(_map_garmin(_load_fixture("garmin", "activities.json")))

    def test_inline_scenarios_match_the_quadratic_reference(self) -> None:
        def wahoo(name: str, minute: int) -> ActivityRecord:
            return _ride(
                name,
                provider=ProviderId.WAHOO,
                started_at=datetime(2026, 6, 1, 7, minute, tzinfo=BERLIN),
            )

        relay = _ride("g-relay", provider=ProviderId.GARMIN)
        scenarios = (
            [wahoo("w-1", 0), relay, *_map_garmin([garmin_ride()])],
            [
                wahoo("early", 0),
                wahoo("late", 20),
                *_map_garmin([garmin_ride(startTimeLocal="2026-06-01 07:10:00")]),
            ],
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
    def test_copies_compare_wall_clocks_across_the_autumn_overlap(self) -> None:
        # 02:30 CEST and 02:30 CET are one hour apart on the instant and equal on
        # the wall clock, so the second is a copy of the first.
        wahoo = _ride(
            "w-1",
            provider=ProviderId.WAHOO,
            started_at=datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        )
        garmin = _ride(
            "g-1",
            provider=ProviderId.GARMIN,
            started_at=datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
        )
        self.assertEqual(
            {frozenset({"w-1", "g-1"})}, _members(_bundle([wahoo, garmin]))
        )

    def test_copies_compare_wall_clocks_across_the_spring_gap(self) -> None:
        # 01:59 CET and 03:01 CEST are 2 minutes apart on the instant and 62
        # minutes apart on the wall clock, so they are no copies of each other.
        wahoo = _ride(
            "w-1",
            provider=ProviderId.WAHOO,
            sport=Sport.RUN,
            started_at=datetime(2026, 3, 29, 0, 59, tzinfo=UTC),
        )
        before = _ride(
            "g-before",
            provider=ProviderId.GARMIN,
            sport=Sport.RUN,
            started_at=datetime(2026, 3, 29, 1, 1, tzinfo=UTC),
        )
        near = _ride(
            "g-near",
            provider=ProviderId.GARMIN,
            sport=Sport.RUN,
            started_at=datetime(2026, 3, 29, 0, 55, tzinfo=UTC),
        )
        self.assertEqual(
            {frozenset({"w-1"}), frozenset({"g-before"})},
            _members(_bundle([wahoo, before])),
        )
        self.assertEqual(
            {frozenset({"w-1", "g-near"})}, _members(_bundle([wahoo, near]))
        )

    def test_window_at_the_datetime_limits_saturates_instead_of_overflowing(
        self,
    ) -> None:
        low = datetime.min.replace(tzinfo=UTC)
        high = datetime.max.replace(tzinfo=UTC)
        records = [
            _ride(
                "wahoo-low",
                provider=ProviderId.WAHOO,
                started_at=low + timedelta(minutes=10),
            ),
            _ride("garmin-low", provider=ProviderId.GARMIN, started_at=low),
            _ride(
                "wahoo-high",
                provider=ProviderId.WAHOO,
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
            {"wahoo-low": ["garmin-low"], "wahoo-high": ["garmin-high"]},
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
                _ride(f"wahoo-{slot}", provider=ProviderId.WAHOO, started_at=started_at)
            )
            records.append(
                _ride(
                    f"relay-{slot}", provider=ProviderId.GARMIN, started_at=started_at
                )
            )
            records.append(
                _ride(
                    f"watch-{slot}",
                    provider=ProviderId.GARMIN,
                    recorded_by=RecordingOrigin.GARMIN,
                    started_at=started_at,
                )
            )
        with mock.patch.object(
            canonical_sessions,
            "_provider_copy_cost",
            wraps=canonical_sessions._provider_copy_cost,
        ) as copy_checks:
            sessions = bundle_sessions(records, zone=BERLIN)
        self.assertEqual(5001, len(records))
        self.assertEqual(SCALE_SLOTS, len(sessions))
        self.assertTrue(all(len(session.duplicates) == 2 for session in sessions))
        # Slots are one hour apart, so each Garmin record has one Wahoo candidate
        # in its window. The all-pairs scan would make about 5.6 million comparisons.
        self.assertEqual(2 * SCALE_SLOTS, copy_checks.call_count)


if __name__ == "__main__":
    unittest.main()
