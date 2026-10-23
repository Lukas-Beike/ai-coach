"""Automatic Garmin activity detail backfill: candidates, batches, pauses, and reader lifecycle."""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import Mock, patch

from canonical_detail_support import NOW, ZONE, open_manager, seed_intervals_activity
from support import make_config
from test_garmin_activity_detail_job import _collected

from backend.canonical.vocabulary import ActivityRecordState, RecordingOrigin
from backend.db.activity_detail_store import (
    activity_detail_backfill_candidates,
    activity_detail_backfill_universe,
    detail_sets_for,
)
from backend.errors import AppError
from backend.providers import canonical_plans as plans
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin_activity_detail_mapping import MAPPER_VERSION
from backend.sync.canonical_ingest import ingest_plan
from backend.sync.garmin_activity_details import (
    BACKFILL_BATCH_SIZE,
    BACKFILL_RATE_LIMIT_PAUSE,
    BACKFILL_RETRY_ATTEMPTS,
    BACKFILL_STATE_KEY,
    BACKFILL_WINDOW,
    GarminActivityDetailService,
)
from backend.sync.garmin_assembly import GarminAssembly
from backend.sync.garmin_service import GarminRemoteReader

NOW_AT = datetime.fromisoformat(NOW)
SINCE = NOW_AT - BACKFILL_WINDOW


def _seed(manager: Any, rows: list[tuple[str, str]]) -> None:
    """Ingest Garmin rides given as (activity id, local start time) pairs."""
    payload = {
        "synced_at": NOW,
        "activities": [
            {
                "activityId": int(activity_id),
                "activityName": "Synthetic ride",
                "activityType": {"typeKey": "cycling"},
                "startTimeLocal": start,
                "distance": 20000.0,
                "duration": 3600.0,
                "averageHR": 140,
                "activityTrainingLoad": 50.0,
            }
            for activity_id, start in rows
        ],
    }
    plan = plans.garmin_ingest_plan(payload, zone=ZONE)
    with manager.unit_of_work() as db:
        ingest_plan(
            db,
            plan,
            retrieved_at=NOW_AT,
            deletion_window=None,
            zone=ZONE,
        )


def _payload(activity_id: str, **extra: Any) -> dict[str, Any]:
    collected = _collected()
    collected["activity_id"] = activity_id
    collected.update(extra)
    return collected


def _partial(activity_id: str, **extra: Any) -> dict[str, Any]:
    """A payload whose splits part failed while the other parts arrived."""
    payload = _payload(activity_id, **extra)
    payload.pop("splits", None)
    payload["errors"] = [{"source": "activity_splits", "message": "synthetic"}]
    return payload


def _summary_hash(manager: Any, activity_id: str) -> str:
    with manager.reader() as db:
        return str(
            db.execute(
                "SELECT payload_hash FROM provider_records "
                "WHERE provider = ? AND record_kind = 'activity' "
                "AND source_record_id = ? AND state = 'active'",
                (GARMIN_ID, activity_id),
            ).fetchone()["payload_hash"]
        )


CHANGED_HASH = hashlib.sha256(b"synthetic changed summary").hexdigest()


def _set_summary_hash(
    manager: Any, activity_id: str, value: str = CHANGED_HASH
) -> None:
    with manager.unit_of_work() as db:
        db.execute(
            "UPDATE provider_records SET payload_hash = ? "
            "WHERE provider = ? AND record_kind = 'activity' AND source_record_id = ?",
            (value, GARMIN_ID, activity_id),
        )


def _candidate_ids(
    manager: Any,
    *,
    limit: int = 100,
    retry_ids: tuple[str, ...] = (),
    mapper_version: int = MAPPER_VERSION,
) -> list[str]:
    with manager.reader() as db:
        rows = activity_detail_backfill_candidates(
            db,
            GARMIN_ID,
            ACTIVITY_RECORD_KIND,
            since=SINCE,
            limit=limit,
            mapper_version=mapper_version,
            retry_ids=retry_ids,
        )
    return [row["provider_activity_id"] for row in rows]


def _stored_kinds(manager: Any, activity_id: str) -> list[str]:
    with manager.reader() as db:
        return sorted(
            item.detail.kind.value
            for item in detail_sets_for(db, GARMIN_ID, activity_id)
        )


class _KeyValues:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, _db: Any, key: str) -> str | None:
        return self.values.get(key)

    def set(self, _db: Any, key: str, value: str) -> None:
        self.values[key] = value


