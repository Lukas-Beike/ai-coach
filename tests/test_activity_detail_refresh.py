"""Read-only provider refresh, durable cache and failure atomicity contracts."""

import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import Mock

from backend.activities.detail_store import ActivityDetailStore
from backend.errors import AppError
from backend.sync.activity_details import (
    MAX_STREAM_POINTS,
    ActivityDetailRefreshService,
    normalize_streams,
)
from backend.sync.jobs import JobValidationError, normalize_sync_job_request


class Manager:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def unit_of_work(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            yield db


class ActivityDetailRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = Manager(Path(self.directory.name) / "fixture.sqlite")
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
        self.store = ActivityDetailStore(self.manager)
        self.api = Mock()
        self.state = Mock()
        self.state.latest_snapshot.return_value = {
            "raw_provider_data": {"activities": [{"id": "CaseSensitive-1"}]}
        }
        self.service = ActivityDetailRefreshService(
            api_client=self.api,
            state_repository=self.state,
            store=self.store,
            utc_now=lambda: "2026-10-02T08:00:00Z",
            configured=True,
        )

    def responses(self):
        return [
            {
                "id": "CaseSensitive-1",
                "name": "Synthetic ride",
                "private_field": "excluded",
            },
            [
                {"type": "time", "data": list(range(3001))},
                {"type": "watts", "data": [200] * 3001},
            ],
        ]

    def test_refresh_keeps_full_resolution_and_provenance_across_restart(self):
        self.api.get.side_effect = self.responses()
        self.assertEqual("completed", self.service.refresh("CaseSensitive-1")["status"])
        saved = ActivityDetailStore(self.manager).get("CaseSensitive-1")
        self.assertEqual(3001, len(saved["activity"]["streams"]["watts"]))
        self.assertEqual("Intervals.icu", saved["source"])
        self.assertEqual("2026-10-02T08:00:00Z", saved["observed_at"])
        self.assertNotIn("private_field", saved["activity"])
        self.assertEqual(
            "/activity/CaseSensitive-1", self.api.get.call_args_list[0].args[0]
        )
        self.api.post.assert_not_called()
        self.api.put.assert_not_called()

    def test_failed_second_fetch_preserves_previous_record(self):
        self.api.get.side_effect = self.responses()
        self.service.refresh("CaseSensitive-1")
        before = self.store.get("CaseSensitive-1")
        self.api.get.side_effect = [
            self.responses()[0],
            AppError(503, "Synthetic failure"),
        ]
        with self.assertRaises(AppError):
            self.service.refresh("CaseSensitive-1")
        self.assertEqual(before, self.store.get("CaseSensitive-1"))

    def test_unknown_id_and_path_syntax_never_reach_provider(self):
        with self.assertRaises(AppError):
            self.service.refresh("unknown")
        for activity_id in ("../x", "x/y", "x?athlete=other", "", "x" * 201):
            with self.subTest(activity_id=activity_id), self.assertRaises(ValueError):
                self.service.refresh(activity_id)
        self.api.get.assert_not_called()

    def test_mismatched_provider_id_is_not_committed(self):
        self.api.get.return_value = {"id": "other"}
        with self.assertRaises(AppError):
            self.service.refresh("CaseSensitive-1")
        self.assertIsNone(self.store.get("CaseSensitive-1"))

    def test_stream_limits_alignment_and_missing_values(self):
        for streams in (
            [{"type": "time", "data": [0, 0]}],
            [{"type": "time", "data": [0, 1]}, {"type": "watts", "data": [1]}],
            [{"type": "time", "data": [0] * (MAX_STREAM_POINTS + 1)}],
        ):
            with self.subTest(length=len(streams)), self.assertRaises(AppError):
                normalize_streams(streams)
        result = normalize_streams(
            [
                {"type": "time", "data": [0, 1, 2]},
                {"type": "watts", "data": [0, None, float("nan")]},
                {"type": "latlng", "data": [[1, 2]]},
            ]
        )
        self.assertEqual([0, None, None], result["watts"])
        self.assertNotIn("latlng", result)

    def test_job_normalization_preserves_case_and_rejects_unrelated_targets(self):
        envelope = normalize_sync_job_request(
            "intervals",
            "activity_details",
            {"activity_id": "CaseSensitive-1"},
            all_sync_days=-1,
        )
        self.assertEqual("CaseSensitive-1", envelope["payload"]["activity_id"])
        for provider, payload in (
            ("garmin", {"activity_id": "x"}),
            ("intervals", {"activity_id": "../x"}),
            ("intervals", {"activity_id": "x", "remote_write": True}),
        ):
            with self.subTest(provider=provider), self.assertRaises(JobValidationError):
                normalize_sync_job_request(
                    provider, "activity_details", payload, all_sync_days=-1
                )
