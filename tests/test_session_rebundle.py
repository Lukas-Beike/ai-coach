"""One-time re-bundling of stored Garmin and Wahoo copies (#1954).

Synthetic provider rows in a temporary database; no provider, network or real
data directory is involved.
"""

from __future__ import annotations

import logging
import unittest
from datetime import UTC, datetime
from typing import Any
from unittest import mock

from test_session_linking import (
    ZONE,
    LinkingCase,
    garmin_ride,
    wahoo_workout,
)

from backend.db import canonical_store
from backend.db.repositories import KeyValueRepository
from backend.sync import session_rebundle
from backend.sync.session_rebundle import (
    SessionRebundle,
    summarize_session_rebundle,
)

NOW = "2026-11-10T08:00:00+00:00"
FIRST = datetime(2026, 9, 11, 8, 0, tzinfo=UTC)
SECOND = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)
RUN_GARMIN = "9101"
RUN_WAHOO = "601"
RIDE_GARMIN = "9102"
RIDE_WAHOO = "602"
CONFIRMED_GARMIN = "9103"
CONFIRMED_WAHOO = "603"
DELETED_GARMIN = "9104"
DELETED_WAHOO = "604"


def _wahoo_run() -> dict[str, Any]:
    return wahoo_workout(
        RUN_WAHOO,
        starts="2026-09-02T05:02:00.000Z",
        workout_type_id=1,
        workout_summary={
            "duration_active_accum": "3600",
            "distance_accum": "10050",
        },
    )


def _garmin_run() -> dict[str, Any]:
    return garmin_ride(
        RUN_GARMIN,
        activityType={"typeKey": "running"},
        startTimeLocal="2026-09-02 07:05:00",
        distance=10000.0,
    )


def _garmin_indoor_ride() -> dict[str, Any]:
    return garmin_ride(
        RIDE_GARMIN,
        activityType={"typeKey": "indoor_cycling"},
        startTimeLocal="2026-09-04 07:05:00",
        distance=0.0,
    )


def _wahoo_indoor_ride() -> dict[str, Any]:
    return wahoo_workout(
        RIDE_WAHOO,
        starts="2026-09-04T05:02:00.000Z",
        workout_type_id=12,
        workout_summary={
            "duration_active_accum": "3600",
            "distance_accum": "25000",
        },
    )


def _pair(identifier_garmin: str, identifier_wahoo: str, day: str) -> tuple[Any, Any]:
    return (
        garmin_ride(identifier_garmin, startTimeLocal=f"2026-09-{day} 07:05:00"),
        wahoo_workout(identifier_wahoo, starts=f"2026-09-{day}T05:02:00.000Z"),
    )


