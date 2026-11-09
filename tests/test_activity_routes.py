"""Route recognition on synthetic tracks: grouping, ordinals, names, caching, privacy."""

from __future__ import annotations

import json
import math
import random
import tempfile
import unittest
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest import mock
from unittest.mock import Mock, patch

from canonical_detail_support import add_session_record, open_manager

from backend.activities import route_store, routes
from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db import activity_detail_store
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.http_api.activity_route_post import ActivityRoutePostRoutes
from backend.privacy import GPS_TRACKS_DELETE_CONFIRMATION_TEXT, PrivacyDeleteService
from backend.sync.activity_routes import (
    ActivityRoutesStage,
    summarize_activity_routes,
)

START = (52.52012, 13.40534)
LOOP_M = 2 * math.pi * 800


def loop(
    start: tuple[float, float] = START,
    *,
    radius: float = 800.0,
    seed: int = 0,
    jitter: float = 8.0,
    centre_east: bool = False,
    step: float = 30.0,
) -> tuple[list[float], list[float]]:
    """A circular track from ``start`` with Gaussian GPS jitter in metres.

    The circle's centre lies west of the start, or east of it with
    ``centre_east``: two such loops touch only at the start.
    """
    rng = random.Random(seed)
    count = int(2 * math.pi * radius / step)
    latitudes: list[float] = []
    longitudes: list[float] = []
    for index in range(count + 1):
        angle = 2 * math.pi * index / count
        east = (
            radius * (1 - math.cos(angle))
            if centre_east
            else radius * (math.cos(angle) - 1)
        )
        north = radius * math.sin(angle)
        east += rng.gauss(0, jitter)
        north += rng.gauss(0, jitter)
        latitude = start[0] + north / 111_320
        longitudes.append(
            start[1] + east / (111_320 * math.cos(math.radians(latitude)))
        )
        latitudes.append(latitude)
    return latitudes, longitudes


def reverse(track: tuple[list[float], list[float]]) -> tuple[list[float], list[float]]:
    return track[0][::-1], track[1][::-1]


def make(track: tuple[list[float], list[float]], distance: float = LOOP_M) -> Any:
    found = routes.fingerprint(*track, distance)
    assert found is not None
    return found


class CellTests(unittest.TestCase):
    def test_a_few_metres_stay_in_one_cell_and_500_m_do_not(self) -> None:
        for latitude in (0.3, 52.5201, 64.1):
            with self.subTest(latitude=latitude):
                near = routes.cell_of(latitude + 0.00001, 13.40501)
                self.assertEqual(near, routes.cell_of(latitude + 0.00001, 13.40501))
                moved = routes.cell_of(latitude + 600 / 111_320, 13.40501)
                self.assertNotEqual(near[0], moved[0])

    def test_a_cell_is_about_500_m_wide_at_any_latitude(self) -> None:
        for latitude in (0.3, 52.5, 64.1):
            with self.subTest(latitude=latitude):
                metres = 111_320 * math.cos(math.radians(latitude))
                cells = {
                    routes.cell_of(latitude, 13.4 + east / metres)
                    for east in range(0, 5000, 10)
                }
                # 5 km east cross 10 cells of 500 m, plus one at a border.
                self.assertIn(len(cells), (10, 11))

    def test_invalid_fixes_are_skipped(self) -> None:
        clean = loop(seed=1)
        noisy_lat = [None, 0.0, math.nan, 95.0, *clean[0]]
        noisy_lon = [None, 0.0, 13.4, 13.4, *clean[1]]
        self.assertEqual(
            routes.fingerprint(*clean, LOOP_M),
            routes.fingerprint(noisy_lat, noisy_lon, LOOP_M),
        )


