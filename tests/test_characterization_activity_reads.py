"""Characterize activity pagination, recent reads and analysis fingerprints.

These tests pin current behaviour, quirks included, as the parity reference for
the provider-neutral refactor. Storage is a temporary SQLite key/value table and
providers are in-memory fakes; no server, network or real athlete data is used.
"""

import base64
import builtins
import json
import sqlite3
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import closing, contextmanager, nullcontext
from datetime import date
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
from backend.activities.read_service import PAGE_DEFAULT, PAGE_MAX, ActivityReadService
from backend.db.manager import DatabaseManager
from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService
from backend.performance.activity_read_service import ActivityAnalysisReadService
from backend.performance.report_service import TrainingRecordsService
from backend.planning import calendar_read_model
from backend.planning import season as planning_season

TODAY = date(2026, 5, 4)
DAY = "2026-05-04T08:00:00"
PREVIOUS_DAY = "2026-05-03T08:00:00"


class _Database:
    """Minimal unit-of-work manager over a temporary SQLite key/value table."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )

    @contextmanager
    def unit_of_work(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            yield db


class _Snapshots:
    def __init__(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    def latest_snapshot(self, _db: Any) -> Any:
        return self._snapshot


class _Feedback:
    """Simplified feedback attachment: copies dict rows and drops everything else.

    Matches on id only; the production fallback to activityId/external_id is not
    exercised here.
    """

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def list(self, _limit: int = 100) -> builtins.list[dict[str, Any]]:
        return self._rows

    def attach_to_activities(
        self, activities: builtins.list[Any]
    ) -> builtins.list[dict[str, Any]]:
        by_id = {str(row["activity_id"]): row for row in self._rows}
        attached = []
        for item in activities:
            if not isinstance(item, dict):
                continue
            copy = dict(item)
            key = str(item.get("id"))
            if key in by_id:
                copy["activity_feedback"] = by_id[key]
            attached.append(copy)
        return attached


class _StorageCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = _Database(Path(directory.name) / "fixture.sqlite")


def _activity(activity_id: Any, start: str = DAY, **fields: Any) -> dict[str, Any]:
    return {
        "id": activity_id,
        "start_date_local": start,
        "type": "Ride",
        "moving_time": 3600,
        **fields,
    }


def _snapshot(activities: Any, raw: Any = None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "synced_at": "2026-05-04T06:00:00+00:00",
        "athlete": {},
        "recent_wellness": [],
        "recent_activities": activities,
    }
    if raw is not None:
        snapshot["raw_provider_data"] = {"activities": raw}
    return snapshot


def _encode(value: Any) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(cursor: str) -> Any:
    padded = cursor + "=" * (-len(cursor) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _ids(rows: list[dict[str, Any]]) -> list[Any]:
    return [row["id"] for row in rows]


class ActivityPageCharacterizationTests(_StorageCase):
    def _page(self, activities: Any, **kwargs: Any) -> dict[str, Any]:
        service = ActivityReadService(
            self.database, _Snapshots(_snapshot(activities)), _Feedback()
        )
        return service.page(today=TODAY, **kwargs)

    def test_cursor_is_unpadded_urlsafe_json_of_last_page_key(self) -> None:
        # The 28-byte payload needs base64 padding, so the unpadded form is pinned.
        result = self._page(
            [_activity("bc", DAY), _activity("a", PREVIOUS_DAY)], limit=1
        )
        self.assertEqual(["bc"], _ids(result["activities"]))
        self.assertEqual(
            "WyIyMDI2LTA1LTA0VDA4OjAwOjAwIiwiYmMiXQ", result["next_cursor"]
        )
        self.assertEqual([DAY, "bc"], _decode(result["next_cursor"]))

    def test_cursor_round_trips_non_ascii_ids(self) -> None:
        result = self._page(
            [_activity("Rad-Ä", DAY), _activity("a", PREVIOUS_DAY)], limit=1
        )
        self.assertEqual(
            "WyIyMDI2LTA1LTA0VDA4OjAwOjAwIiwiUmFkLcOEIl0", result["next_cursor"]
        )
        self.assertEqual([DAY, "Rad-Ä"], _decode(result["next_cursor"]))

    def test_cursor_skips_rows_whose_sort_key_equals_the_cursor_key(self) -> None:
        # Quirk pinned: resumption is strictly "less than" the cursor key, so a
        # second row with the same date and id is never returned.
        rows = [_activity("dup", DAY), _activity("dup", DAY)]
        first = self._page(rows, limit=1)
        second = self._page(rows, cursor=first["next_cursor"], limit=1)
        self.assertEqual(1, len(first["activities"]))
        self.assertEqual([], second["activities"])
        self.assertIsNone(second["next_cursor"])

    def test_last_page_has_no_cursor(self) -> None:
        result = self._page([_activity("only", DAY)], limit=1)
        self.assertIsNone(result["next_cursor"])
        self.assertEqual(1, result["limit"])

    def test_cursor_resumes_strictly_after_encoded_key(self) -> None:
        rows = [
            _activity("c", DAY),
            _activity("b", DAY),
            _activity("a", PREVIOUS_DAY),
        ]
        first = self._page(rows, limit=1)
        second = self._page(rows, cursor=first["next_cursor"], limit=1)
        third = self._page(rows, cursor=second["next_cursor"], limit=1)
        self.assertEqual(["c"], _ids(first["activities"]))
        self.assertEqual(["b"], _ids(second["activities"]))
        self.assertEqual(["a"], _ids(third["activities"]))
        self.assertIsNone(third["next_cursor"])

    def test_ties_on_start_date_are_ordered_by_id_descending(self) -> None:
        result = self._page(
            [_activity("a", DAY), _activity("c", DAY), _activity("b", DAY)]
        )
        self.assertEqual(["c", "b", "a"], _ids(result["activities"]))

    def test_numeric_ids_are_compared_as_strings(self) -> None:
        # Quirk pinned: "9" sorts after "10" because keys are str(id).
        result = self._page([_activity(10, DAY), _activity(9, DAY)])
        self.assertEqual([9, 10], _ids(result["activities"]))

    def test_sort_key_falls_back_through_date_and_id_fields(self) -> None:
        rows = [
            {"external_id": "ext-only", "start_date_local": PREVIOUS_DAY},
            {"activityId": "from-activity-id", "date": "2026-05-04"},
            {"id": "empty-local", "start_date_local": "", "start_date": DAY},
        ]
        result = self._page(rows)
        self.assertEqual([rows[2], rows[1], rows[0]], result["activities"])

    def test_sort_key_date_is_truncated_to_forty_characters(self) -> None:
        # Quirk pinned: only the first 40 characters of the start string sort.
        long_start = DAY + ".000000000000000000000000000000+00:00"
        result = self._page(
            [_activity("a", long_start), _activity("b", long_start)], limit=1
        )
        self.assertEqual(long_start[:40], _decode(result["next_cursor"])[0])

    def test_malformed_or_unexpected_cursors_restart_from_first_page(self) -> None:
        rows = [_activity("b", DAY), _activity("a", PREVIOUS_DAY)]
        for cursor in (
            "not-a-cursor!!",
            _encode({"key": 1}),
            _encode([DAY]),
            _encode([DAY, "b", "extra"]),
        ):
            with self.subTest(cursor=cursor):
                result = self._page(rows, cursor=cursor, limit=1)
                self.assertEqual(["b"], _ids(result["activities"]))

    def test_limit_is_clamped_and_reported(self) -> None:
        rows = [_activity(f"a{index:03d}", DAY) for index in range(260)]
        for raw, expected in (
            (None, PAGE_DEFAULT),
            ("abc", PAGE_DEFAULT),
            (0, 1),
            (-3, 1),
            ("7", 7),
            (2.9, 2),
            (1000, PAGE_MAX),
        ):
            with self.subTest(limit=raw):
                result = self._page(rows, limit=raw)
                self.assertEqual(expected, result["limit"])
                self.assertEqual(expected, len(result["activities"]))
                self.assertIsNotNone(result["next_cursor"])

    def test_days_filter_uses_inclusive_window_and_echoes_value(self) -> None:
        rows = [
            _activity("today", DAY),
            _activity("yesterday", PREVIOUS_DAY),
            _activity("two-days", "2026-05-02T08:00:00"),
            _activity("undated", ""),
        ]
        cases = (
            (None, ["today", "yesterday", "two-days", "undated"], -1),
            ("abc", ["today", "yesterday", "two-days", "undated"], -1),
            (-1, ["today", "yesterday", "two-days", "undated"], -1),
            (0, ["today"], 0),
            (1, ["today"], 1),
            (2, ["today", "yesterday"], 2),
            # Quirk pinned: any negative value other than -1 is clamped to one day.
            (-5, ["today"], -5),
        )
        for days, expected_ids, echoed in cases:
            with self.subTest(days=days):
                result = self._page(rows, days=days)
                self.assertEqual(expected_ids, _ids(result["activities"]))
                self.assertEqual(echoed, result["days"])

    def test_days_filter_compares_utc_date_of_offset_timestamps(self) -> None:
        # Quirk pinned (suspected defect, reported in the PR): days cutoffs convert
        # offset timestamps to UTC, so 00:30 at +02:00 falls on the previous day.
        # training-records observations() date the same row by its local prefix.
        rows = [_activity("late-local", "2026-05-04T00:30:00+02:00")]
        self.assertEqual([], _ids(self._page(rows, days=1)["activities"]))
        self.assertEqual(["late-local"], _ids(self._page(rows)["activities"]))

    def test_non_dict_rows_are_skipped_before_paging(self) -> None:
        result = self._page(["junk", None, _activity("only", DAY)], limit=5)
        self.assertEqual(["only"], _ids(result["activities"]))
        self.assertIsNone(result["next_cursor"])

    def test_missing_snapshot_returns_empty_page(self) -> None:
        service = ActivityReadService(self.database, _Snapshots(None), _Feedback())
        result = service.page(today=TODAY)
        self.assertEqual([], result["activities"])
        self.assertIsNone(result["snapshot_synced_at"])
        self.assertIsNone(result["next_cursor"])

    def test_non_list_recent_activities_is_treated_as_empty(self) -> None:
        result = self._page("not-a-list")
        self.assertEqual([], result["activities"])
        self.assertIsNone(result["next_cursor"])


class ActivityRecentCharacterizationTests(_StorageCase):
    def _recent(self, activities: Any, **kwargs: Any) -> dict[str, Any]:
        service = ActivityReadService(
            self.database, _Snapshots(_snapshot(activities)), _Feedback()
        )
        return service.recent(today=TODAY, **kwargs)

    def test_recent_keeps_snapshot_order_without_sorting(self) -> None:
        result = self._recent(
            [_activity("older", PREVIOUS_DAY), _activity("newer", DAY)]
        )
        self.assertEqual(["older", "newer"], _ids(result["activities"]))

    def test_recent_default_limit_is_250_and_maximum_is_500(self) -> None:
        rows = [_activity(f"a{index:03d}", DAY) for index in range(600)]
        self.assertEqual(250, len(self._recent(rows)["activities"]))
        self.assertEqual(500, len(self._recent(rows, limit=600)["activities"]))
        self.assertEqual(500, len(self._recent(rows, limit=10_000)["activities"]))

    def test_recent_clamps_low_limits_to_one(self) -> None:
        rows = [_activity("a", DAY), _activity("b", DAY)]
        self.assertEqual(1, len(self._recent(rows, limit=0)["activities"]))
        self.assertEqual(1, len(self._recent(rows, limit=-1)["activities"]))

    def test_non_dict_rows_consume_limit_before_being_dropped(self) -> None:
        # Quirk pinned: without a days filter, the slice happens before non-dict
        # rows are dropped by feedback attachment, so "junk" uses up the budget.
        rows = ["junk", _activity("a", DAY), _activity("b", DAY)]
        self.assertEqual(["a"], _ids(self._recent(rows, limit=2)["activities"]))
        self.assertEqual(["a", "b"], _ids(self._recent(rows, limit=3)["activities"]))

    def test_days_filter_drops_non_dict_rows_before_limit(self) -> None:
        rows = ["junk", _activity("today", DAY)]
        result = self._recent(rows, days=1, limit=1)
        self.assertEqual(["today"], _ids(result["activities"]))
        self.assertEqual(1, result["days"])

    def test_days_zero_returns_nothing_because_cutoff_is_tomorrow(self) -> None:
        # Quirk pinned: recent() does not clamp days, unlike page(); days=0 gives
        # a cutoff of tomorrow and therefore an empty list.
        result = self._recent([_activity("today", DAY)], days=0)
        self.assertEqual([], result["activities"])
        self.assertEqual(0, result["days"])


BASE_SUMMARY: dict[str, Any] = {
    "start_date_local": DAY,
    "name": "Threshold",
    "type": "Ride",
    "moving_time": 3600,
}


class ActivitySummaryFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_a_sha256_hex_digest(self) -> None:
        digest = summary_fingerprint(BASE_SUMMARY)
        self.assertEqual(64, len(digest))
        int(digest, 16)

    def test_fingerprint_ignores_provider_id_and_source(self) -> None:
        first = {**BASE_SUMMARY, "id": "ride-1", "source": "Intervals.icu"}
        second = {**BASE_SUMMARY, "id": "ride-2", "source": "Garmin"}
        self.assertEqual(summary_fingerprint(first), summary_fingerprint(second))

    def test_fingerprint_changes_when_a_detail_field_changes(self) -> None:
        original = summary_fingerprint(BASE_SUMMARY)
        self.assertNotEqual(
            original, summary_fingerprint({**BASE_SUMMARY, "moving_time": 3601})
        )
        self.assertNotEqual(
            original, summary_fingerprint({**BASE_SUMMARY, "name": "Other"})
        )

    def test_fingerprint_ignores_streams_and_laps(self) -> None:
        with_detail = {
            **BASE_SUMMARY,
            "streams": {"watts": [200, 210]},
            "laps": [{"name": "Lap 1", "moving_time": 600}],
        }
        changed_detail = {
            **BASE_SUMMARY,
            "streams": {"watts": [1, 2, 3]},
            "laps": [],
        }
        self.assertEqual(
            summary_fingerprint(BASE_SUMMARY), summary_fingerprint(with_detail)
        )
        self.assertEqual(
            summary_fingerprint(BASE_SUMMARY), summary_fingerprint(changed_detail)
        )

    def test_fingerprint_ignores_fields_outside_the_detail_projection(self) -> None:
        extra = {
            **BASE_SUMMARY,
            "private_field": "excluded",
            "description": "not projected",
            "activity_feedback": {"notes": "ignored"},
        }
        self.assertEqual(summary_fingerprint(BASE_SUMMARY), summary_fingerprint(extra))

    def test_non_finite_numbers_count_as_absent(self) -> None:
        # Quirk pinned: NaN is projected to None and then omitted entirely.
        without = {"name": "Threshold"}
        with_nan = {"name": "Threshold", "moving_time": float("nan")}
        self.assertEqual(summary_fingerprint(without), summary_fingerprint(with_nan))

    def test_fingerprint_does_not_depend_on_input_key_order(self) -> None:
        reordered = dict(reversed(list(BASE_SUMMARY.items())))
        self.assertEqual(
            summary_fingerprint(BASE_SUMMARY), summary_fingerprint(reordered)
        )

    def test_integer_and_float_values_fingerprint_differently(self) -> None:
        # Quirk pinned: JSON serialisation keeps 3600 and 3600.0 distinct.
        self.assertNotEqual(
            summary_fingerprint({"moving_time": 3600}),
            summary_fingerprint({"moving_time": 3600.0}),
        )

    def test_name_is_only_fingerprinted_up_to_500_characters(self) -> None:
        # Quirk pinned: the projection truncates names at 500 characters.
        prefix = "x" * 500
        self.assertEqual(
            summary_fingerprint({"name": prefix + "a"}),
            summary_fingerprint({"name": prefix + "b"}),
        )


class ActivityDetailStalenessCharacterizationTests(_StorageCase):
    RAW = _activity("ride-1", DAY, name="Threshold", moving_time=3600)

    def _detail(self, raw: list[dict[str, Any]]) -> dict[str, Any]:
        service = ActivityAnalysisReadService(
            self.database,
            _Snapshots(_snapshot([], raw)),
            _Feedback(),
            ActivityDetailStore(self.database),
        )
        return service.detail("ride-1", garmin_snapshot={}, profile={}, today=TODAY)

    def _save_analysis(self, **overrides: Any) -> None:
        record: dict[str, Any] = {
            "activity_id": "ride-1",
            "activity": {"name": "Threshold", "moving_time": 3600},
            "source": "Intervals.icu",
            "observed_at": "2026-05-04T06:00:00Z",
            "summary_sha256": summary_fingerprint(self.RAW),
            "full_resolution": True,
            "content_sha256": "0" * 64,
            "available_streams": ["time", "watts"],
            "coverage": {"watts": {"points": 2, "valid_points": 2}},
            "session_analysis": {"aerobic": {"status": "ok"}},
            "target_snapshot": None,
            **overrides,
        }
        ActivityDetailStore(self.database).save("ride-1", record)

    def test_fresh_record_returns_cached_analysis_with_provenance(self) -> None:
        self._save_analysis()
        result = self._detail([self.RAW])
        self.assertEqual({"aerobic": {"status": "ok"}}, result["session_analysis"])
        metadata = result["detail_data"]
        self.assertFalse(metadata["stale"])
        self.assertTrue(metadata["full_resolution"])
        self.assertEqual("2026-05-04T06:00:00Z", metadata["observed_at"])
        self.assertEqual(["time", "watts"], metadata["available_streams"])
        self.assertEqual("Intervals.icu", metadata["source"])

    def test_changed_provider_summary_marks_record_stale_and_hides_analysis(
        self,
    ) -> None:
        self._save_analysis()
        changed = {**self.RAW, "moving_time": 3700}
        result = self._detail([changed])
        self.assertTrue(result["detail_data"]["stale"])
        self.assertEqual({}, result["session_analysis"])
        # Quirk pinned: the cached activity overlays the fresh provider row, so the
        # stale cached value (3600) is still shown.
        self.assertEqual(3600, result["activity"]["moving_time"])
        self.assertTrue(result["detail_data"]["full_resolution"])

    def test_record_without_fingerprint_is_never_stale(self) -> None:
        # Quirk pinned: a falsy summary_sha256 disables the staleness check.
        self._save_analysis(summary_sha256=None)
        result = self._detail([{**self.RAW, "moving_time": 9999}])
        self.assertFalse(result["detail_data"]["stale"])
        self.assertEqual({"aerobic": {"status": "ok"}}, result["session_analysis"])

    def test_missing_record_reports_no_provenance(self) -> None:
        result = self._detail([self.RAW])
        self.assertFalse(result["detail_data"]["stale"])
        self.assertFalse(result["detail_data"]["full_resolution"])
        self.assertIsNone(result["detail_data"]["observed_at"])
        self.assertIsNone(result["detail_data"]["content_sha256"])
        self.assertEqual([], result["detail_data"]["available_streams"])
        self.assertEqual({}, result["session_analysis"])


class TrainingRecordObservationCharacterizationTests(_StorageCase):
    OK_RIDE = _activity(
        "ride-ok",
        DAY,
        name="Threshold",
        device_name="Wahoo ELEMNT",
        moving_time=3600,
    )
    STALE_RIDE = _activity("ride-stale", PREVIOUS_DAY, name="Endurance")

    def _observations(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        service = TrainingRecordsService(
            database_manager=self.database,
            read_snapshot=lambda: _snapshot(raw, raw),
            read_equipment=dict,
            read_record=None,
        )
        return service.observations()

    def _save_analysis(
        self, activity_id: str, fingerprint: str | None, aerobic: Any = None
    ) -> None:
        ActivityDetailStore(self.database).save(
            activity_id,
            {
                "activity_id": activity_id,
                "activity": {},
                "source": "Intervals.icu",
                "observed_at": "2026-05-04T06:00:00Z",
                "summary_sha256": fingerprint,
                "session_analysis": {"aerobic": aerobic},
            },
        )

    def test_observations_skip_entries_whose_fingerprint_does_not_match(self) -> None:
        self._save_analysis(
            "ride-ok", summary_fingerprint(self.OK_RIDE), {"status": "ok"}
        )
        self._save_analysis(
            "ride-stale",
            summary_fingerprint({**self.STALE_RIDE, "moving_time": 1800}),
            {"status": "ok"},
        )
        records = self._observations([self.OK_RIDE, self.STALE_RIDE])
        self.assertEqual(["ride-ok"], [record["activity_id"] for record in records])

    def test_matching_observation_carries_snapshot_fields(self) -> None:
        self._save_analysis(
            "ride-ok", summary_fingerprint(self.OK_RIDE), {"status": "ok"}
        )
        (record,) = self._observations([self.OK_RIDE])
        self.assertEqual("2026-05-04", record["date"])
        self.assertEqual("Ride", record["sport"])
        self.assertEqual(3600, record["duration"])
        self.assertEqual("Wahoo ELEMNT", record["device"])
        self.assertEqual("Intervals.icu", record["source"])
        self.assertEqual({"status": "ok"}, record["aerobic"])

    def test_observations_skip_unknown_activities_and_missing_aerobic(self) -> None:
        self._save_analysis("ride-gone", "0" * 64, {"status": "ok"})
        self._save_analysis(
            "ride-stale",
            summary_fingerprint(self.STALE_RIDE),
            None,
        )
        self.assertEqual([], self._observations([self.STALE_RIDE]))

    def test_observations_skip_records_without_a_fingerprint(self) -> None:
        # Quirk pinned: observations() requires an exact fingerprint match, so a
        # record without one is excluded, while activity detail treats the same
        # record as not stale.
        self._save_analysis("ride-ok", None, {"status": "ok"})
        self.assertEqual([], self._observations([self.OK_RIDE]))

    def test_observations_are_sorted_newest_first(self) -> None:
        self._save_analysis(
            "ride-ok", summary_fingerprint(self.OK_RIDE), {"status": "ok"}
        )
        self._save_analysis(
            "ride-stale",
            summary_fingerprint(self.STALE_RIDE),
            {"status": "insufficient"},
        )
        records = self._observations([self.STALE_RIDE, self.OK_RIDE])
        self.assertEqual(["ride-ok", "ride-stale"], [r["activity_id"] for r in records])


class PublicPlanCompactRowFingerprintCharacterizationTests(_StorageCase):
    RAW = _activity("ride-1", DAY, name="Threshold", average_heartrate=150)
    COMPACT_MATCHING = _activity("ride-1", DAY, name="Threshold", average_heartrate=150)
    COMPACT_LEAN = _activity("ride-1", DAY, name="Threshold")

    def _save_profile(self) -> None:
        ActivityDetailStore(self.database).save(
            "ride-1",
            {
                "activity_id": "ride-1",
                "activity": {
                    "streams": {
                        "time": list(range(3600)),
                        "watts": [200] * 3600,
                    }
                },
                "source": "Intervals.icu",
                "observed_at": "2026-05-04T06:00:00Z",
                "summary_sha256": summary_fingerprint(self.RAW),
                "session_analysis": {"aerobic": {"status": "ok"}},
            },
        )

    def _plan_service(self, snapshot: dict[str, Any]) -> PublicPlanStateService:
        return PublicPlanStateService(
            PublicPlanDependencies(
                sync_state=Mock(latest_snapshot=Mock(return_value=snapshot)),
                planned_units=Mock(list=Mock(return_value=[])),
                activity_feedback=Mock(attach_to_activities=lambda rows: list(rows)),
                weather=Mock(state=Mock(return_value={})),
                adaptive_followup=Mock(),
                database_manager_factory=lambda: cast(DatabaseManager, self.database),
                db_lock=nullcontext(),
                key_values=Mock(get=Mock(return_value=None)),
                training_plans=Mock(list=Mock(return_value=[])),
                external_calendar=Mock(
                    list_events=Mock(return_value=[]),
                    list_events_in_window=Mock(return_value=[]),
                    state=Mock(return_value={}),
                ),
                external_calendar_sync=Mock(running=Mock(return_value=False)),
                daily_context=Mock(build=Mock(return_value={})),
                checkins=Mock(list=Mock(return_value=[])),
                competitions=Mock(list=Mock(return_value=[])),
                adaptive_preview=Mock(
                    latest_preview=Mock(return_value=None),
                    status=Mock(return_value={}),
                ),
                coach_quick_actions=Mock(state=Mock(return_value={})),
                today=lambda: TODAY,
                external_calendar_configured=False,
                external_calendar_window_days=14,
                default_workout_name="Workout",
            )
        )

    def _planning_activities(self, compact: list[dict[str, Any]]) -> list[Any]:
        snapshot = _snapshot(compact, [self.RAW])
        captured: list[Any] = []

        def capture(*args: Any, **_kwargs: Any) -> dict[str, Any]:
            captured.append(args[1])
            return {}

        with (
            patch.object(
                calendar_read_model, "project_planning_calendar", side_effect=capture
            ),
            patch.object(planning_season, "planning_state", return_value={}),
        ):
            self._plan_service(snapshot).read()
        return captured[0]

    def test_compact_row_with_matching_projection_gets_recorded_profile(self) -> None:
        self._save_profile()
        (row,) = self._planning_activities([self.COMPACT_MATCHING])
        self.assertEqual("recorded", row["workout_profile"]["source"])

    def test_compact_row_missing_a_raw_field_hides_profile_while_detail_is_fresh(
        self,
    ) -> None:
        # Quirk pinned: the public plan fingerprints the compact recent_activities
        # row, while detail staleness fingerprints raw_provider_data. A compact row
        # that omits a projected field therefore drops the profile even though the
        # stored record is fresh against the raw provider row.
        self._save_profile()
        (row,) = self._planning_activities([self.COMPACT_LEAN])
        self.assertNotIn("workout_profile", row)
        detail = ActivityAnalysisReadService(
            self.database,
            _Snapshots(_snapshot([self.COMPACT_LEAN], [self.RAW])),
            _Feedback(),
            ActivityDetailStore(self.database),
        ).detail("ride-1", garmin_snapshot={}, profile={}, today=TODAY)
        self.assertFalse(detail["detail_data"]["stale"])


if __name__ == "__main__":
    unittest.main()
