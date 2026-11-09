"""Athlete-level first threshold estimate, its adoption and its Coach visibility (#1867)."""

import json
import re
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from backend.activities.hr_cap import (
    SOURCE_ESTIMATED,
    SOURCE_MEASURED,
    SOURCES,
    cap_label,
    cap_percents,
    effective_caps,
    hr_cap,
    normalize_hr_cap,
)
from backend.athlete.profile import (
    COACH_READ_ONLY_FIELDS,
    DEFAULT_PROFILE,
    ProfileService,
)
from backend.canonical.activity_detail import ActivityDfaAlpha1, ActivityStreamSet
from backend.canonical.first_threshold import (
    FIRST_THRESHOLD_FIELD,
    FIRST_THRESHOLD_ORIGIN_FIELD,
    ORIGIN_ESTIMATED,
    ORIGIN_MEASURED,
    first_threshold_estimated,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    DfaQuality,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    StreamChannel,
    StreamResolution,
)
from backend.coach import tool_schemas
from backend.coach.context import CoachStructuredContextService
from backend.db import DatabaseManager, activity_detail_store, row_factory
from backend.db.activity_detail_store import (
    detail_sets_for,
    first_threshold_results,
    replace_detail_set,
    stored_dfa_alpha1,
)
from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.http_api.athlete_get import AthleteGetRoutes
from backend.http_api.first_threshold_post import ADOPT_PATH, FirstThresholdPostRoutes
from backend.http_api.post_dispatch import HttpPostDispatcher
from backend.performance.current_metrics import coach_thresholds
from backend.performance.first_threshold_estimate import (
    MIN_SESSIONS,
    SessionThreshold,
    estimate_view,
    first_threshold_estimate,
)
from backend.performance.first_threshold_service import FirstThresholdService
from backend.planning import run_hr_cap
from tests.test_dfa_alpha1 import ramp
from tests.test_fit_rr_mapping import fit_with_rr, streams

TODAY = date(2026, 11, 9)
GOOD, LOW = DfaQuality.GOOD, DfaQuality.LOW
STAMP = "2026-11-01T08:00:00+00:00"


def session(days_ago, bpm, quality=GOOD):
    return SessionThreshold(TODAY - timedelta(days=days_ago), bpm, quality)


def lthr_of(value):
    return lambda _day: value