class FingerprintTests(unittest.TestCase):
    def test_the_same_loop_with_gps_jitter_is_one_route(self) -> None:
        reference = make(loop(seed=1))
        for seed in range(2, 12):
            with self.subTest(seed=seed):
                self.assertTrue(
                    routes.same_route(reference, make(loop(seed=seed))),
                )

    def test_a_reversed_loop_is_the_same_route(self) -> None:
        self.assertTrue(
            routes.same_route(make(loop(seed=1)), make(reverse(loop(seed=2))))
        )

    def test_another_loop_from_the_same_start_and_length_is_not(self) -> None:
        mine, other = make(loop(seed=1)), make(loop(seed=2, centre_east=True))
        self.assertEqual(mine.start, other.start)
        self.assertLess(routes.overlap(mine, other), 0.3)
        self.assertFalse(routes.same_route(mine, other))

    def test_a_distance_more_than_10_percent_apart_is_not(self) -> None:
        track = loop(seed=1)
        self.assertTrue(
            routes.same_route(make(track, 5000.0), make(track, 5450.0)),
        )
        self.assertFalse(
            routes.same_route(make(track, 5000.0), make(track, 5600.0)),
        )
        # A bigger circle from the same start is not the route either.
        self.assertFalse(
            routes.same_route(
                make(loop(seed=1)), make(loop(radius=1000.0, seed=2), 6283.0)
            )
        )

    def test_a_distant_start_is_not_the_same_route(self) -> None:
        shifted = make(loop((52.52, 13.45), seed=1))
        self.assertFalse(routes.same_route(make(loop(seed=1)), shifted))

    def test_short_or_stationary_tracks_have_no_fingerprint(self) -> None:
        self.assertIsNone(routes.fingerprint(*loop(radius=300.0), None))
        still = ([START[0]] * 200, [START[1]] * 200)
        self.assertIsNone(routes.fingerprint(*still, 10_000.0))
        self.assertIsNone(routes.fingerprint([], [], 10_000.0))

    def test_without_a_given_distance_the_track_length_is_used(self) -> None:
        found = routes.fingerprint(*loop(seed=1))
        assert found is not None
        # A 800 m circle: 5027 m, chords on a 150 m grid stay within 5 %.
        self.assertAlmostEqual(LOOP_M, found.distance_m, delta=0.05 * LOOP_M)

    def test_a_signal_gap_is_no_distance(self) -> None:
        latitudes, longitudes = loop(seed=1)
        gapped = (
            [*latitudes[:100], 53.5, *latitudes[100:]],
            [*longitudes[:100], 14.5, *longitudes[100:]],
        )
        plain = routes.fingerprint(latitudes, longitudes)
        jumped = routes.fingerprint(*gapped)
        assert plain is not None and jumped is not None
        self.assertAlmostEqual(plain.distance_m, jumped.distance_m, delta=400.0)

    def test_stored_references_round_trip_and_reject_malformed_ones(self) -> None:
        found = make(loop(seed=1), 5026.5)
        self.assertEqual(
            found, routes.decode(json.loads(json.dumps(routes.encode(found))))
        )
        for bad in (None, {}, {"c": 5, "s": [1, 2], "e": [1, 2], "d": 1}, "x"):
            self.assertIsNone(routes.decode(bad))


