"""Isolated status projection for attached and durable Coach jobs."""

from __future__ import annotations

import json
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import Mock

from backend.coach.authorization import coach_session_key
from backend.coach.job_submission import CoachJobSubmissionService


class FakeStreamRegistry:
    def __init__(self, attached: dict[str, str] | None = None) -> None:
        self.attached = attached

    def attached_status(self, _session_csrf_hash: str) -> dict[str, str] | None:
        return self.attached


class FakeDatabase:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def execute(self, _query: str) -> FakeDatabase:
        return self

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class FakeDatabaseManager:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.database = FakeDatabase(rows)
        self.opened = 0

    @contextmanager
    def unit_of_work(self):
        self.opened += 1
        yield self.database


class CoachJobStatusTests(unittest.TestCase):
    def make_service(
        self,
        rows: list[dict[str, object]] | None = None,
        attached: dict[str, str] | None = None,
    ) -> tuple[CoachJobSubmissionService, FakeDatabaseManager]:
        manager = FakeDatabaseManager(rows or [])
        service = CoachJobSubmissionService(
            lambda: manager,
            Mock(),
            threading.Lock(),
            Mock(),
            Mock(),
            FakeStreamRegistry(attached),
            Mock(),
            lambda: "synthetic-time",
            background_horizon_days=30,
        )
        return service, manager

    @staticmethod
    def background_row(
        session_csrf_hash: str,
        *,
        status: str = "running",
        phase: str | None = "executing_tools",
        plan_scope: dict[str, object] | None = None,
    ) -> dict[str, object]:
        receipt = {
            "mode": "background",
            "session_key": coach_session_key(session_csrf_hash),
            "operation_id": "synthetic-operation",
        }
        if phase is not None:
            receipt["phase"] = phase
        if plan_scope is not None:
            receipt["plan_scope"] = plan_scope
        return {"client_turn_id": "synthetic-turn", "status": status, "receipt": json.dumps(receipt)}

    def test_attached_status_takes_priority_over_background_lookup(self) -> None:
        service, manager = self.make_service(
            rows=[self.background_row("same-session")],
            attached={"status": "running", "operation_id": "attached-operation"},
        )

        self.assertEqual(
            service.stream_status("same-session"),
            {"status": "running", "operation_id": "attached-operation"},
        )
        self.assertEqual(manager.opened, 0)

    def test_idle_status_has_exact_response_shape(self) -> None:
        service, _manager = self.make_service()

        self.assertEqual(service.stream_status("idle-session"), {"status": "idle", "operation_id": None})

    def test_background_status_projects_receipt_fields(self) -> None:
        service, _manager = self.make_service(
            rows=[self.background_row("owner", plan_scope={"background": True, "horizon_days": 30})]
        )

        self.assertEqual(
            service.stream_status("owner"),
            {
                "status": "running",
                "operation_id": "synthetic-operation",
                "mode": "background",
                "phase": "executing_tools",
                "plan_scope": {"background": True, "horizon_days": 30},
            },
        )

    def test_background_status_falls_back_to_job_status_and_empty_scope(self) -> None:
        service, _manager = self.make_service(
            rows=[self.background_row("owner", status="queued", phase=None)]
        )

        self.assertEqual(
            service.stream_status("owner"),
            {
                "status": "running",
                "operation_id": "synthetic-operation",
                "mode": "background",
                "phase": "queued",
                "plan_scope": {},
            },
        )

    def test_background_job_from_another_session_projects_as_idle(self) -> None:
        service, _manager = self.make_service(rows=[self.background_row("owner")])

        self.assertEqual(
            service.stream_status("different-session"),
            {"status": "idle", "operation_id": None},
        )


if __name__ == "__main__":
    unittest.main()