class SessionRebundleTests(LinkingCase):
    def setUp(self) -> None:
        super().setUp()
        self.key_values = KeyValueRepository(lambda: NOW)
        self.stage = SessionRebundle(
            key_values=self.key_values,
            clock=lambda: NOW,
            zone_provider=lambda: ZONE,
            database_manager=lambda: self.manager,
        )

    def _unbundle(self, *wahoo_ids: str) -> None:
        """Return the stored copies to separate sessions, as an older build left them."""
        with self.manager.unit_of_work() as db:
            for wahoo_id in wahoo_ids:
                row = db.execute(
                    "SELECT activity_id FROM activity_sessions "
                    "WHERE primary_provider_activity_id = ?",
                    (wahoo_id,),
                ).fetchone()
                self.assertTrue(
                    canonical_store.detach_activity_session(
                        db, activity_id=row["activity_id"], now=NOW
                    )
                )

    def _run(self):
        with self.manager.unit_of_work() as db:
            return self.stage.run_batch(db)

    def _summary(self) -> dict[str, Any]:
        with self.manager.reader() as db:
            return summarize_session_rebundle(self.key_values, db)

    def _unbundled_pairs(self) -> None:
        garmin_run, wahoo_run = _garmin_run(), _wahoo_run()
        self._ingest_garmin([garmin_run, _garmin_indoor_ride()], FIRST)
        self._ingest_wahoo([wahoo_run, _wahoo_indoor_ride()], SECOND)
        self._unbundle(RUN_WAHOO, RIDE_WAHOO)
        self.assertEqual(
            {"active"}, {row["state"] for row in self._sessions().values()}
        )

    def test_unbundled_run_and_ride_without_distance_bundle_once(self) -> None:
        self._unbundled_pairs()

        report = self._run()

        sessions = self._sessions()
        self.assertEqual((2, True), (report.items, report.done))
        for garmin_id, wahoo_id in (
            (RUN_GARMIN, RUN_WAHOO),
            (RIDE_GARMIN, RIDE_WAHOO),
        ):
            self.assertEqual("active", sessions[garmin_id]["state"])
            self.assertEqual("duplicate", sessions[wahoo_id]["state"])
            self.assertEqual(
                sessions[garmin_id]["activity_id"], sessions[wahoo_id]["merged_into"]
            )
        self.assertEqual(
            {
                "status": "complete",
                "version": 1,
                "counts": {"days": 2, "linked": 2},
            },
            self._summary(),
        )

    def test_a_second_startup_does_nothing(self) -> None:
        self._unbundled_pairs()
        self._run()
        before = self._snapshot()

        report = self._run()

        self.assertEqual((0, True), (report.items, report.done))
        self.assertEqual(before, self._snapshot())

    def test_a_pair_separated_after_the_pass_is_not_bundled_again(self) -> None:
        self._unbundled_pairs()
        self._run()
        self._unbundle(RUN_WAHOO)
        before = self._snapshot()

        self._run()

        self.assertEqual(before, self._snapshot())

    def test_confirmed_and_deleted_sessions_stay_untouched(self) -> None:
        self._unbundled_pairs()
        confirmed = _pair(CONFIRMED_GARMIN, CONFIRMED_WAHOO, "06")
        deleted = _pair(DELETED_GARMIN, DELETED_WAHOO, "08")
        self._ingest_garmin([confirmed[0], deleted[0]], FIRST)
        self._ingest_wahoo([confirmed[1], deleted[1]], SECOND)
        self._unbundle(CONFIRMED_WAHOO, DELETED_WAHOO)
        self._set_session(CONFIRMED_WAHOO, athlete_confirmed=1, link_kind="confirmed")
        self._set_session(DELETED_WAHOO, state="deleted")
        untouched = {CONFIRMED_GARMIN, CONFIRMED_WAHOO, DELETED_GARMIN, DELETED_WAHOO}
        before = {key: row for key, row in self._sessions().items() if key in untouched}

        self._run()

        sessions = self._sessions()
        self.assertEqual(before, {key: sessions[key] for key in untouched})
        self.assertEqual("duplicate", sessions[RUN_WAHOO]["state"])
        self.assertEqual("duplicate", sessions[RIDE_WAHOO]["state"])
        self.assertEqual("deleted", sessions[DELETED_WAHOO]["state"])

    def test_a_failure_leaves_the_data_unchanged_and_is_retried(self) -> None:
        self._unbundled_pairs()
        before = self._snapshot()
        real = session_rebundle.link_activity_sessions
        calls = []

        def fail_on_the_second_day(*args: Any, **kwargs: Any) -> int:
            calls.append(kwargs["touched_dates"])
            if len(calls) == 2:
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        with (
            mock.patch.object(
                session_rebundle,
                "link_activity_sessions",
                side_effect=fail_on_the_second_day,
            ),
            mock.patch.object(session_rebundle, "_log_completed") as log,
            self.assertRaises(RuntimeError),
        ):
            self._run()

        self.assertEqual(2, len(calls))
        self.assertEqual(before, self._snapshot())
        self.assertEqual("pending", self._summary()["status"])
        log.assert_not_called()

        with self.manager.unit_of_work() as db:
            self.stage.mark_failed(db)
        self.assertEqual("failed", self._summary()["status"])
        self.assertEqual(2, self._run().items)
        self.assertEqual("complete", self._summary()["status"])

    def test_the_log_line_carries_counts_only(self) -> None:
        self._unbundled_pairs()

        with self.assertLogs("intervals_coach", level=logging.INFO) as logs:
            self._run()

        record = next(
            r
            for r in logs.records
            if r.__dict__.get("event") == "session_rebundle_completed"
        )
        self.assertEqual({"days": 2, "linked": 2}, record.__dict__["context"])


if __name__ == "__main__":
    unittest.main()