class IndexTests(unittest.TestCase):
    def index_of(self, *tracks: Any) -> dict[str, Any]:
        index = routes.empty_index()
        for number, track in enumerate(tracks, start=1):
            index["sessions"][f"s{number}"] = {
                "h": "x",
                "at": f"2026-09-{number:02d}T05:00:00+00:00",
                "route": None,
            }
            routes.place(index, f"s{number}", track)
        return index

    def test_repeats_share_a_route_and_other_loops_get_their_own(self) -> None:
        index = self.index_of(
            make(loop(seed=1)),
            make(loop(seed=2, centre_east=True)),
            make(loop(seed=3)),
            None,
        )
        sessions = index["sessions"]
        self.assertEqual("r1", sessions["s1"]["route"])
        self.assertEqual("r2", sessions["s2"]["route"])
        self.assertEqual("r1", sessions["s3"]["route"])
        self.assertIsNone(sessions["s4"]["route"])
        self.assertEqual({"r1", "r2"}, set(index["routes"]))

    def test_the_block_counts_repeats_by_start_and_names_by_default(self) -> None:
        index = self.index_of(*[make(loop(seed=n)) for n in range(1, 6)])
        block = routes.route_block(index, "s5")
        self.assertEqual(
            {
                "label": "Strecke 1",
                "repeat_index": 5,
                "repeat_count": 5,
                "route_id": "r1",
            },
            block,
        )
        second = routes.route_block(index, "s2")
        assert second is not None
        self.assertEqual(2, second["repeat_index"])
        self.assertIsNone(routes.route_block(index, "unknown"))
        index["routes"]["r1"]["name"] = "Hausrunde"
        named = routes.route_block(index, "s3")
        assert named is not None
        self.assertEqual("Hausrunde", named["label"])

    def test_a_session_keeps_its_route_while_it_still_matches(self) -> None:
        index = self.index_of(make(loop(seed=1)))
        index["routes"]["r1"]["name"] = "Hausrunde"
        routes.place(index, "s1", make(loop(seed=7)))
        self.assertEqual("r1", index["sessions"]["s1"]["route"])
        self.assertEqual("Hausrunde", index["routes"]["r1"]["name"])

    def test_prune_forgets_gone_sessions_and_empty_routes(self) -> None:
        index = self.index_of(make(loop(seed=1)), make(loop(seed=2, centre_east=True)))
        routes.prune(index, ["s1"])
        self.assertEqual(["s1"], list(index["sessions"]))
        self.assertEqual(["r1"], list(index["routes"]))

    def test_names_are_trimmed_plain_text_of_one_to_sixty_characters(self) -> None:
        self.assertEqual("Hausrunde", routes.clean_name("  Hausrunde \t"))
        self.assertEqual("a" * 60, routes.clean_name("a" * 60))
        for bad in ("", "   ", "a" * 61, "zwei\nzeilen", "tab\tx", "x\x00", None, 5):
            with self.subTest(bad=bad):
                self.assertIsNone(routes.clean_name(bad))


GARMIN = ProviderId.GARMIN
FIRST_DAY = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)


def store_track(
    manager: Any,
    provider_activity_id: str,
    track: tuple[list[float], list[float]],
    provider: ProviderId = GARMIN,
) -> None:
    count = len(track[0])
    with manager.unit_of_work() as db:
        activity_detail_store.replace_detail_set(
            db,
            ActivityStreamSet(
                provider_activity_id=provider_activity_id,
                provenance=Provenance(
                    provider=provider,
                    source_kind=SourceKind.PROVIDER_REPORTED,
                    source_record_id=None,
                    recorded_by=RecordingOrigin.GARMIN,
                    retrieved_at=FIRST_DAY,
                    label="Garmin Connect",
                ),
                origin=ActivityDetailOrigin.FETCH,
                resolution=StreamResolution.FULL,
                channels={
                    StreamChannel.TIME_S: tuple(3.0 * i for i in range(count)),
                    StreamChannel.HEART_RATE_BPM: (130.0,) * count,
                    StreamChannel.LATITUDE_DEG: tuple(track[0]),
                    StreamChannel.LONGITUDE_DEG: tuple(track[1]),
                },
            ),
            mapper_version=1,
            summary_sha256=None,
            now=FIRST_DAY.isoformat(),
        )