class _Details:
    """Generator-backed reader double that records calls and whether it was closed."""

    def __init__(
        self,
        responses: dict[str, Any],
        *,
        pre_yield: dict[str, Any] | None = None,
    ) -> None:
        self._responses = responses
        self._pre_yield = pre_yield or {}
        self.calls: list[tuple[tuple[str, ...], threading.Event | None]] = []
        self.fetched: list[str] = []
        self.closed = False

    def fetch_activity_details(self, provider_activity_ids, *, cancel_event=None):
        self.calls.append((tuple(provider_activity_ids), cancel_event))
        return self._iterate(list(provider_activity_ids), cancel_event)

    def _iterate(self, ids: list[str], cancel_event: threading.Event | None):
        try:
            for activity_id in ids:
                if cancel_event is not None and cancel_event.is_set():
                    return
                hook = self._pre_yield.get(activity_id)
                if hook is not None:
                    hook()
                self.fetched.append(activity_id)
                payload = self._responses[activity_id]
                if isinstance(payload, BaseException):
                    raise payload
                yield activity_id, payload
        finally:
            self.closed = True


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.key_values = _KeyValues()
        self.now = NOW

    def service(
        self,
        reader: Any,
        *,
        configured: bool = True,
        allowed: Any = None,
    ) -> GarminActivityDetailService:
        return GarminActivityDetailService(
            database_manager=self.manager,
            reader=reader,
            configured=lambda: configured,
            guard=Mock(),
            utc_now=lambda: self.now,
            key_values=self.key_values,
            capability_allowed=allowed or (lambda _capability: True),
        )


def _stored_state(key_values: Any) -> dict[str, Any]:
    raw = key_values.values.get(BACKFILL_STATE_KEY)
    return json.loads(raw) if raw else {}


class BackfillCandidateTests(_Base):
    def test_window_boundary_uses_offset_aware_start_times(self) -> None:
        _seed(
            self.manager,
            [("1001", "2026-07-19 12:00:00"), ("1002", "2026-07-21 12:00:00")],
        )

        self.assertEqual(_candidate_ids(self.manager), ["1002"])
        with self.manager.reader() as db:
            universe = activity_detail_backfill_universe(db, GARMIN_ID, since=SINCE)
        self.assertEqual(universe, ["1002"])

    def test_candidates_are_newest_first(self) -> None:
        _seed(
            self.manager,
            [
                ("1001", "2026-10-01 07:00:00"),
                ("1002", "2026-10-15 07:00:00"),
                ("1003", "2026-10-08 07:00:00"),
            ],
        )

        self.assertEqual(_candidate_ids(self.manager), ["1002", "1003", "1001"])

    def test_limit_caps_the_candidate_list(self) -> None:
        _seed(
            self.manager,
            [
                ("1001", "2026-10-01 07:00:00"),
                ("1002", "2026-10-02 07:00:00"),
                ("1003", "2026-10-03 07:00:00"),
            ],
        )

        self.assertEqual(_candidate_ids(self.manager, limit=2), ["1003", "1002"])

    def test_manual_deleted_and_other_provider_records_are_excluded(self) -> None:
        _seed(
            self.manager,
            [
                ("1001", "2026-10-01 07:00:00"),
                ("1002", "2026-10-02 07:00:00"),
                ("1003", "2026-10-03 07:00:00"),
            ],
        )
        seed_intervals_activity(self.manager, "5550001")
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_records SET recorded_by = ? "
                "WHERE provider = ? AND provider_activity_id = ?",
                (RecordingOrigin.MANUAL.value, GARMIN_ID, "1001"),
            )
            db.execute(
                "UPDATE activity_records SET state = ? "
                "WHERE provider = ? AND provider_activity_id = ?",
                (ActivityRecordState.DELETED.value, GARMIN_ID, "1002"),
            )

        self.assertEqual(_candidate_ids(self.manager), ["1003"])

    def test_activity_with_matching_detail_sets_is_excluded(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        reader = _Details({"1001": _payload("1001")})
        self.service(reader).backfill()
        self.assertEqual(_stored_kinds(self.manager, "1001")[0], "heart_rate_zones")

        self.assertEqual(_candidate_ids(self.manager), [])

    def test_changed_summary_makes_stored_sets_a_candidate_again(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        self.service(_Details({"1001": _payload("1001")})).backfill()
        _set_summary_hash(self.manager, "1001")

        self.assertEqual(_candidate_ids(self.manager), ["1001"])

    def test_sets_from_an_older_mapper_version_are_candidates_again(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        self.service(_Details({"1001": _payload("1001")})).backfill()
        self.assertEqual(_candidate_ids(self.manager), [])

        self.assertEqual(
            _candidate_ids(self.manager, mapper_version=MAPPER_VERSION + 1), ["1001"]
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_detail_sets SET mapper_version = ? "
                "WHERE provider = ? AND provider_activity_id = ?",
                (MAPPER_VERSION - 1, GARMIN_ID, "1001"),
            )
        self.assertEqual(_candidate_ids(self.manager), ["1001"])

    def test_one_set_for_the_current_summary_ends_the_candidacy(self) -> None:
        # A kind Garmin stopped returning keeps its old hash; refetching would loop.
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        self.service(_Details({"1001": _payload("1001")})).backfill()
        _set_summary_hash(self.manager, "1001")
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_detail_sets SET summary_sha256 = ? "
                "WHERE provider = ? AND provider_activity_id = ? AND detail_kind = ?",
                (CHANGED_HASH, GARMIN_ID, "1001", "laps"),
            )

        self.assertEqual(_candidate_ids(self.manager), [])

    def test_retry_ids_keep_an_activity_with_current_sets_a_candidate(self) -> None:
        _seed(
            self.manager,
            [("1001", "2026-10-02 07:00:00"), ("1002", "2026-10-01 07:00:00")],
        )
        self.service(
            _Details({"1001": _payload("1001"), "1002": _payload("1002")})
        ).backfill()

        self.assertEqual(_candidate_ids(self.manager), [])
        self.assertEqual(_candidate_ids(self.manager, retry_ids=("1002",)), ["1002"])

    def test_empty_marked_activity_stays_a_candidate_for_the_query(self) -> None:
        # Empty marks are a Python-side filter; the SQL query keeps the activity.
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])

        self.assertEqual(_candidate_ids(self.manager), ["1001"])