class AthleteEstimateTests(unittest.TestCase):
    def test_the_median_of_three_sessions_is_percent_of_the_lthr(self) -> None:
        # 150, 153 and 156 bpm at an LTHR of 170 are 88.2, 90.0 and 91.8 percent.
        estimate = first_threshold_estimate(
            [session(5, 150), session(10, 153), session(15, 156)],
            lthr_of(170.0),
            TODAY,
        )
        assert estimate is not None
        self.assertEqual(estimate.percent_lthr, 90.0)
        self.assertEqual(estimate.sessions, 3)
        self.assertEqual(estimate.spread_pct, 3.6)
        self.assertEqual(estimate.first_day, TODAY - timedelta(days=15))
        self.assertEqual(estimate.last_day, TODAY - timedelta(days=5))
        self.assertIs(estimate.quality, LOW)  # three sessions are the minimum only

    def test_fewer_than_three_sessions_give_no_estimate(self) -> None:
        self.assertEqual(MIN_SESSIONS, 3)
        sessions = [session(5, 150), session(10, 153)]
        self.assertIsNone(first_threshold_estimate(sessions, lthr_of(170.0), TODAY))
        self.assertIsNone(first_threshold_estimate([], lthr_of(170.0), TODAY))

    def test_each_session_uses_the_lthr_in_effect_on_its_own_day(self) -> None:
        sessions = [session(5, 162), session(10, 153), session(15, 144)]
        by_day = {
            TODAY - timedelta(days=5): 180.0,
            TODAY - timedelta(days=10): 170.0,
            TODAY - timedelta(days=15): 160.0,
        }
        estimate = first_threshold_estimate(sessions, by_day.get, TODAY)
        assert estimate is not None
        # 162/180, 153/170 and 144/160 are all 90 percent although the bpm differ.
        self.assertEqual((estimate.percent_lthr, estimate.spread_pct), (90.0, 0.0))

    def test_only_the_last_60_days_count(self) -> None:
        sessions = [
            session(5, 150),
            session(10, 153),
            session(59, 156),
            session(60, 120),
        ]
        estimate = first_threshold_estimate(sessions, lthr_of(170.0), TODAY)
        assert estimate is not None
        self.assertEqual(estimate.sessions, 3)  # day 59 counts, day 60 does not
        self.assertIsNone(
            first_threshold_estimate(
                [session(5, 150), session(10, 153), session(60, 156)],
                lthr_of(170.0),
                TODAY,
            )
        )

    def test_low_quality_and_implausible_sessions_do_not_qualify(self) -> None:
        sessions = [
            session(5, 150),
            session(10, 153),
            session(15, 156, LOW),
            session(20, 400),  # 235 percent of the threshold
        ]
        self.assertIsNone(first_threshold_estimate(sessions, lthr_of(170.0), TODAY))

    def test_a_session_without_a_known_threshold_does_not_qualify(self) -> None:
        sessions = [session(5, 150), session(10, 153), session(15, 156)]
        known = {TODAY - timedelta(days=10): 170.0, TODAY - timedelta(days=15): 170.0}
        self.assertIsNone(first_threshold_estimate(sessions, known.get, TODAY))
        known[TODAY - timedelta(days=5)] = 170.0
        self.assertIsNotNone(first_threshold_estimate(sessions, known.get, TODAY))

    def test_five_agreeing_sessions_make_a_good_estimate(self) -> None:
        agreeing = [
            session(day, bpm)
            for day, bpm in ((2, 150), (6, 152), (9, 153), (12, 154), (20, 155))
        ]
        estimate = first_threshold_estimate(agreeing, lthr_of(170.0), TODAY)
        assert estimate is not None
        self.assertIs(estimate.quality, GOOD)
        wide = [*agreeing[:4], session(30, 120)]
        low = first_threshold_estimate(wide, lthr_of(170.0), TODAY)
        assert low is not None
        self.assertIs(low.quality, LOW)  # spread above five points

    def test_the_view_resolves_bpm_with_the_current_threshold_and_names_the_source(
        self,
    ) -> None:
        estimate = first_threshold_estimate(
            [session(5, 153), session(10, 153), session(15, 153)],
            lthr_of(170.0),
            TODAY,
        )
        view = estimate_view(estimate, 172.0)
        assert view is not None
        self.assertEqual(view["percent_lthr"], 90.0)
        self.assertEqual(view["bpm"], 155)  # 90 percent of 172 is 154.8
        self.assertEqual(view["quality"], "low")
        self.assertEqual(view["sessions"], 3)
        self.assertIn("kein Laborwert", view["source"])
        without_threshold = estimate_view(estimate, None)
        assert without_threshold is not None
        self.assertIsNone(without_threshold["bpm"])
        self.assertIsNone(estimate_view(None, 170.0))