def add_outdoor_session(
    manager: Any,
    number: int,
    track: tuple[list[float], list[float]] | None,
    *,
    day: int | None = None,
    distance: float = LOOP_M,
    sport: str = "run",
    environment: str = "outdoor",
) -> str:
    """One Garmin session on day ``day`` (default: its number) of September."""
    started = (FIRST_DAY + timedelta(days=(day or number) - 1)).isoformat()
    activity_id, provider_id = f"act_g{number}", f"g{number}"
    add_session_record(
        manager,
        GARMIN,
        provider_id,
        activity_id,
        sport=sport,
        moving_duration_s=3600.0,
        distance_m=distance,
    )
    with manager.unit_of_work() as db:
        db.execute(
            "UPDATE activity_records SET started_at = ?, environment = ? "
            "WHERE provider_activity_id = ?",
            (started, environment, provider_id),
        )
        db.execute(
            "UPDATE activity_sessions SET started_at = ? WHERE activity_id = ?",
            (started, activity_id),
        )
    if track is not None:
        store_track(manager, provider_id, track)
    return activity_id


class StageCase(unittest.TestCase):
    batch_size = 50

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.key_values = KeyValueRepository(lambda: FIRST_DAY.isoformat())
        self.stage = ActivityRoutesStage(
            key_values=self.key_values,
            zone_provider=lambda: UTC,
            batch_size=self.batch_size,
        )
        self.service = route_store.ActivityRouteService(
            lambda: self.manager, nullcontext(), self.key_values
        )

    def run_stage(self) -> Any:
        with self.manager.unit_of_work() as db:
            return self.stage.run_batch(db)

    def _index(self) -> dict[str, Any]:
        with self.manager.reader() as db:
            return route_store.load_index(db)

    def _block(self, session_id: str) -> dict[str, Any] | None:
        with self.manager.reader() as db:
            return route_store.stored_route_block(db, session_id)


