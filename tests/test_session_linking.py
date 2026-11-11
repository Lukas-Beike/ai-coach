"""Persisted session bundling through the real canonical ingest path.

Each test uses a temporary SQLite file through the real DatabaseManager and the
canonical schema, with synthetic provider rows. No provider account, network,
real data directory or encryption key is involved.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import intervals_compaction as intervals_fixture

from backend.activities.activity_reference import ActivityReferences
from backend.activities.session_linking import link_activity_sessions
from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager, canonical_store, row_factory
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import (
    ACTIVITY_RECORD_KIND,
    ActivityItem,
    IngestPlan,
    wahoo_ingest_plan,
)
from backend.providers.wahoo_activity_mapping import MAPPER_VERSION as WAHOO_VERSION
from backend.providers.wahoo_activity_mapping import map_wahoo_activities
from backend.sync import canonical_ingest as ingest

ZONE = ZoneInfo("Europe/Berlin")
FIRST = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
SECOND = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
THIRD = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 11, 11, 0, tzinfo=UTC)
EARLIEST = date(2026, 9, 1)
INTERVALS_ID = "i-1"
WAHOO_ID = "501"
GARMIN_ID = "9001"
SESSION_COLUMNS = (
    "activity_id, primary_provider, primary_provider_activity_id, link_kind, "
    "athlete_confirmed, state, merged_into, updated_at"
)


def intervals_ride(identifier: str = INTERVALS_ID, **fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": identifier,
        "type": "Ride",
        "device_name": "Wahoo ELEMNT",
        "start_date_local": "2026-09-10T07:00:00",
        "moving_time": 3600,
        "distance": 30000.0,
    }
    row.update(fields)
    return row


def wahoo_workout(identifier: str = WAHOO_ID, **fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": identifier,
        "starts": "2026-09-10T05:02:00.000Z",
        "name": "Ride",
        "workout_type_id": 0,
        "workout_summary": {
            "duration_active_accum": "3600",
            "distance_accum": "30100",
        },
    }
    row.update(fields)
    return row


def garmin_ride(identifier: str = GARMIN_ID, **fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "activityId": identifier,
        "activityType": {"typeKey": "cycling"},
        "startTimeLocal": "2026-09-10 07:05:00",
        "duration": 3600.0,
        "distance": 30050.0,
    }
    row.update(fields)
    return row


class LinkingCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = DatabaseManager(
            Path(directory.name) / "linking.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)

    def _ingest_intervals(
        self, rows: list[dict[str, Any]], at: datetime
    ) -> ingest.CanonicalIngestCounters:
        snapshot = {
            "synced_at": at.isoformat(),
            "raw_provider_data": {"activities": rows},
        }
        with self.manager.unit_of_work() as db:
            return intervals_fixture.ingest_intervals_snapshot(
                db,
                snapshot,
                zone=ZONE,
                activity_days=None,
                all_sync_days=3,
                earliest_date=EARLIEST,
            )

    def _ingest_wahoo(
        self, workouts: list[dict[str, Any]], at: datetime
    ) -> ingest.CanonicalIngestCounters:
        plan = wahoo_ingest_plan(
            {"synced_at": at.isoformat(), "workouts": workouts}, zone=ZONE
        )
        with self.manager.unit_of_work() as db:
            return ingest.ingest_plan(
                db, plan, retrieved_at=at, deletion_window=None, zone=ZONE
            )

    def _ingest_garmin(
        self, rows: list[dict[str, Any]], at: datetime
    ) -> ingest.CanonicalIngestCounters:
        payload = {"synced_at": at.isoformat(), "activities": rows}
        with self.manager.unit_of_work() as db:
            return ingest.ingest_garmin_payload(db, payload, zone=ZONE)

    def _sessions(self) -> dict[str, dict[str, Any]]:
        """Return session rows keyed by the provider activity id of their primary."""
        with self.manager.reader() as db:
            rows = db.execute(f"SELECT {SESSION_COLUMNS} FROM activity_sessions")
            return {row["primary_provider_activity_id"]: dict(row) for row in rows}

    def _snapshot(self) -> tuple[list[Any], list[Any]]:
        with self.manager.reader() as db:
            sessions = [
                tuple(row)
                for row in db.execute(
                    f"SELECT {SESSION_COLUMNS} FROM activity_sessions ORDER BY 1"
                )
            ]
            records = [
                tuple(row)
                for row in db.execute(
                    "SELECT provider, provider_activity_id, activity_id, state, "
                    "updated_at FROM activity_records ORDER BY 1, 2"
                )
            ]
        return sessions, records

    def _ingest_all_three(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        self._ingest_wahoo([wahoo_workout()], SECOND)
        self._ingest_garmin([garmin_ride()], THIRD)

    def _set_session(self, provider_activity_id: str, **columns: Any) -> None:
        assignments = ", ".join(f"{name} = ?" for name in columns)
        with self.manager.unit_of_work() as db:
            db.execute(
                f"UPDATE activity_sessions SET {assignments} "
                "WHERE primary_provider_activity_id = ?",
                (*columns.values(), provider_activity_id),
            )


class PersistedLinkTests(LinkingCase):
    def test_three_providers_of_one_ride_become_one_surviving_session(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        wahoo_counters = self._ingest_wahoo([wahoo_workout()], SECOND)
        garmin_counters = self._ingest_garmin([garmin_ride()], THIRD)
        self.assertEqual((wahoo_counters.linked, garmin_counters.linked), (1, 1))
        sessions = self._sessions()
        survivor = sessions[INTERVALS_ID]
        self.assertEqual(survivor["state"], "active")
        self.assertEqual(survivor["link_kind"], "heuristic")
        self.assertIsNone(survivor["merged_into"])
        for provider_activity_id in (WAHOO_ID, GARMIN_ID):
            alias = sessions[provider_activity_id]
            self.assertEqual(alias["state"], "duplicate")
            self.assertEqual(alias["merged_into"], survivor["activity_id"])
            self.assertEqual(alias["link_kind"], "single")

    def test_records_and_primary_columns_are_not_repointed(self) -> None:
        self._ingest_all_three()
        with self.manager.reader() as db:
            rows = db.execute(
                "SELECT r.provider, r.provider_activity_id, r.activity_id, "
                "s.primary_provider, s.primary_provider_activity_id "
                "FROM activity_records AS r JOIN activity_sessions AS s "
                "ON s.activity_id = r.activity_id"
            ).fetchall()
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["provider"], row["primary_provider"])
            self.assertEqual(
                row["provider_activity_id"], row["primary_provider_activity_id"]
            )

    def test_the_older_session_survives_whatever_the_ingest_order(self) -> None:
        self._ingest_wahoo([wahoo_workout()], FIRST)
        self._ingest_intervals([intervals_ride()], SECOND)
        sessions = self._sessions()
        self.assertEqual(sessions[WAHOO_ID]["state"], "active")
        self.assertEqual(sessions[INTERVALS_ID]["state"], "duplicate")
        self.assertEqual(
            sessions[INTERVALS_ID]["merged_into"], sessions[WAHOO_ID]["activity_id"]
        )

    def test_a_later_garmin_ride_joins_the_survivor_of_an_alias(self) -> None:
        self._ingest_wahoo([wahoo_workout()], FIRST)
        self._ingest_intervals([intervals_ride()], SECOND)
        self._ingest_garmin([garmin_ride()], THIRD)
        sessions = self._sessions()
        survivor = sessions[WAHOO_ID]["activity_id"]
        self.assertEqual(sessions[GARMIN_ID]["merged_into"], survivor)
        self.assertEqual(sessions[INTERVALS_ID]["merged_into"], survivor)

    def test_a_relink_never_merges_two_records_of_one_origin(self) -> None:
        # Two walks 25 minutes apart. G2 arrives first and joins I1, its only
        # candidate. Once I2 and G1 arrive, bundling pairs G1 with I1 and G2 with
        # I2; following those pairs through the persisted merge would join all
        # four records in one session.
        def walk(identifier: str, start: str, seconds: int) -> dict[str, Any]:
            return intervals_ride(
                identifier,
                type="Walk",
                device_name="Garmin Forerunner",
                start_date_local=f"2026-09-10T{start}:00",
                moving_time=seconds,
                distance=None,
            )

        def garmin_walk(identifier: str, start: str, seconds: float) -> dict[str, Any]:
            return garmin_ride(
                identifier,
                activityType={"typeKey": "walking"},
                startTimeLocal=f"2026-09-10 {start}:00",
                duration=seconds,
                distance=None,
            )

        first = walk("i-1", "07:00", 2400)
        self._ingest_intervals([first], FIRST)
        self._ingest_garmin([garmin_walk("9002", "07:25", 2280.0)], SECOND)
        self._ingest_intervals([first, walk("i-2", "07:25", 2280)], THIRD)
        self._ingest_garmin(
            [
                garmin_walk("9001", "07:00", 2400.0),
                garmin_walk("9002", "07:25", 2280.0),
            ],
            LATER,
        )

        sessions = self._sessions()
        self.assertEqual(
            sessions["9002"]["merged_into"], sessions["i-1"]["activity_id"]
        )
        for provider_activity_id in ("i-1", "i-2", "9001"):
            self.assertEqual(sessions[provider_activity_id]["state"], "active")

    def test_unrelated_activities_stay_single(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        counters = (
            self._ingest_wahoo(
                [wahoo_workout(starts="2026-09-10T12:00:00.000Z")], SECOND
            ),
            self._ingest_garmin(
                [garmin_ride(startTimeLocal="2026-09-12 07:00:00")], THIRD
            ),
        )
        self.assertEqual(sum(item.linked for item in counters), 0)
        states = {row["state"] for row in self._sessions().values()}
        self.assertEqual(states, {"active"})

    def test_a_ride_on_the_next_local_day_links_across_midnight(self) -> None:
        late = intervals_ride(start_date_local="2026-09-10T23:50:00")
        self._ingest_intervals([late], FIRST)
        # 00:05 on the next local day is 15 minutes later on the wall clock.
        self._ingest_wahoo([wahoo_workout(starts="2026-09-10T22:05:00.000Z")], SECOND)
        self.assertEqual(self._sessions()[WAHOO_ID]["state"], "duplicate")

    def test_a_stored_row_of_an_unknown_provider_is_skipped(self) -> None:
        stamp = "2026-09-10T05:01:00+00:00"
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO activity_sessions(activity_id, primary_provider, "
                "primary_provider_activity_id, started_at, local_date, created_at, "
                "updated_at) VALUES ('act_other', 'other-provider', 'o-1', ?, "
                "'2026-09-10', ?, ?)",
                (stamp, stamp, stamp),
            )
            db.execute(
                "INSERT INTO activity_records(provider, provider_activity_id, "
                "activity_id, mapper_version, source_kind, recorded_by, sport, "
                "environment, started_at, local_date, duration_s, distance_m, load, "
                "load_model, avg_hr, avg_power, name, details, fetched_at, "
                "created_at, updated_at) VALUES ('other-provider', 'o-1', "
                "'act_other', 1, 'provider_reported', 'unknown', 'ride', 'indoor', "
                "?, '2026-09-10', 3600.0, 30000.0, 60.0, 'unknown', 140.0, 200.0, "
                "'Ride', '{}', ?, ?, ?)",
                (stamp, stamp, stamp, stamp),
            )
        self._ingest_intervals([intervals_ride()], FIRST)
        counters = self._ingest_wahoo([wahoo_workout()], SECOND)
        self.assertEqual(counters.linked, 1)
        other = self._sessions()["o-1"]
        self.assertEqual((other["state"], other["merged_into"]), ("active", None))


class WahooPlaceholderTests(LinkingCase):
    def _store_placeholder_as_an_older_build_did(self) -> None:
        workout = wahoo_workout(workout_summary=None)
        mapped = map_wahoo_activities([workout], zone=ZONE, retrieved_at=SECOND)
        record = mapped.records[0]
        plan = IngestPlan(
            provider=ProviderId.WAHOO,
            activities=(
                ActivityItem(
                    record=record,
                    local_date=record.started_at.astimezone(ZONE).date(),
                    mapper_version=WAHOO_VERSION,
                ),
            ),
        )
        with self.manager.unit_of_work() as db:
            ingest.ingest_plan(
                db, plan, retrieved_at=SECOND, deletion_window=None, zone=ZONE
            )

    def _states(self) -> dict[str, str]:
        with self.manager.reader() as db:
            return {
                row["primary_provider_activity_id"]: row["state"]
                for row in db.execute(
                    "SELECT primary_provider_activity_id, state FROM activity_sessions"
                )
            }

    def test_a_listed_placeholder_never_becomes_a_session(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        counters = self._ingest_wahoo([wahoo_workout(workout_summary=None)], SECOND)

        self.assertEqual((counters.written, counters.deleted), (0, 0))
        self.assertEqual({INTERVALS_ID: "active"}, self._states())

    def test_a_stored_placeholder_is_withdrawn_and_revived_with_its_summary(
        self,
    ) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        self._store_placeholder_as_an_older_build_did()
        self.assertEqual({INTERVALS_ID: "active", WAHOO_ID: "active"}, self._states())

        withdrawn = self._ingest_wahoo([wahoo_workout(workout_summary=None)], THIRD)
        self.assertEqual(withdrawn.deleted, 1)
        self.assertEqual({INTERVALS_ID: "active", WAHOO_ID: "deleted"}, self._states())
        self.assertEqual(
            self._ingest_wahoo([wahoo_workout(workout_summary=None)], LATER).deleted,
            0,
        )

        recorded = self._ingest_wahoo([wahoo_workout()], LATER)
        self.assertEqual((recorded.updated, recorded.linked), (1, 1))
        sessions = self._sessions()
        self.assertEqual(sessions[WAHOO_ID]["state"], "duplicate")
        self.assertIsNotNone(sessions[WAHOO_ID]["merged_into"])

    def test_a_stored_recording_listed_without_its_summary_is_kept(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        self._ingest_wahoo([wahoo_workout()], SECOND)
        before = self._snapshot()

        counters = self._ingest_wahoo([wahoo_workout(workout_summary=None)], THIRD)

        self.assertEqual(counters.deleted, 0)
        self.assertEqual(before, self._snapshot())


class IdempotenceTests(LinkingCase):
    def test_reingesting_changes_neither_rows_nor_states(self) -> None:
        self._ingest_all_three()
        before = self._snapshot()
        repeated = (
            self._ingest_intervals([intervals_ride()], LATER),
            self._ingest_wahoo([wahoo_workout()], LATER),
            self._ingest_garmin([garmin_ride()], LATER),
        )
        after = self._snapshot()
        self.assertEqual(before[0], after[0])
        self.assertEqual(len(before[1]), len(after[1]))
        self.assertEqual(sum(counters.linked for counters in repeated), 0)
        self.assertEqual(sum(counters.written for counters in repeated), 0)

    def test_linking_directly_a_second_time_is_a_no_op(self) -> None:
        self._ingest_all_three()
        before = self._snapshot()
        with self.manager.unit_of_work() as db:
            linked = link_activity_sessions(
                db,
                touched_dates={date(2026, 9, 10)},
                zone=ZONE,
                now=LATER.isoformat(),
            )
        self.assertEqual(linked, 0)
        self.assertEqual(self._snapshot(), before)


class ProtectedSessionTests(LinkingCase):
    def test_confirmed_session_is_never_merged(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        self._set_session(INTERVALS_ID, athlete_confirmed=1, link_kind="confirmed")
        counters = self._ingest_wahoo([wahoo_workout()], SECOND)
        self.assertEqual(counters.linked, 0)
        sessions = self._sessions()
        self.assertEqual(sessions[INTERVALS_ID]["state"], "active")
        self.assertEqual(sessions[INTERVALS_ID]["link_kind"], "confirmed")
        self.assertEqual(sessions[WAHOO_ID]["state"], "active")

    def test_hidden_session_is_never_merged_or_reopened(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        self._set_session(INTERVALS_ID, state="hidden")
        counters = self._ingest_wahoo([wahoo_workout()], SECOND)
        self.assertEqual(counters.linked, 0)
        self.assertEqual(self._sessions()[INTERVALS_ID]["state"], "hidden")
        self.assertEqual(self._sessions()[WAHOO_ID]["state"], "active")

    def test_deleted_session_is_never_merged(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        self._set_session(INTERVALS_ID, state="deleted")
        counters = self._ingest_wahoo([wahoo_workout()], SECOND)
        self.assertEqual(counters.linked, 0)
        self.assertEqual(self._sessions()[INTERVALS_ID]["state"], "deleted")
        self.assertEqual(self._sessions()[WAHOO_ID]["state"], "active")

    def test_an_alias_that_no_longer_matches_is_split_off(self) -> None:
        self._ingest_all_three()
        survivor = self._sessions()[INTERVALS_ID]["activity_id"]
        # The Wahoo workout later drifts out of the matching window.
        self._ingest_wahoo([wahoo_workout(starts="2026-09-10T12:00:00.000Z")], LATER)
        alias = self._sessions()[WAHOO_ID]
        self.assertEqual((alias["state"], alias["merged_into"]), ("active", None))
        self.assertEqual(self._sessions()[INTERVALS_ID]["activity_id"], survivor)

    def test_a_confirmed_session_is_never_split(self) -> None:
        self._ingest_all_three()
        survivor = self._sessions()[INTERVALS_ID]["activity_id"]
        self._set_session(INTERVALS_ID, athlete_confirmed=1)
        self._ingest_wahoo([wahoo_workout(starts="2026-09-10T12:00:00.000Z")], LATER)
        alias = self._sessions()[WAHOO_ID]
        self.assertEqual(
            (alias["state"], alias["merged_into"]), ("duplicate", survivor)
        )

    def test_a_confirmed_link_kind_is_never_downgraded(self) -> None:
        self._ingest_intervals([intervals_ride()], FIRST)
        self._set_session(INTERVALS_ID, link_kind="confirmed")
        self._ingest_wahoo([wahoo_workout()], SECOND)
        self.assertEqual(self._sessions()[INTERVALS_ID]["link_kind"], "confirmed")
        self.assertEqual(self._sessions()[WAHOO_ID]["state"], "duplicate")


def _states(sessions: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {key: row["state"] for key, row in sessions.items()}


def _yoga_workout() -> dict[str, Any]:
    return wahoo_workout(
        workout_type_id=66, workout_summary={"duration_active_accum": "3600"}
    )


class AllSportsBundlingTests(LinkingCase):
    """A Garmin and a Wahoo copy of one session bundle whatever the sport."""

    def _assert_bundled(
        self, garmin_rows: list[dict[str, Any]], wahoo_rows: list[dict[str, Any]]
    ) -> None:
        self._ingest_garmin(garmin_rows, FIRST)
        counters = self._ingest_wahoo(wahoo_rows, SECOND)
        self.assertEqual(counters.linked, 1)
        sessions = self._sessions()
        self.assertEqual(
            _states(sessions), {GARMIN_ID: "active", WAHOO_ID: "duplicate"}
        )
        self.assertEqual(
            sessions[WAHOO_ID]["merged_into"], sessions[GARMIN_ID]["activity_id"]
        )

    def test_a_run_recorded_twice_is_one_session(self) -> None:
        self._assert_bundled(
            [garmin_ride(activityType={"typeKey": "running"}, distance=10000.0)],
            [
                wahoo_workout(
                    workout_type_id=1,
                    workout_summary={
                        "duration_active_accum": "3600",
                        "distance_accum": "10050",
                    },
                )
            ],
        )

    def test_a_walk_recorded_twice_is_one_session(self) -> None:
        self._assert_bundled(
            [garmin_ride(activityType={"typeKey": "walking"}, distance=4000.0)],
            [
                wahoo_workout(
                    workout_type_id=6,
                    workout_summary={
                        "duration_active_accum": "3600",
                        "distance_accum": "4020",
                    },
                )
            ],
        )

    def test_a_yoga_session_without_distance_is_one_session(self) -> None:
        self._assert_bundled(
            [garmin_ride(activityType={"typeKey": "yoga"}, distance=None)],
            [_yoga_workout()],
        )

    def test_an_indoor_ride_without_garmin_distance_is_one_session(self) -> None:
        self._assert_bundled(
            [garmin_ride(activityType={"typeKey": "indoor_cycling"}, distance=0.0)],
            [
                wahoo_workout(
                    workout_type_id=12,
                    workout_summary={
                        "duration_active_accum": "3600",
                        "distance_accum": "25000",
                    },
                )
            ],
        )

    def test_a_ride_with_a_stop_and_elapsed_only_garmin_time_is_one_session(
        self,
    ) -> None:
        # Garmin sends only the 3900 s elapsed time; Wahoo moved for 3300 s.
        self._assert_bundled(
            [garmin_ride(duration=3900.0)],
            [
                wahoo_workout(
                    workout_summary={
                        "duration_active_accum": "3300",
                        "duration_total_accum": "3900",
                        "distance_accum": "30100",
                    }
                )
            ],
        )

    def test_a_watch_recording_and_a_relayed_copy_join_the_wahoo_ride(self) -> None:
        self._ingest_wahoo([wahoo_workout()], FIRST)
        self._ingest_garmin(
            [
                garmin_ride("9001", manufacturer="WAHOO_FITNESS"),
                garmin_ride(
                    "9002",
                    manufacturer="GARMIN",
                    startTimeLocal="2026-09-10 07:01:00",
                    duration=3700.0,
                ),
            ],
            SECOND,
        )
        self.assertEqual(
            _states(self._sessions()),
            {WAHOO_ID: "active", "9001": "duplicate", "9002": "duplicate"},
        )

    def test_a_run_and_a_yoga_session_stay_two_sessions(self) -> None:
        self._ingest_garmin(
            [garmin_ride(activityType={"typeKey": "running"}, distance=None)], FIRST
        )
        self._ingest_wahoo([_yoga_workout()], SECOND)
        self.assertEqual(
            _states(self._sessions()), {GARMIN_ID: "active", WAHOO_ID: "active"}
        )

    def test_two_separate_sessions_on_one_day_stay_apart(self) -> None:
        self._ingest_garmin(
            [
                garmin_ride(activityType={"typeKey": "yoga"}, distance=None),
                garmin_ride(
                    "9002",
                    activityType={"typeKey": "yoga"},
                    distance=None,
                    startTimeLocal="2026-09-10 15:00:00",
                ),
            ],
            FIRST,
        )
        self._ingest_wahoo([_yoga_workout()], SECOND)
        sessions = self._sessions()
        self.assertEqual(
            _states(sessions),
            {GARMIN_ID: "active", "9002": "active", WAHOO_ID: "duplicate"},
        )
        self.assertEqual(
            sessions[WAHOO_ID]["merged_into"], sessions[GARMIN_ID]["activity_id"]
        )


class ConfirmedBundleRevivalTests(LinkingCase):
    def _confirmed_bundle(self) -> None:
        self._ingest_garmin([garmin_ride()], FIRST)
        self._ingest_wahoo([wahoo_workout()], SECOND)
        self._set_session(GARMIN_ID, athlete_confirmed=1, link_kind="confirmed")

    def _delete_garmin(self) -> None:
        with self.manager.unit_of_work() as db:
            canonical_store.mark_activity_deleted(
                db,
                ProviderId.GARMIN.value,
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id=GARMIN_ID,
                now=THIRD.isoformat(),
            )

    def test_a_confirmed_survivor_deleted_and_redelivered_stays_one_session(
        self,
    ) -> None:
        self._confirmed_bundle()
        self._delete_garmin()
        after_delete = self._sessions()
        self.assertEqual(after_delete[WAHOO_ID]["state"], "active")
        self.assertEqual(after_delete[WAHOO_ID]["athlete_confirmed"], 1)
        self._ingest_garmin([garmin_ride(duration=3601.0)], LATER)
        sessions = self._sessions()
        self.assertEqual(
            _states(sessions), {GARMIN_ID: "duplicate", WAHOO_ID: "active"}
        )
        self.assertEqual(
            sessions[GARMIN_ID]["merged_into"], sessions[WAHOO_ID]["activity_id"]
        )
        self.assertEqual(sessions[GARMIN_ID]["athlete_confirmed"], 0)
        self.assertEqual(sessions[WAHOO_ID]["athlete_confirmed"], 1)

    def test_a_second_redelivery_changes_nothing(self) -> None:
        self._confirmed_bundle()
        self._delete_garmin()
        self._ingest_garmin([garmin_ride(duration=3601.0)], LATER)
        before = self._snapshot()
        self._ingest_garmin([garmin_ride(duration=3601.0)], LATER)
        self.assertEqual(self._snapshot(), before)

    def test_an_unconfirmed_bundle_is_one_session_after_a_redelivery(self) -> None:
        self._ingest_garmin([garmin_ride()], FIRST)
        self._ingest_wahoo([wahoo_workout()], SECOND)
        self._delete_garmin()
        self._ingest_garmin([garmin_ride(duration=3601.0)], LATER)
        self.assertEqual(
            _states(self._sessions()), {GARMIN_ID: "duplicate", WAHOO_ID: "active"}
        )

    def test_a_revived_copy_that_no_longer_matches_an_unconfirmed_bundle_splits(
        self,
    ) -> None:
        self._ingest_garmin([garmin_ride()], FIRST)
        self._ingest_wahoo([wahoo_workout()], SECOND)
        self._delete_garmin()
        self._ingest_garmin([garmin_ride(startTimeLocal="2026-09-10 15:00:00")], LATER)
        self.assertEqual(
            _states(self._sessions()), {GARMIN_ID: "active", WAHOO_ID: "active"}
        )

    def test_a_session_the_athlete_deleted_stays_deleted_on_redelivery(self) -> None:
        self._ingest_garmin([garmin_ride()], FIRST)
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted', "
                "merged_into_retained = activity_id "
                "WHERE primary_provider_activity_id = ?",
                (GARMIN_ID,),
            )
        self._ingest_garmin([garmin_ride(duration=3601.0)], LATER)
        self.assertEqual(self._sessions()[GARMIN_ID]["state"], "deleted")
        # A first-time copy from another provider is deleted with it (#2137, B-011).
        self._ingest_wahoo([wahoo_workout()], LATER)
        with self.manager.reader() as db:
            copy = db.execute(
                "SELECT state, merged_into_retained FROM activity_sessions "
                "WHERE primary_provider_activity_id = ?",
                (WAHOO_ID,),
            ).fetchone()
        self.assertEqual(
            ("deleted", self._sessions()[GARMIN_ID]["activity_id"]),
            (copy["state"], copy["merged_into_retained"]),
        )
        # Undoing the athlete's delete brings the copy back (session_corrections).
        survivor = self._sessions()[GARMIN_ID]["activity_id"]
        self._set_session(GARMIN_ID, state="active", merged_into_retained=None)
        with self.manager.unit_of_work() as db:
            revived = canonical_store.revive_deleted_copies(
                db, survivor, exclude={survivor}, now=LATER
            )
        self.assertEqual(1, revived)
        self.assertEqual(
            ("duplicate", survivor),
            (
                self._sessions()[WAHOO_ID]["state"],
                self._sessions()[WAHOO_ID]["merged_into"],
            ),
        )


class ExactLinkTests(LinkingCase):
    def _garmin_copy(self, external_id: str, **fields: Any) -> dict[str, Any]:
        return intervals_ride(
            device_name="Garmin Edge 840",
            source="GARMIN_CONNECT",
            external_id=external_id,
            **fields,
        )

    def test_a_trimmed_copy_links_exactly_to_its_garmin_activity(self) -> None:
        self._ingest_garmin([garmin_ride()], FIRST)
        counters = self._ingest_intervals(
            [self._garmin_copy(GARMIN_ID, distance=21000.0)], SECOND
        )
        self.assertEqual(counters.linked, 1)
        sessions = self._sessions()
        self.assertEqual(sessions[GARMIN_ID]["link_kind"], "exact")
        self.assertEqual(
            sessions[INTERVALS_ID]["merged_into"], sessions[GARMIN_ID]["activity_id"]
        )

    def test_an_exact_reference_upgrades_a_heuristic_merge(self) -> None:
        self._ingest_intervals([intervals_ride(device_name="Garmin Edge")], FIRST)
        self._ingest_garmin([garmin_ride()], SECOND)
        self.assertEqual(self._sessions()[INTERVALS_ID]["link_kind"], "heuristic")

        self._ingest_intervals([self._garmin_copy(GARMIN_ID)], THIRD)

        sessions = self._sessions()
        self.assertEqual(sessions[INTERVALS_ID]["link_kind"], "exact")
        self.assertEqual(
            sessions[GARMIN_ID]["merged_into"], sessions[INTERVALS_ID]["activity_id"]
        )

    def test_a_hidden_upstream_keeps_its_copy_from_the_heuristics(self) -> None:
        self._ingest_garmin([garmin_ride()], FIRST)
        self._set_session(GARMIN_ID, state="hidden")
        # A second Garmin recording of the ride, within every tolerance.
        self._ingest_garmin([garmin_ride("9002")], SECOND)
        self._ingest_intervals([self._garmin_copy(GARMIN_ID)], THIRD)

        sessions = self._sessions()
        self.assertEqual(sessions["9002"]["state"], "active")
        self.assertEqual(sessions[INTERVALS_ID]["state"], "active")
        self.assertEqual(sessions[GARMIN_ID]["state"], "hidden")

    def test_a_contradicted_heuristic_merge_is_not_changed(self) -> None:
        self._ingest_intervals([intervals_ride(device_name="Garmin Edge")], FIRST)
        self._ingest_garmin(
            [garmin_ride(), garmin_ride("9002", startTimeLocal="2026-09-10 12:00:00")],
            SECOND,
        )
        before = self._sessions()

        self._ingest_intervals([self._garmin_copy("9002")], THIRD)

        after = self._sessions()
        for provider_activity_id in (INTERVALS_ID, GARMIN_ID, "9002"):
            self.assertEqual(
                (
                    after[provider_activity_id]["state"],
                    after[provider_activity_id]["merged_into"],
                ),
                (
                    before[provider_activity_id]["state"],
                    before[provider_activity_id]["merged_into"],
                ),
            )


class AliasResolutionTests(LinkingCase):
    def _references(self) -> ActivityReferences:
        return ActivityReferences(self.manager)

    def test_a_wahoo_alias_resolves_to_its_own_session(self) -> None:
        self._ingest_all_three()
        wahoo_alias = self._sessions()[WAHOO_ID]["activity_id"]
        reference = self._references().resolve_reference(wahoo_alias)
        # Athlete data is stored under the session it was written for.
        self.assertEqual(
            (reference.activity_id, reference.provider), (wahoo_alias, None)
        )


class ReadersUnchangedTests(LinkingCase):
    def test_table_reads_return_every_record_before_and_after_linking(self) -> None:
        self._ingest_all_three()
        with self.manager.reader() as db:
            rows = canonical_store.active_activity_rows(db)
            texts = [
                row["payload"]
                for row in db.execute(
                    "SELECT payload FROM provider_records WHERE provider = ? "
                    "AND record_kind = ? AND state = 'active'",
                    (ProviderId.INTERVALS.value, ACTIVITY_RECORD_KIND),
                )
            ]
        self.assertEqual(
            sorted((row["provider"], row["provider_activity_id"]) for row in rows),
            [
                (ProviderId.GARMIN.value, GARMIN_ID),
                (ProviderId.INTERVALS.value, INTERVALS_ID),
                (ProviderId.WAHOO.value, WAHOO_ID),
            ],
        )
        self.assertEqual(len(texts), 1)

    def test_deleting_the_intervals_activity_leaves_the_aliases_readable(self) -> None:
        self._ingest_all_three()
        with self.manager.unit_of_work() as db:
            canonical_store.mark_activity_deleted(
                db,
                ProviderId.INTERVALS.value,
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id=INTERVALS_ID,
                now=LATER.isoformat(),
            )
            rows = canonical_store.active_activity_rows(db)
        self.assertEqual(
            sorted(row["provider"] for row in rows),
            [ProviderId.GARMIN.value, ProviderId.WAHOO.value],
        )


class CounterTests(unittest.TestCase):
    def test_linked_is_reported_with_the_other_counts(self) -> None:
        counters = ingest.CanonicalIngestCounters(linked=2)
        self.assertEqual(counters.as_dict()["linked"], 2)
        self.assertEqual(ingest.CanonicalIngestCounters().as_dict()["linked"], 0)


if __name__ == "__main__":
    unittest.main()