class CapSourceTests(unittest.TestCase):
    def test_an_adopted_estimate_gives_the_estimated_cap_source(self) -> None:
        percents, source = cap_percents(90.0, True)
        self.assertEqual(source, SOURCE_ESTIMATED)
        self.assertEqual(percents["easy"], cap_percents(90.0)[0]["easy"])
        self.assertEqual(cap_percents(90.0)[1], SOURCE_MEASURED)
        self.assertEqual(cap_percents(None, True)[1], "default")
        self.assertEqual(effective_caps(90.0, True)["easy"]["source"], "estimated")

    def test_the_third_source_is_accepted_labelled_and_checked(self) -> None:
        self.assertEqual(SOURCES, ("default", "measured", "estimated"))
        cap = hr_cap(87.0, SOURCE_ESTIMATED)
        self.assertEqual(normalize_hr_cap(cap)["source"], "estimated")
        self.assertTrue(cap_label(cap, 170.0).endswith("geschätzt"))
        unit = {"sport": "run", "session_focus": "easy", "hr_cap": cap}
        mismatch = run_hr_cap.cap_problem(unit, 90.0)
        assert mismatch is not None
        self.assertEqual(mismatch["reason"], run_hr_cap.SOURCE_MISMATCH)
        adopted = {**unit, "hr_cap": effective_caps(90.0, True)["easy"]}
        self.assertIsNone(run_hr_cap.cap_problem(adopted, 90.0, True))
        self.assertEqual(len(run_hr_cap.problems([adopted], 90.0, False)), 1)

    def test_the_profile_origin_decides_the_estimated_flag_and_the_coach_thresholds(
        self,
    ) -> None:
        stored = {
            FIRST_THRESHOLD_FIELD: "90",
            FIRST_THRESHOLD_ORIGIN_FIELD: "estimated",
        }
        self.assertTrue(first_threshold_estimated(stored))
        measured = {**stored, FIRST_THRESHOLD_ORIGIN_FIELD: "measured"}
        self.assertFalse(first_threshold_estimated(measured))
        self.assertFalse(
            first_threshold_estimated({FIRST_THRESHOLD_ORIGIN_FIELD: "estimated"})
        )
        metrics: dict[str, dict[str, Any]] = {
            "cycling_ftp_watts": {"value": None, "source": None},
            "max_hr_bpm": {"value": 190},
            "bike_threshold_hr_bpm": {"value": 170},
            "run_threshold_hr_bpm": {"value": 170},
        }
        thresholds = coach_thresholds(metrics, 90.0, True)
        self.assertEqual(thresholds["run_hr_caps"]["easy"]["source"], "estimated")


def stream_set(activity_id, estimate=None, *, provider=ProviderId.GARMIN):
    return ActivityStreamSet(
        provider_activity_id=activity_id,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=datetime(2026, 11, 9, 8, tzinfo=UTC),
            label=None,
        ),
        origin=ActivityDetailOrigin.FETCH,
        resolution=StreamResolution.FULL,
        channels={
            StreamChannel.TIME_S: (0.0, 1.0, 2.0),
            StreamChannel.HEART_RATE_BPM: (120.0, 121.0, 122.0),
        },
        dfa_alpha1=estimate,
    )


def result(bpm, quality=GOOD, windows=40):
    return ActivityDfaAlpha1(
        estimate_bpm=bpm,
        windows=windows,
        artifact_share=0.01,
        quality=quality,
        method=1,
    )


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "first.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.counter = 0

    def add_session(self, db, activity_id, provider, record_id, day):
        db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, started_at, local_date, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                activity_id,
                provider,
                record_id,
                f"{day}T07:00:00+00:00",
                day,
                STAMP,
                STAMP,
            ),
        )

    def add_record(self, db, activity_id, provider, record_id, day, sport):
        db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
            "state, mapper_version, source_kind, recorded_by, sport, environment, "
            "started_at, local_date, load_model, fetched_at, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', 1, 'provider_reported', ?, ?, 'outdoor', ?, ?, "
            "'unknown', ?, ?, ?)",
            (
                provider,
                record_id,
                activity_id,
                provider,
                sport,
                f"{day}T07:00:00+00:00",
                day,
                STAMP,
                STAMP,
                STAMP,
            ),
        )

    def add_run(
        self, days_ago, estimate, *, sport="run", provider="garmin", session=None
    ):
        """A live session with one record and a stream set holding ``estimate``."""
        self.counter += 1
        day = (TODAY - timedelta(days=days_ago)).isoformat()
        activity_id = session or f"act_{self.counter}"
        record_id = f"r{self.counter}"
        with self.manager.unit_of_work() as db:
            if session is None:
                self.add_session(db, activity_id, provider, record_id, day)
            self.add_record(db, activity_id, provider, record_id, day, sport)
            replace_detail_set(
                db,
                stream_set(record_id, estimate, provider=ProviderId(provider)),
                mapper_version=6,
                summary_sha256=None,
                now=STAMP,
            )
        return activity_id