class StageTests(StageCase):
    def test_repeats_get_ordinals_and_other_loops_their_own_route(self) -> None:
        for number in range(1, 6):
            add_outdoor_session(self.manager, number, loop(seed=number))
        add_outdoor_session(
            self.manager, 6, loop(seed=6, centre_east=True), sport="ride"
        )
        add_outdoor_session(self.manager, 7, reverse(loop(seed=7)))
        report = self.run_stage()
        self.assertTrue(report.done)
        self.assertEqual(7, report.items)
        ordinals = {
            number: (block["repeat_index"], block["repeat_count"])
            for number in (1, 2, 3, 4, 5, 7)
            if (block := self._block(f"act_g{number}")) is not None
        }
        # The reversed loop of the seventh day is the sixth visit of the route.
        self.assertEqual(
            {1: (1, 6), 2: (2, 6), 3: (3, 6), 4: (4, 6), 5: (5, 6), 7: (6, 6)},
            ordinals,
        )
        last = self._block("act_g7")
        assert last is not None
        self.assertEqual(
            {"label": "Strecke 1", "repeat_index": 6, "repeat_count": 6},
            {k: v for k, v in last.items() if k != "route_id"},
        )
        other = self._block("act_g6")
        assert other is not None
        self.assertEqual("Strecke 2", other["label"])
        self.assertEqual((1, 1), (other["repeat_index"], other["repeat_count"]))

    def test_the_ordinal_follows_the_start_time_not_the_arrival(self) -> None:
        add_outdoor_session(self.manager, 1, loop(seed=1), day=20)
        add_outdoor_session(self.manager, 2, loop(seed=2), day=10)
        self.run_stage()
        self.assertEqual(2, (self._block("act_g1") or {})["repeat_index"])
        self.assertEqual(1, (self._block("act_g2") or {})["repeat_index"])

    def test_short_indoor_and_positionless_sessions_have_no_route(self) -> None:
        add_outdoor_session(self.manager, 1, loop(radius=300.0), distance=1885.0)
        add_outdoor_session(self.manager, 2, loop(seed=2), environment="indoor")
        add_outdoor_session(self.manager, 3, None)
        add_outdoor_session(self.manager, 4, loop(seed=4), sport="swim")
        self.run_stage()
        for number in (1, 2, 3, 4):
            self.assertIsNone(self._block(f"act_g{number}"))
        self.assertEqual({}, self._index()["routes"])

    def test_a_second_run_decodes_and_writes_nothing(self) -> None:
        add_outdoor_session(self.manager, 1, loop(seed=1))
        add_outdoor_session(self.manager, 2, loop(seed=2))
        self.run_stage()
        stored = self._index()
        with patch.object(
            activity_detail_store,
            "full_stream_sets_for_session",
            wraps=activity_detail_store.full_stream_sets_for_session,
        ) as decode:
            second = self.run_stage()
        decode.assert_not_called()
        self.assertEqual(0, second.items)
        self.assertTrue(second.done)
        self.assertEqual(stored, self._index())
        # A new session decodes only itself.
        add_outdoor_session(self.manager, 3, loop(seed=3))
        with patch.object(
            activity_detail_store,
            "full_stream_sets_for_session",
            wraps=activity_detail_store.full_stream_sets_for_session,
        ) as decode:
            third = self.run_stage()
        self.assertEqual(1, third.items)
        self.assertEqual(1, decode.call_count)
        self.assertEqual(3, (self._block("act_g3") or {})["repeat_count"])

    def test_batches_resume_until_every_session_is_placed(self) -> None:
        stage = ActivityRoutesStage(
            key_values=self.key_values, zone_provider=lambda: UTC, batch_size=2
        )
        for number in range(1, 6):
            add_outdoor_session(self.manager, number, loop(seed=number))
        done = []
        for _ in range(3):
            with self.manager.unit_of_work() as db:
                done.append(stage.run_batch(db).done)
        self.assertEqual([False, False, True], done)
        self.assertEqual(5, (self._block("act_g5") or {})["repeat_count"])

    def test_a_deleted_session_leaves_its_route_and_the_count(self) -> None:
        for number in range(1, 4):
            add_outdoor_session(self.manager, number, loop(seed=number))
        self.run_stage()
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted' WHERE activity_id = ?",
                ("act_g2",),
            )
        self.run_stage()
        self.assertIsNone(self._block("act_g2"))
        self.assertEqual(2, (self._block("act_g3") or {})["repeat_index"])
        self.assertEqual(2, (self._block("act_g3") or {})["repeat_count"])
        for number in (1, 3):
            with self.manager.unit_of_work() as db:
                db.execute(
                    "UPDATE activity_sessions SET state = 'deleted' WHERE activity_id = ?",
                    (f"act_g{number}",),
                )
        self.run_stage()
        self.assertEqual({}, self._index()["routes"])

    def test_a_rename_survives_new_sessions_and_a_changed_stream(self) -> None:
        add_outdoor_session(self.manager, 1, loop(seed=1))
        self.run_stage()
        route_id = (self._block("act_g1") or {})["route_id"]
        self.service.rename(route_id, "Hausrunde")
        add_outdoor_session(self.manager, 2, loop(seed=2))
        # The provider delivers the first track again, slightly different.
        store_track(self.manager, "g1", loop(seed=9, jitter=12.0))
        report = self.run_stage()
        self.assertEqual(2, report.items)
        for number in (1, 2):
            block = self._block(f"act_g{number}") or {}
            self.assertEqual(
                ("Hausrunde", route_id, number),
                (block["label"], block["route_id"], block["repeat_index"]),
            )

    def test_a_track_that_changes_route_leaves_the_old_one(self) -> None:
        add_outdoor_session(self.manager, 1, loop(seed=1))
        add_outdoor_session(self.manager, 2, loop(seed=2))
        self.run_stage()
        store_track(self.manager, "g2", loop(seed=3, centre_east=True))
        self.run_stage()
        self.assertEqual(1, (self._block("act_g1") or {})["repeat_count"])
        self.assertNotEqual(
            (self._block("act_g1") or {})["route_id"],
            (self._block("act_g2") or {})["route_id"],
        )

    def test_deleted_tracks_remove_their_routes_and_names(self) -> None:
        add_outdoor_session(self.manager, 1, loop(seed=1))
        self.run_stage()
        self.service.rename((self._block("act_g1") or {})["route_id"], "Hausrunde")
        with self.manager.unit_of_work() as db:
            activity_detail_store.delete_stored_tracks(db)
        self.run_stage()
        self.assertIsNone(self._block("act_g1"))
        self.assertEqual({}, self._index()["routes"])
        # Rebuilt neither now nor later without tracks.
        self.run_stage()
        self.assertEqual({}, self._index()["routes"])

    def test_with_the_setting_off_stored_routes_stay(self) -> None:
        add_outdoor_session(self.manager, 1, loop(seed=1))
        self.run_stage()
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, activity_detail_store.GPS_TRACKS_KEY, "0")
        self.run_stage()
        self.assertIsNotNone(self._block("act_g1"))

    def test_a_failing_batch_is_marked_failed(self) -> None:
        with self.manager.unit_of_work() as db:
            self.stage.mark_failed(db)
        with self.manager.reader() as db:
            self.assertEqual("failed", self.stage.summary(db)["status"])