class BackfillBatchTests(_Base):
    def test_batch_is_limited_to_ten_and_reports_remaining(self) -> None:
        rows = [
            (str(1000 + index), f"2026-10-{index + 1:02d} 07:00:00")
            for index in range(12)
        ]
        _seed(self.manager, rows)
        reader = _Details({aid: _payload(aid) for aid, _ in rows})

        result = self.service(reader).backfill()

        self.assertEqual(BACKFILL_BATCH_SIZE, 10)
        self.assertEqual(len(reader.calls), 1)
        ids, _cancel = reader.calls[0]
        self.assertEqual(len(ids), BACKFILL_BATCH_SIZE)
        self.assertEqual(ids[0], "1011")
        self.assertEqual(
            result,
            {"status": "completed", "fetched": 10, "empty": 0, "remaining": 2},
        )
        self.assertEqual(_stored_kinds(self.manager, "1011")[0], "heart_rate_zones")
        self.assertEqual(_stored_kinds(self.manager, "1000"), [])

    def test_empty_activity_is_marked_and_not_refetched_for_the_same_summary(
        self,
    ) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        reader = _Details({"1001": {"activity_id": "1001"}})

        first = self.service(reader).backfill()
        second_reader = _Details({})
        second = self.service(second_reader).backfill()

        self.assertEqual(first["empty"], 1)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(
            _stored_state(self.key_values)["empty"],
            {"1001": _summary_hash(self.manager, "1001")},
        )
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second_reader.calls, [])

    def test_empty_mark_is_retried_when_the_summary_changes(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        self.service(_Details({"1001": {"activity_id": "1001"}})).backfill()
        _set_summary_hash(self.manager, "1001")
        reader = _Details({"1001": _payload("1001")})

        result = self.service(reader).backfill()

        self.assertEqual(result["fetched"], 1)
        self.assertEqual(reader.fetched, ["1001"])

    def test_malformed_only_activity_is_retried_then_passed_over(self) -> None:
        _seed(
            self.manager,
            [("1001", "2026-10-02 07:00:00"), ("1002", "2026-10-01 07:00:00")],
        )
        summary = _summary_hash(self.manager, "1001")
        responses = {
            "1001": {"activity_id": "1001", "hr_zones": "synthetic malformed"},
            "1002": _payload("1002"),
        }
        for _attempt in range(BACKFILL_RETRY_ATTEMPTS):
            reader = _Details(responses)
            result = self.service(reader).backfill()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["empty"], 0)
            self.assertEqual(reader.fetched, ["1001"])

        reader = _Details(responses)
        result = self.service(reader).backfill()

        self.assertEqual(
            result, {"status": "completed", "fetched": 1, "empty": 0, "remaining": 0}
        )
        self.assertEqual(reader.fetched, ["1002"])
        state = _stored_state(self.key_values)
        self.assertEqual(state["empty"], {})
        self.assertEqual(state["retry"], {"1001": [summary, BACKFILL_RETRY_ATTEMPTS]})

    def test_part_dropped_by_the_mapper_is_retried(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        summary = _summary_hash(self.manager, "1001")

        first = self.service(
            _Details({"1001": _payload("1001", hr_zones="synthetic malformed")})
        ).backfill()

        self.assertEqual(first["fetched"], 1)
        self.assertNotIn("heart_rate_zones", _stored_kinds(self.manager, "1001"))
        self.assertEqual(
            _stored_state(self.key_values)["retry"], {"1001": [summary, 1]}
        )

        reader = _Details({"1001": _payload("1001")})
        self.service(reader).backfill()

        self.assertEqual(reader.fetched, ["1001"])
        self.assertIn("heart_rate_zones", _stored_kinds(self.manager, "1001"))
        self.assertNotIn("retry", _stored_state(self.key_values))

    def test_retry_state_is_committed_with_the_detail_rows(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        summary = _summary_hash(self.manager, "1001")
        service = self.service(_Details({"1001": _partial("1001")}))

        # The run stops before its final state write.
        with (
            patch.object(
                service, "_save_backfill_state", side_effect=RuntimeError("stop")
            ),
            self.assertRaises(RuntimeError),
        ):
            service.backfill()

        self.assertIn("heart_rate_zones", _stored_kinds(self.manager, "1001"))
        self.assertEqual(
            _stored_state(self.key_values)["retry"], {"1001": [summary, 1]}
        )
        self.assertEqual(_candidate_ids(self.manager, retry_ids=("1001",)), ["1001"])

    def test_failed_state_write_rolls_back_the_detail_rows(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        original_set = self.key_values.set
        failures = [RuntimeError("synthetic state write failure")]

        def failing_set(db: Any, key: str, value: str) -> None:
            if failures:
                raise failures.pop()
            original_set(db, key, value)

        with patch.object(self.key_values, "set", side_effect=failing_set):
            result = self.service(_Details({"1001": _partial("1001")})).backfill()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(_stored_kinds(self.manager, "1001"), [])
        self.assertNotIn("retry", _stored_state(self.key_values))
        self.assertEqual(_candidate_ids(self.manager), ["1001"])

    def test_rate_limit_keeps_arrived_parts_pauses_and_stops_the_batch(self) -> None:
        _seed(
            self.manager,
            [("1001", "2026-10-02 07:00:00"), ("1002", "2026-10-01 07:00:00")],
        )
        reader = _Details(
            {
                "1001": _payload("1001", rate_limited=True),
                "1002": _payload("1002"),
            }
        )

        result = self.service(reader).backfill()

        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(reader.fetched, ["1001"])
        self.assertTrue(reader.closed)
        self.assertEqual(_stored_kinds(self.manager, "1001")[0], "heart_rate_zones")
        self.assertEqual(_stored_kinds(self.manager, "1002"), [])
        paused = datetime.fromisoformat(_stored_state(self.key_values)["paused_until"])
        self.assertEqual(paused, NOW_AT + BACKFILL_RATE_LIMIT_PAUSE)

    def test_partial_fetch_is_retried_until_it_completes(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        summary = _summary_hash(self.manager, "1001")

        first = self.service(_Details({"1001": _partial("1001")})).backfill()

        self.assertEqual(first["fetched"], 1)
        self.assertEqual(
            _stored_state(self.key_values)["retry"], {"1001": [summary, 1]}
        )
        self.assertNotIn("laps", _stored_kinds(self.manager, "1001"))

        reader = _Details({"1001": _payload("1001")})
        second = self.service(reader).backfill()

        self.assertEqual(reader.fetched, ["1001"])
        self.assertEqual(second["fetched"], 1)
        self.assertNotIn("retry", _stored_state(self.key_values))
        self.assertIn("laps", _stored_kinds(self.manager, "1001"))

    def test_part_skipped_while_paused_is_retried(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        summary = _summary_hash(self.manager, "1001")
        paused = _payload("1001")
        paused.pop("splits")
        paused["skipped"] = ["activity_splits"]

        self.service(_Details({"1001": paused})).backfill()

        self.assertEqual(
            _stored_state(self.key_values)["retry"], {"1001": [summary, 1]}
        )
        reader = _Details({"1001": _payload("1001")})
        self.service(reader).backfill()

        self.assertEqual(reader.fetched, ["1001"])
        self.assertNotIn("retry", _stored_state(self.key_values))

    def test_fully_skipped_activity_is_not_marked_empty(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])

        result = self.service(
            _Details({"1001": {"activity_id": "1001", "skipped": ["activity_details"]}})
        ).backfill()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(_stored_state(self.key_values)["empty"], {})
        self.assertEqual(_candidate_ids(self.manager), ["1001"])

    def test_failing_activity_stops_holding_back_older_ones(self) -> None:
        _seed(
            self.manager,
            [("1002", "2026-10-02 07:00:00"), ("1001", "2026-10-01 07:00:00")],
        )
        summary = _summary_hash(self.manager, "1002")
        failed = {
            "activity_id": "1002",
            "errors": [{"source": "activity_details", "message": "synthetic"}],
        }
        for _attempt in range(BACKFILL_RETRY_ATTEMPTS):
            reader = _Details({"1002": failed, "1001": _payload("1001")})
            result = self.service(reader).backfill()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(reader.fetched, ["1002"])

        reader = _Details({"1002": failed, "1001": _payload("1001")})
        result = self.service(reader).backfill()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(reader.fetched, ["1001"])
        self.assertEqual(
            _stored_state(self.key_values)["retry"],
            {"1002": [summary, BACKFILL_RETRY_ATTEMPTS]},
        )

    def test_rate_limit_without_stored_parts_is_not_an_attempt(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        limited = {
            "activity_id": "1001",
            "errors": [{"source": "activity_details", "message": "synthetic"}],
            "rate_limited": True,
        }

        result = self.service(_Details({"1001": limited})).backfill()

        self.assertEqual(result["status"], "rate_limited")
        self.assertNotIn("retry", _stored_state(self.key_values))

    def test_partial_fetch_retries_are_bounded_per_summary(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        summary = _summary_hash(self.manager, "1001")
        for _attempt in range(BACKFILL_RETRY_ATTEMPTS):
            self.service(_Details({"1001": _partial("1001")})).backfill()

        reader = _Details({"1001": _partial("1001")})
        result = self.service(reader).backfill()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(reader.calls, [])
        self.assertEqual(
            _stored_state(self.key_values)["retry"],
            {"1001": [summary, BACKFILL_RETRY_ATTEMPTS]},
        )

        # A changed summary makes the stored sets outdated and restarts the count.
        _set_summary_hash(self.manager, "1001")
        reader = _Details({"1001": _partial("1001")})
        self.service(reader).backfill()

        self.assertEqual(reader.fetched, ["1001"])
        self.assertEqual(
            _stored_state(self.key_values)["retry"], {"1001": [CHANGED_HASH, 1]}
        )

    def test_rate_limited_partial_fetch_is_retried_after_the_pause(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])

        self.service(_Details({"1001": _partial("1001", rate_limited=True)})).backfill()
        self.now = (
            NOW_AT + BACKFILL_RATE_LIMIT_PAUSE + timedelta(minutes=1)
        ).isoformat()
        reader = _Details({"1001": _payload("1001")})
        result = self.service(reader).backfill()

        self.assertEqual(reader.fetched, ["1001"])
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("retry", _stored_state(self.key_values))

    def test_rate_limit_exception_pauses_without_failing(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        reader = _Details({"1001": AppError(429, "synthetic", reason="garmin_429")})

        result = self.service(reader).backfill()

        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(result["fetched"], 0)
        self.assertTrue(reader.closed)
        self.assertEqual(
            datetime.fromisoformat(_stored_state(self.key_values)["paused_until"]),
            NOW_AT + BACKFILL_RATE_LIMIT_PAUSE,
        )

    def test_pause_blocks_remote_calls_until_it_expires(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        paused_until = NOW_AT + timedelta(hours=1)
        self.key_values.values[BACKFILL_STATE_KEY] = json.dumps(
            {"empty": {}, "paused_until": paused_until.isoformat()}, sort_keys=True
        )
        reader = _Details({"1001": _payload("1001")})

        paused = self.service(reader).backfill()

        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["remaining"], 1)
        self.assertEqual(reader.calls, [])
        self.assertEqual(
            datetime.fromisoformat(_stored_state(self.key_values)["paused_until"]),
            paused_until,
        )

        self.now = (NOW_AT + timedelta(hours=2)).isoformat()
        resumed = self.service(reader).backfill()

        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["fetched"], 1)
        self.assertNotIn("paused_until", _stored_state(self.key_values))

    def test_unavailable_detail_capability_gives_no_remote_call(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        reader = _Details({"1001": _payload("1001")})

        result = self.service(
            reader, allowed=lambda capability: capability != "activity_splits"
        ).backfill()

        self.assertEqual(result["status"], "paused")
        self.assertEqual(reader.calls, [])

    def test_all_parts_failing_stops_without_marking(self) -> None:
        _seed(
            self.manager,
            [("1001", "2026-10-02 07:00:00"), ("1002", "2026-10-01 07:00:00")],
        )
        reader = _Details(
            {
                "1001": {
                    "activity_id": "1001",
                    "errors": [{"source": "activity_details", "message": "synthetic"}],
                },
                "1002": _payload("1002"),
            }
        )

        result = self.service(reader).backfill()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["empty"], 0)
        self.assertEqual(reader.fetched, ["1001"])
        self.assertEqual(_stored_state(self.key_values).get("empty", {}), {})
        self.assertEqual(_stored_kinds(self.manager, "1001"), [])

    def test_unexpected_error_is_logged_by_type_only(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        reader = _Details({"1001": RuntimeError("PRIVATE-PROVIDER-TEXT")})

        with self.assertLogs("backend.sync.garmin_activity_details", "WARNING") as logs:
            result = self.service(reader).backfill()

        self.assertEqual(result["status"], "failed")
        self.assertTrue(reader.closed)
        self.assertEqual(getattr(logs.records[0], "error_type", None), "RuntimeError")
        joined = str(logs.output) + str(result)
        self.assertNotIn("PRIVATE-PROVIDER-TEXT", joined)

    def test_cancel_between_activities_stops_the_batch(self) -> None:
        _seed(
            self.manager,
            [("1001", "2026-10-02 07:00:00"), ("1002", "2026-10-01 07:00:00")],
        )
        cancel = threading.Event()
        reader = _Details(
            {"1001": _payload("1001"), "1002": _payload("1002")},
            pre_yield={"1001": cancel.set},
        )

        result = self.service(reader).backfill(cancel_event=cancel)

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(reader.fetched, ["1001"])
        self.assertIs(reader.calls[0][1], cancel)
        self.assertTrue(reader.closed)

    def test_unconfigured_garmin_gives_not_configured_without_reader_call(self) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        reader = _Details({"1001": _payload("1001")})

        result = self.service(reader, configured=False).backfill()

        self.assertEqual(result["status"], "not_configured")
        self.assertEqual(reader.calls, [])

    def test_empty_window_completes_without_reader_call(self) -> None:
        reader = _Details({})

        result = self.service(reader).backfill()

        self.assertEqual(
            result, {"status": "completed", "fetched": 0, "empty": 0, "remaining": 0}
        )
        self.assertEqual(reader.calls, [])


class BackfillAssemblyTests(unittest.TestCase):
    def test_sync_service_runs_the_backfill_of_the_composed_detail_service(
        self,
    ) -> None:
        control: Any = Mock(name="control")
        control.resync_gate = None
        assembly = GarminAssembly(
            dependencies=GarminAssembly.Inputs(
                provider=Mock(name="provider"),
                persistence=Mock(name="persistence"),
                telemetry=Mock(name="telemetry"),
                control=control,
            )
        )
        state = Mock(name="state")
        with patch.object(assembly, "sync_state_service", return_value=state):
            detail_service = assembly.activity_detail_service()
            with patch.object(
                assembly, "activity_detail_service", return_value=detail_service
            ):
                sync_service = assembly.sync_service()

        self.assertIs(detail_service._capability_allowed, state.capability_allowed)
        self.assertIsNotNone(detail_service._key_values)
        self.assertEqual(
            sync_service._activity_detail_backfill, detail_service.backfill
        )


def _real_reader(garmin_tokens: Any, factory: Any) -> GarminRemoteReader:
    return GarminRemoteReader(
        make_config(
            openai_base_url="",
            openai_model="",
            intervals_athlete_id="",
            data_retention_days=30,
            garmin_email="athlete@example.invalid",
            garmin_password="secret",
            garmin_tokenstore="missing-tokenstore",
        ),
        factory,
        Mock(),
        Mock(),
        lambda value: value,
        Mock(),
        lambda: NOW,
        lambda: date(2026, 10, 18),
        date(2000, 1, 1),
        90,
        -1,
        garmin_tokens=garmin_tokens,
    )


class BackfillReaderLifecycleTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.client = Mock()
        self.client.login.return_value = (False, None)
        self.factory = Mock()
        self.factory.available.return_value = True
        self.factory.create.return_value = self.client
        self.tokens = Mock()
        self.tokens.login_argument.return_value = '{"di_token": "synthetic"}'

    def _run(self, collect: Any, *, cancel: threading.Event | None = None):
        reader = _real_reader(self.tokens, self.factory)
        service = self.service(reader)
        with (
            patch(
                "backend.sync.garmin_service.provider_http.external_call",
                side_effect=lambda _service, _operation, call, _details, **_kwargs: (
                    call()
                ),
            ),
            patch(
                "backend.sync.garmin_service.collect_garmin_activity_detail",
                side_effect=collect,
            ) as collector,
        ):
            result = service.backfill(cancel_event=cancel)
        return result, collector

    def test_one_authentication_and_token_write_back_serve_the_whole_batch(
        self,
    ) -> None:
        _seed(
            self.manager,
            [("1001", "2026-10-02 07:00:00"), ("1002", "2026-10-01 07:00:00")],
        )

        def collect(_client, activity_id, **_kwargs):
            return _payload(activity_id)

        result, collector = self._run(collect)

        self.assertEqual(result["fetched"], 2)
        self.assertEqual(collector.call_count, 2)
        self.factory.create.assert_called_once()
        self.client.login.assert_called_once_with('{"di_token": "synthetic"}')
        self.tokens.write_back.assert_called_once_with(
            self.client, '{"di_token": "synthetic"}'
        )

    def test_tokens_are_persisted_when_the_batch_stops_early(self) -> None:
        _seed(
            self.manager,
            [("1001", "2026-10-02 07:00:00"), ("1002", "2026-10-01 07:00:00")],
        )
        cancel = threading.Event()

        def collect(_client, activity_id, **_kwargs):
            cancel.set()
            return _payload(activity_id)

        result, collector = self._run(collect, cancel=cancel)

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(collector.call_count, 1)
        self.tokens.write_back.assert_called_once_with(
            self.client, '{"di_token": "synthetic"}'
        )

    def test_reported_429_on_one_activity_pauses_the_batch(self) -> None:
        _seed(
            self.manager,
            [("1001", "2026-10-02 07:00:00"), ("1002", "2026-10-01 07:00:00")],
        )

        def collect(_client, activity_id, **kwargs):
            if activity_id == "1001":
                kwargs["capability_failure"](
                    "activity_details", AppError(429, "synthetic")
                )
            return _payload(activity_id)

        result, collector = self._run(collect)

        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(collector.call_count, 1)
        self.assertEqual(
            datetime.fromisoformat(_stored_state(self.key_values)["paused_until"]),
            NOW_AT + BACKFILL_RATE_LIMIT_PAUSE,
        )
        self.tokens.write_back.assert_called_once()

    def test_429_on_one_part_skips_the_remaining_parts_of_the_activity(
        self,
    ) -> None:
        _seed(self.manager, [("1001", "2026-10-01 07:00:00")])
        self.client.get_activity_details.side_effect = AppError(429, "synthetic")
        reader = _real_reader(self.tokens, self.factory)

        with patch(
            "backend.sync.garmin_service.provider_http.external_call",
            side_effect=lambda _service, _operation, call, _details, **_kwargs: call(),
        ):
            result = self.service(reader).backfill()

        self.assertEqual(result["status"], "rate_limited")
        self.client.get_activity_details.assert_called_once()
        self.client.get_activity_splits.assert_not_called()
        self.client.get_activity_hr_in_timezones.assert_not_called()
        self.client.get_activity_power_in_timezones.assert_not_called()


if __name__ == "__main__":
    unittest.main()