class StoredEstimateTests(Fixture):
    def test_the_estimate_round_trips_with_its_stream_set(self) -> None:
        self.add_run(3, result(152.5))
        with self.manager.reader() as db:
            stored = detail_sets_for(db, "garmin", "r1")
            text = db.execute("SELECT dfa_alpha1 FROM activity_detail_sets").fetchone()[
                "dfa_alpha1"
            ]
        detail = stored[0].detail
        assert isinstance(detail, ActivityStreamSet)
        self.assertEqual(detail.dfa_alpha1, result(152.5))
        self.assertEqual(
            json.loads(text),
            {
                "estimate_bpm": 152.5,
                "windows": 40,
                "artifact_share": 0.01,
                "quality": "good",
                "method": 1,
            },
        )

    def test_a_set_without_an_estimate_stores_null_and_bad_text_reads_as_none(
        self,
    ) -> None:
        self.add_run(3, None)
        with self.manager.reader() as db:
            row = db.execute("SELECT dfa_alpha1 FROM activity_detail_sets").fetchone()
        self.assertIsNone(row["dfa_alpha1"])
        for text in ("{}", '{"estimate_bpm": 5000}', '{"quality": "x"}', "[]"):
            self.assertIsNone(stored_dfa_alpha1(text), text)

    def test_reader_returns_one_estimate_per_live_run_session_in_the_range(
        self,
    ) -> None:
        self.add_run(3, result(150.0))
        shared = self.add_run(8, result(151.0, LOW, 12))
        # The better record of the same session wins.
        self.add_run(8, result(152.0, GOOD, 30), provider="wahoo", session=shared)
        self.add_run(12, result(160.0), sport="ride")
        self.add_run(70, result(140.0))
        self.add_run(20, None)
        with self.manager.reader() as db:
            rows = first_threshold_results(
                db, since=TODAY - timedelta(days=59), until=TODAY, sport=Sport.RUN
            )
        self.assertEqual(
            [(row.day, row.result.estimate_bpm) for row in rows],
            [
                (TODAY - timedelta(days=8), 152.0),
                (TODAY - timedelta(days=3), 150.0),
            ],
        )