class PrivacyDeleteTests(StageCase):
    def privacy(self) -> PrivacyDeleteService:
        return PrivacyDeleteService(
            SimpleNamespace(
                database_manager=self.manager,
                database_lock=nullcontext(),
                maintenance_gate=SimpleNamespace(restore=lambda: nullcontext()),
                key_value_repository=self.key_values,
            )  # type: ignore[arg-type]
        )

    def seed(self) -> str:
        add_outdoor_session(self.manager, 1, loop(seed=1))
        self.run_stage()
        route_id = (self._block("act_g1") or {})["route_id"]
        self.service.rename(route_id, "Hausrunde")
        return str(route_id)

    def test_deleting_the_tracks_deletes_the_routes_in_the_same_request(self) -> None:
        self.seed()
        result = self.privacy().delete_gps_tracks(GPS_TRACKS_DELETE_CONFIRMATION_TEXT)
        self.assertEqual(1, result["deleted_tracks"])
        self.assertIsNone(self._block("act_g1"))
        with self.manager.reader() as db:
            self.assertIsNone(self.key_values.get(db, route_store.INDEX_KEY))

    def test_a_refused_confirmation_keeps_the_routes(self) -> None:
        self.seed()
        with self.assertRaises(AppError):
            self.privacy().delete_gps_tracks("ja")
        self.assertEqual("Hausrunde", (self._block("act_g1") or {})["label"])

    def test_turning_the_setting_off_keeps_the_routes(self) -> None:
        self.seed()
        self.privacy().set_gps_tracks(True)
        self.assertIsNotNone(self._block("act_g1"))
        self.privacy().set_gps_tracks(False)
        self.assertIsNotNone(self._block("act_g1"))


class HardeningTests(StageCase):
    def test_a_failing_batch_is_isolated_and_marked_failed(self) -> None:
        with mock.patch.object(self.stage, "_wanted", side_effect=RuntimeError("x")):
            report = self.run_stage()
        self.assertTrue(report.done)
        with self.manager.reader() as db:
            self.assertEqual(
                "failed", summarize_activity_routes(self.key_values, db)["status"]
            )

    def test_malformed_entries_and_a_nan_distance_do_not_fail_the_stage(self) -> None:
        add_outdoor_session(self.manager, 1, loop(seed=1))
        with self.manager.unit_of_work() as db:
            self.key_values.set(
                db,
                route_store.INDEX_KEY,
                json.dumps({"routes": {"r1": 5}, "sessions": {"x": "y"}, "next": 2}),
            )
        report = self.run_stage()
        self.assertTrue(report.done)
        self.assertIsNotNone(self._block("act_g1"))


