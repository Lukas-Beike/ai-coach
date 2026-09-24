"""Tests for structured planning change validation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.db.repositories import PlanningStateRepository
from backend.errors import (
    INVALID_PLANNING_DATE_ERROR,
    STALE_PLANNING_REVISION_ERROR,
    AppError,
)
from backend.planning.changes import StructuredTrainingChangeValidator


def _dict_row(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


class _CalendarConflictService:
    def __init__(self, conflict_dates: set[str] | None = None) -> None:
        self.conflict_dates = conflict_dates or set()
        self.calls: list[tuple[dict[str, Any], set[str]]] = []

    def conflicts(
        self, workout: dict[str, Any], exclude_library_ids: set[str]
    ) -> list[dict[str, Any]]:
        self.calls.append((workout, set(exclude_library_ids)))
        if workout["date"] in self.conflict_dates:
            return [{"date": workout["date"]}]
        return []


class StructuredTrainingChangeValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "planning.sqlite"
        self.db = sqlite3.connect(database_path)
        self.db.row_factory = _dict_row
        self.db.execute(
            "CREATE TABLE planning_state (id INTEGER PRIMARY KEY, revision INTEGER)"
        )
        self.db.execute("INSERT INTO planning_state (id, revision) VALUES (1, 7)")
        self.db.execute(
            "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT)"
        )
        self.calendar = _CalendarConflictService()
        self.validator = StructuredTrainingChangeValidator(
            PlanningStateRepository(), self.calendar
        )

    def tearDown(self) -> None:
        self.db.close()
        self.temporary_directory.cleanup()

    def _add_unit(
        self,
        local_id: str,
        *,
        date: str = "2031-06-01",
        archived: bool = False,
        local_deleted: bool = False,
        raw_payload: str | None = None,
    ) -> str:
        payload = raw_payload or json.dumps(
            {
                "date": date,
                "archived": archived,
                "local_deleted": local_deleted,
                "name": local_id,
            }
        )
        self.db.execute(
            "INSERT INTO planned_units (local_id, payload) VALUES (?, ?)",
            (local_id, payload),
        )
        return payload

    def _assert_app_error(
        self,
        call,
        *,
        status: int,
        message: str,
        reason: str,
    ) -> AppError:
        with self.assertRaises(AppError) as raised:
            call()
        self.assertEqual(raised.exception.status, status)
        self.assertEqual(raised.exception.message, message)
        self.assertEqual(raised.exception.reason, reason)
        return raised.exception

    def test_create_requires_a_valid_date(self) -> None:
        self._assert_app_error(
            lambda: self.validator.validate([{"action": "create"}], {}, self.db, False),
            status=400,
            message="Eine neue geplante Einheit benötigt ein Datum.",
            reason="invalid_change",
        )
        self._assert_app_error(
            lambda: self.validator.validate(
                [{"action": "create", "date": "2031-02-30"}],
                {},
                self.db,
                False,
            ),
            status=400,
            message=INVALID_PLANNING_DATE_ERROR,
            reason="invalid_change",
        )
        self.assertEqual(self.calendar.calls, [])

    def test_duplicate_final_dates_are_rejected_before_calendar_checks(self) -> None:
        self._assert_app_error(
            lambda: self.validator.validate(
                [
                    {"action": "create", "date": "2031-06-03"},
                    {"action": "create", "date": "2031-06-03"},
                ],
                {},
                self.db,
                False,
            ),
            status=409,
            message=(
                "Der Plan enthält mehrere Einheiten für den 2031-06-03; "
                "pro Tag ist eine Einheit möglich."
            ),
            reason="plan_date_conflict",
        )
        self.assertEqual(self.calendar.calls, [])

    def test_moved_and_restored_dates_check_calendar_and_exclude_batch_ids(
        self,
    ) -> None:
        self._add_unit("move-me", date="2031-06-01")
        self._add_unit("restore-me", date="2031-06-02", archived=True)

        revision = self.validator.validate(
            [
                {"action": "update", "local_id": "move-me", "date": "2031-06-03"},
                {"action": "restore", "local_id": "restore-me"},
            ],
            {},
            self.db,
            False,
        )

        self.assertEqual(revision, 7)
        self.assertEqual(
            {(call[0]["date"], frozenset(call[1])) for call in self.calendar.calls},
            {
                ("2031-06-03", frozenset({"move-me", "restore-me"})),
                ("2031-06-02", frozenset({"move-me", "restore-me"})),
            },
        )

    def test_calendar_conflict_on_moved_date_is_reported(self) -> None:
        self._add_unit("move-me", date="2031-06-01")
        self.calendar.conflict_dates.add("2031-06-03")

        self._assert_app_error(
            lambda: self.validator.validate(
                [{"action": "update", "local_id": "move-me", "date": "2031-06-03"}],
                {},
                self.db,
                False,
            ),
            status=409,
            message="Für den 2031-06-03 existiert bereits eine lokale Kalendereinheit.",
            reason="plan_date_conflict",
        )
        self.assertEqual(
            self.calendar.calls,
            [({"date": "2031-06-03"}, {"move-me"})],
        )

    def test_delete_and_archive_make_existing_rows_inactive(self) -> None:
        self._add_unit("delete-me", date="2031-06-03")
        self._add_unit("archive-me", date="2031-06-03")

        revision = self.validator.validate(
            [
                {"action": "delete", "local_id": "delete-me"},
                {"action": "archive", "local_id": "archive-me"},
            ],
            {},
            self.db,
            False,
        )

        self.assertEqual(revision, 7)
        self.assertEqual(self.calendar.calls, [])

    def test_missing_rows_are_ignored_even_for_restore(self) -> None:
        self._add_unit("corrupt", raw_payload="{")
        self._add_unit("non-dict", raw_payload="[]")
        revision = self.validator.validate(
            [
                {"action": "restore", "local_id": "missing"},
                {"action": "restore", "local_id": "corrupt"},
                {"action": "restore", "local_id": "non-dict"},
            ],
            {},
            self.db,
            False,
        )

        self.assertEqual(revision, 7)
        self.assertEqual(self.calendar.calls, [])

    def test_required_revision_is_enforced_and_optional_revision_is_allowed(
        self,
    ) -> None:
        self._assert_app_error(
            lambda: self.validator.validate([], {}, self.db, True),
            status=400,
            message="Eine vollständige Planänderung benötigt die gelesene Planrevision.",
            reason="planning_revision_required",
        )
        self.assertEqual(self.validator.validate([], {}, self.db, False), 7)
        self.assertEqual(
            self.validator.validate([], {"expected_revision": "7"}, self.db, True), 7
        )

    def test_stale_revision_is_rejected(self) -> None:
        self._assert_app_error(
            lambda: self.validator.validate(
                [], {"expected_revision": 6}, self.db, False
            ),
            status=409,
            message=STALE_PLANNING_REVISION_ERROR,
            reason="planning_revision_conflict",
        )

    def test_expected_revision_conversion_errors_are_preserved(self) -> None:
        for value, error_type in (("not-an-int", ValueError), ([], TypeError)):
            with self.subTest(value=value), self.assertRaises(error_type):
                self.validator.validate(
                    [], {"expected_revision": value}, self.db, False
                )

    def test_required_payload_hash_rejects_missing_or_malformed_hash(self) -> None:
        self._add_unit("unit")
        for expected_hash in (None, "not-a-hash", "a" * 63, "g" * 64):
            change = {"action": "update", "local_id": "unit"}
            if expected_hash is not None:
                change["expected_payload_hash"] = expected_hash
            with self.subTest(expected_hash=expected_hash):
                self._assert_app_error(
                    lambda change=change: self.validator.validate(
                        [change], {"expected_revision": 7}, self.db, True
                    ),
                    status=400,
                    message="Eine vollständige Planänderung benötigt aktuelle Payload-Hashes.",
                    reason="payload_hash_required",
                )

    def test_required_hash_validates_current_payload(self) -> None:
        payload = self._add_unit("unit")
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        self.assertEqual(
            self.validator.validate(
                [
                    {
                        "action": "update",
                        "local_id": "unit",
                        "expected_payload_hash": payload_hash.upper(),
                    }
                ],
                {"expected_revision": 7},
                self.db,
                True,
            ),
            7,
        )

    def test_malformed_or_stale_optional_payload_hash_is_a_conflict(self) -> None:
        self._add_unit("unit")
        for expected_hash in ("bad", "0" * 64):
            with self.subTest(expected_hash=expected_hash):
                self._assert_app_error(
                    lambda expected_hash=expected_hash: self.validator.validate(
                        [
                            {
                                "action": "update",
                                "local_id": "unit",
                                "expected_payload_hash": expected_hash,
                            }
                        ],
                        {},
                        self.db,
                        False,
                    ),
                    status=409,
                    message="Eine Planänderung ist inzwischen veraltet.",
                    reason="payload_hash_conflict",
                )

    def test_missing_local_id_and_missing_hashed_row_keep_existing_errors(self) -> None:
        self._assert_app_error(
            lambda: self.validator.validate(
                [{"action": "update"}], {"expected_revision": 7}, self.db, True
            ),
            status=400,
            message="Jede Planänderung benötigt eine lokale ID.",
            reason="invalid_change",
        )
        self._assert_app_error(
            lambda: self.validator.validate(
                [
                    {
                        "action": "update",
                        "local_id": "missing",
                        "expected_payload_hash": "0" * 64,
                    }
                ],
                {},
                self.db,
                False,
            ),
            status=409,
            message="Eine Planänderung ist inzwischen veraltet.",
            reason="payload_hash_conflict",
        )

    def test_valid_batch_returns_current_revision(self) -> None:
        self.assertEqual(
            self.validator.validate(
                [{"action": "create", "date": "2031-06-03"}],
                {"expected_revision": 7},
                self.db,
                True,
            ),
            7,
        )

    def test_failures_do_not_mutate_rows_or_revision(self) -> None:
        payload = self._add_unit("unit", date="2031-06-01")
        self.calendar.conflict_dates.add("2031-06-03")
        before = self.db.execute(
            "SELECT local_id, payload FROM planned_units ORDER BY local_id"
        ).fetchall()
        revision_before = self.db.execute(
            "SELECT revision FROM planning_state WHERE id=1"
        ).fetchone()["revision"]

        with self.assertRaises(AppError):
            self.validator.validate(
                [{"action": "update", "local_id": "unit", "date": "2031-06-03"}],
                {},
                self.db,
                False,
            )

        after = self.db.execute(
            "SELECT local_id, payload FROM planned_units ORDER BY local_id"
        ).fetchall()
        revision_after = self.db.execute(
            "SELECT revision FROM planning_state WHERE id=1"
        ).fetchone()["revision"]
        self.assertEqual(after, before)
        self.assertEqual(after[0]["payload"], payload)
        self.assertEqual(revision_after, revision_before)


if __name__ == "__main__":
    unittest.main()