class ServiceFixture(Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.kv = KeyValueRepository(lambda: STAMP)
        self.lthr = 170.0
        self.profile = ProfileService(
            self.manager,
            ProfileRepository(self.kv),
            self.kv,
            on_location_changed=lambda *args, **kwargs: None,
            mutation_coordinator=threading.RLock(),
            run_lthr_on=lambda _day: self.lthr,
        )
        self.service = FirstThresholdService(
            self.manager, self.profile, lambda: lambda _day: self.lthr, lambda: TODAY
        )

    def seed(self, bpms=(150.0, 153.0, 156.0, 153.0)):
        for index, bpm in enumerate(bpms):
            self.add_run(5 * (index + 1), result(bpm))

    def history(self):
        with self.manager.reader() as db:
            return [
                json.loads(row["diff"])
                for row in db.execute(
                    "SELECT diff FROM change_history WHERE entity_type = 'profile' "
                    "ORDER BY rowid"
                )
            ]


class AdoptFlowTests(ServiceFixture):
    def test_the_profile_read_shows_the_estimate_and_changes_nothing(self) -> None:
        self.seed()
        view = self.service.estimate()
        assert view is not None
        self.assertEqual(
            (view["percent_lthr"], view["bpm"], view["sessions"], view["quality"]),
            (90.0, 153, 4, "low"),
        )
        self.assertEqual(self.profile.get()[FIRST_THRESHOLD_FIELD], "")
        self.assertEqual(self.history(), [])

    def test_without_enough_sessions_there_is_nothing_to_show_or_adopt(self) -> None:
        self.seed((150.0, 153.0))
        self.assertIsNone(self.service.estimate())
        with self.assertRaises(AppError) as raised:
            self.service.adopt({"percent_lthr": 90.0})
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.profile.get()[FIRST_THRESHOLD_FIELD], "")

    def test_adopting_stores_percent_and_origin_with_a_change_receipt(self) -> None:
        self.seed()
        outcome = self.service.adopt({"percent_lthr": 90.0})
        stored = self.profile.get()
        self.assertEqual(stored[FIRST_THRESHOLD_FIELD], "90")
        self.assertEqual(stored[FIRST_THRESHOLD_ORIGIN_FIELD], ORIGIN_ESTIMATED)
        self.assertEqual(outcome["profile"][FIRST_THRESHOLD_ORIGIN_FIELD], "estimated")
        (entry,) = self.history()
        self.assertEqual(
            set(entry["fields"]),
            {FIRST_THRESHOLD_FIELD, FIRST_THRESHOLD_ORIGIN_FIELD},
        )
        self.assertEqual(
            entry["fields"][FIRST_THRESHOLD_ORIGIN_FIELD],
            {"before": "", "after": "estimated"},
        )
        self.assertTrue(first_threshold_estimated(stored))

    def test_adopting_the_value_already_stored_writes_nothing(self) -> None:
        self.seed()
        first = self.service.adopt({"percent_lthr": 90.0})
        self.assertTrue(first["adopted"])
        entries = len(self.history())
        again = self.service.adopt({"percent_lthr": 90.0})
        self.assertFalse(again["adopted"])
        self.assertEqual(again["profile"][FIRST_THRESHOLD_FIELD], "90")
        self.assertEqual(again["profile"][FIRST_THRESHOLD_ORIGIN_FIELD], "estimated")
        self.assertEqual(again["first_threshold_estimate"]["percent_lthr"], 90.0)
        self.assertEqual(len(self.history()), entries)

    def test_a_stale_or_missing_shown_value_is_refused(self) -> None:
        self.seed()
        for payload in ({"percent_lthr": 89.0}, {}, {"percent_lthr": "x"}):
            with self.subTest(payload=payload), self.assertRaises(AppError) as raised:
                self.service.adopt(payload)
            self.assertEqual(raised.exception.status, 409)
        with self.assertRaises(AppError):
            self.service.adopt([])
        self.assertEqual(self.history(), [])

    def test_a_measured_value_is_replaced_only_when_the_request_says_so(self) -> None:
        self.seed()
        self.profile.patch({FIRST_THRESHOLD_FIELD: "85"})
        self.assertEqual(
            self.profile.get()[FIRST_THRESHOLD_ORIGIN_FIELD], ORIGIN_MEASURED
        )
        with self.assertRaises(AppError) as raised:
            self.service.adopt({"percent_lthr": 90.0})
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.profile.get()[FIRST_THRESHOLD_FIELD], "85")
        self.service.adopt({"percent_lthr": 90.0, "replace_measured": True})
        self.assertEqual(self.profile.get()[FIRST_THRESHOLD_FIELD], "90")
        # An adopted estimate needs no confirmation to be adopted again.
        self.add_run(1, result(160.0))
        view = self.service.estimate()
        assert view is not None
        self.service.adopt({"percent_lthr": view["percent_lthr"]})
        stored = self.profile.get()
        self.assertEqual(stored[FIRST_THRESHOLD_ORIGIN_FIELD], ORIGIN_ESTIMATED)
        self.assertEqual(stored[FIRST_THRESHOLD_FIELD], f"{view['percent_lthr']:g}")

    def test_a_manual_entry_or_edit_resets_the_origin_to_measured(self) -> None:
        self.seed()
        self.service.adopt({"percent_lthr": 90.0})
        self.profile.patch({"first_threshold_hr": "144"})  # 144 / 170 = 84.7 percent
        stored = self.profile.get()
        self.assertEqual(stored[FIRST_THRESHOLD_FIELD], "84.7")
        self.assertEqual(stored[FIRST_THRESHOLD_ORIGIN_FIELD], ORIGIN_MEASURED)
        self.service.adopt({"percent_lthr": 90.0, "replace_measured": True})
        self.profile.patch({FIRST_THRESHOLD_FIELD: "88"})
        self.assertEqual(
            self.profile.get()[FIRST_THRESHOLD_ORIGIN_FIELD], ORIGIN_MEASURED
        )
        self.service.adopt({"percent_lthr": 90.0, "replace_measured": True})
        self.profile.patch({"name": "Ada"})  # other edits keep the origin
        self.assertEqual(
            self.profile.get()[FIRST_THRESHOLD_ORIGIN_FIELD], ORIGIN_ESTIMATED
        )
        self.profile.patch({FIRST_THRESHOLD_FIELD: ""})
        self.assertEqual(self.profile.get()[FIRST_THRESHOLD_ORIGIN_FIELD], "")

    def test_a_full_replacement_without_the_origin_keeps_it(self) -> None:
        self.seed()
        self.service.adopt({"percent_lthr": 90.0})
        replacement = {
            key: value
            for key, value in self.profile.get().items()
            if key != FIRST_THRESHOLD_ORIGIN_FIELD
        }
        self.profile.save({**replacement, "name": "Ada"})
        stored = self.profile.get()
        self.assertEqual(stored["name"], "Ada")
        self.assertEqual(stored[FIRST_THRESHOLD_ORIGIN_FIELD], ORIGIN_ESTIMATED)

    def test_a_profile_stored_before_the_origin_existed_reads_as_measured(self) -> None:
        with self.manager.unit_of_work() as db:
            self.kv.set(db, "profile", json.dumps({FIRST_THRESHOLD_FIELD: "88"}))
        stored = self.profile.get()
        self.assertEqual(stored[FIRST_THRESHOLD_ORIGIN_FIELD], ORIGIN_MEASURED)
        self.assertFalse(first_threshold_estimated(stored))