class RenameTests(StageCase):
    def setUp(self) -> None:
        super().setUp()
        add_outdoor_session(self.manager, 1, loop(seed=1))
        self.run_stage()
        self.route_id = (self._block("act_g1") or {})["route_id"]

    def test_rename_stores_the_trimmed_name_and_answers_label_only(self) -> None:
        result = self.service.rename(self.route_id, "  Hausrunde ")
        self.assertEqual(
            {"status": "ok", "route_id": self.route_id, "label": "Hausrunde"}, result
        )
        self.assertEqual("Hausrunde", (self._block("act_g1") or {})["label"])

    def test_invalid_names_are_refused_and_change_nothing(self) -> None:
        for bad in ("", "  ", "a" * 61, "a\nb", "a\x07", None, 4, ["x"]):
            with self.subTest(name=bad):
                with self.assertRaises(AppError) as raised:
                    self.service.rename(self.route_id, bad)
                self.assertEqual(400, raised.exception.status)
        self.assertEqual("Strecke 1", (self._block("act_g1") or {})["label"])

    def test_an_unknown_route_is_not_found(self) -> None:
        for unknown in ("r99", "", None, 7, ["r1"]):
            with self.subTest(route=unknown):
                with self.assertRaises(AppError) as raised:
                    self.service.rename(unknown, "Name")
                self.assertEqual(404, raised.exception.status)

    def test_the_post_route_passes_the_payload_and_ignores_other_paths(self) -> None:
        service = Mock()
        service.rename.return_value = {"status": "ok"}
        post = ActivityRoutePostRoutes(lambda: service)
        handler = SimpleNamespace(
            read_json=Mock(return_value={"route_id": "r1", "name": "A", "x": 1}),
            send_json=Mock(),
        )
        self.assertTrue(post.handle(handler, "/api/routes/rename"))
        service.rename.assert_called_once_with("r1", "A")
        handler.send_json.assert_called_once_with(200, {"status": "ok"})
        other = SimpleNamespace(read_json=Mock(), send_json=Mock())
        self.assertFalse(post.handle(other, "/api/other"))
        other.read_json.assert_not_called()
        with self.assertRaises(AppError):
            post.handle(
                SimpleNamespace(read_json=Mock(return_value=[]), send_json=Mock()),
                "/api/routes/rename",
            )


class PrivacySweepTests(StageCase):
    """Distinctive coordinates and the cells derived from them never leave the index."""

    def test_no_position_cell_or_fingerprint_reaches_a_read_model(self) -> None:
        start = (51.98765, 7.65432)
        for number in range(1, 4):
            add_outdoor_session(
                self.manager, number, loop(start, seed=number, jitter=3.0)
            )
        with self.assertLogs("intervals_coach", level="DEBUG") as logs:
            self.run_stage()
        block = self._block("act_g2")
        assert block is not None
        self.assertEqual(
            {"label", "repeat_index", "repeat_count", "route_id"}, set(block)
        )
        renamed = self.service.rename(block["route_id"], "Hausrunde")
        index = self._index()
        reference = routes.decode(index["routes"][block["route_id"]]["ref"])
        assert reference is not None
        with self.manager.reader() as db:
            diagnostics = summarize_activity_routes(self.key_values, db)
        texts = [
            json.dumps(item, sort_keys=True) for item in (block, renamed, diagnostics)
        ]
        texts.append("\n".join(logs.output))
        texts.extend(repr(getattr(record, "context", "")) for record in logs.records)
        forbidden = [
            "51.98",
            "7.65",
            str(reference.start[0]),
            str(reference.start[1]),
            json.dumps(routes.encode(reference)["c"], separators=(",", ":"))[:20],
            '"ref"',
            '"cells"',
        ]
        for text in texts:
            for needle in forbidden:
                self.assertNotIn(needle, text)
        # The index itself is private, but holds no raw coordinate either.
        self.assertNotIn("51.98", json.dumps(index))
        self.assertNotIn("7.65", json.dumps(index))
        with self.manager.reader() as db:
            state = self.key_values.get(db, route_store.STATE_KEY) or ""
        self.assertNotIn("act_g", state)


if __name__ == "__main__":
    unittest.main()