class ProfileReadTests(unittest.TestCase):
    def read(self, service):
        handler = Mock()
        profile = Mock()
        profile.get.return_value = {"name": "Test Athlete"}
        competitions = Mock()
        competitions.list.return_value = []
        routes = AthleteGetRoutes(
            lambda: Mock(),
            lambda: Mock(),
            lambda: profile,
            lambda: competitions,
            lambda: Mock(),
            lambda: Mock(),
            Mock(),
            first_threshold_service=service,
        )
        self.assertTrue(routes.handle(handler, "/api/profile"))
        return handler.send_json.call_args.args[1]

    def test_the_profile_read_carries_the_estimate_or_null(self) -> None:
        estimate = {"percent_lthr": 90.0, "sessions": 4, "quality": "low"}
        service = Mock()
        service.estimate.return_value = estimate
        self.assertEqual(
            self.read(lambda: service)["first_threshold_estimate"], estimate
        )
        service.estimate.return_value = None
        self.assertIsNone(self.read(lambda: service)["first_threshold_estimate"])

    def test_a_failing_estimate_never_fails_the_profile_read(self) -> None:
        service = Mock()
        service.estimate.side_effect = RuntimeError("synthetic failure")
        payload = self.read(lambda: service)
        self.assertIsNone(payload["first_threshold_estimate"])
        self.assertEqual(payload["profile"], {"name": "Test Athlete"})


class RouteTests(unittest.TestCase):
    def test_the_route_adopts_through_the_service_under_the_profile_lock(self) -> None:
        service = Mock()
        service.adopt.return_value = {"profile": {}, "first_threshold_estimate": None}
        profile = Mock(mutation_coordinator=threading.RLock())
        routes = FirstThresholdPostRoutes(lambda: service, lambda: profile)
        handler = Mock()
        handler.read_json.return_value = {"percent_lthr": 90.0}
        self.assertTrue(routes.handle(handler, ADOPT_PATH))
        service.adopt.assert_called_once_with({"percent_lthr": 90.0})
        handler.send_json.assert_called_once_with(
            200, {"profile": {}, "first_threshold_estimate": None}
        )
        self.assertFalse(routes.handle(handler, "/api/profile"))

    def test_the_route_is_part_of_the_authenticated_post_dispatch(self) -> None:
        routes = Mock()
        for name in (
            "coach_actions",
            "chat",
            "transcribe",
            "planning_commands",
            "feedback",
            "history_undo",
            "privacy_delete",
            "diagnostics_delete",
            "nutrition",
            "sync_commands",
        ):
            getattr(routes, name).handle.return_value = False
        for name in (
            "analysis",
            "equipment",
            "wahoo",
            "metric_export",
            "garmin",
            "provider_connections",
            "planned_unit_focus",
        ):
            setattr(routes, name, None)
        routes.first_threshold = Mock()
        routes.first_threshold.handle.return_value = True
        dispatcher = HttpPostDispatcher(Mock(), Mock(), Mock(), routes)
        handler = Mock()
        dispatcher.handle_authenticated(handler, ADOPT_PATH, {})
        routes.first_threshold.handle.assert_called_once_with(handler, ADOPT_PATH)


class CoachVisibilityTests(unittest.TestCase):
    def test_the_coach_sees_the_estimate_with_quality_count_and_source(self) -> None:
        estimate = {
            "percent_lthr": 90.0,
            "bpm": 153,
            "sessions": 4,
            "quality": "low",
            "from": "2026-10-10",
            "to": "2026-11-04",
            "spread_pct": 3.6,
            "source": "Schätzung aus Brustgurt-RR-Intervallen (DFA-α1), kein Laborwert",
        }
        performance = Mock()
        performance.current_performance.return_value = {"ftp": 260}

        def current(read):
            return CoachStructuredContextService(
                Mock(),
                Mock(),
                Mock(),
                Mock(),
                performance,
                first_threshold_estimate=read,
            )._current_performance(None)

        seen = current(lambda: estimate)["first_threshold_estimate"]
        self.assertEqual(seen, estimate)
        self.assertLessEqual({"quality", "sessions", "source"}, set(seen))
        self.assertNotIn("first_threshold_estimate", current(lambda: None))

        def failing():
            raise RuntimeError("synthetic failure")

        self.assertNotIn("first_threshold_estimate", current(failing))

    def test_no_coach_tool_writes_the_first_threshold_or_adopts_the_estimate(
        self,
    ) -> None:
        self.assertLessEqual(
            {FIRST_THRESHOLD_FIELD, FIRST_THRESHOLD_ORIGIN_FIELD},
            COACH_READ_ONLY_FIELDS,
        )
        serialized = json.dumps(
            tool_schemas.build_structured_tool_schemas(
                default_profile=DEFAULT_PROFILE,
                checkin_text_limits={},
                checkin_score_fields=(),
                training_change_limit=5,
                library_bulk_max_entries=5,
                training_plan_statuses=("active",),
            ),
            default=str,
        )
        for name in (
            FIRST_THRESHOLD_FIELD,
            FIRST_THRESHOLD_ORIGIN_FIELD,
            "first_threshold_hr",
            "adopt",
        ):
            self.assertNotIn(f'"{name}"', serialized, name)
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in Path(tool_schemas.__file__).parent.glob("*.py")
        )
        for forbidden in (
            "set_first_threshold",
            "FirstThresholdService",
            "first_threshold.adopt",
            "ORIGIN_ESTIMATED",
        ):
            self.assertNotIn(forbidden, sources, forbidden)


class RrNeverLeavesTheMapperTests(Fixture):
    def test_the_rr_series_is_in_no_stored_set_export_or_coach_view(self) -> None:
        marker = 1234.0  # an interval no ramp beat has; found only if it leaked
        series = ramp(0)
        series[40] = marker
        detail = streams(fit_with_rr(series))
        found = detail.dfa_alpha1
        assert found is not None
        with self.manager.unit_of_work() as db:
            self.add_session(db, "act_1", "garmin", "a1", "2026-11-01")
            self.add_record(db, "act_1", "garmin", "a1", "2026-11-01", "run")
            replace_detail_set(
                db, detail, mapper_version=6, summary_sha256=None, now=STAMP
            )
        with self.manager.reader() as db:
            rows = [
                dict(row) for row in db.execute("SELECT * FROM activity_detail_sets")
            ]
            channels = [
                row["channel"]
                for row in db.execute("SELECT channel FROM activity_stream_channels")
            ]
            export = [dict(row) for row in activity_detail_store.stream_export_rows(db)]
        self.assertEqual(
            set(json.loads(rows[0]["dfa_alpha1"])),
            {"estimate_bpm", "windows", "artifact_share", "quality", "method"},
        )
        self.assertEqual(sorted(channels), ["heart_rate_bpm", "time_s"])
        view = estimate_view(
            first_threshold_estimate(
                [SessionThreshold(date(2026, 11, 1), found.estimate_bpm, GOOD)] * 3,
                lthr_of(170.0),
                TODAY,
            ),
            170.0,
        )
        for text in (
            repr(detail),
            json.dumps(rows, default=str),
            json.dumps(export, default=str),
            json.dumps(view, default=str),
        ):
            self.assertIsNone(re.search(r"\b1234(\.0)?\b", text), text[:80])


if __name__ == "__main__":
    unittest.main()
