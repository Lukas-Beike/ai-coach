"""Explicit Wahoo library sync on an encrypted database with a mocked transport."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from backend.canonical.vocabulary import RemoteEntityKind
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.remote_links import RemoteLinkRepository
from backend.db.schema import configure_cipher, initialize_schema
from backend.planning import library as planning_library
from backend.providers.wahoo_client import WahooClient
from backend.sync.executor import WahooJobAdapter
from backend.sync.wahoo_plan_push import WahooPlanPushService
from backend.sync.wahoo_workout_export import WahooWorkoutExport, wahoo_external_id

try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None

NOW = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)
LOCAL_ID = "12345678-1234-5678-1234-567812345678"
TOKEN = "fake-wahoo-token-e2e"
WORKOUT = {
    "type": "Ride",
    "name": "Sweet spot",
    "description": "Warmup\n- 10m 150W\n\nMain Set\n- 8m 250-280W\n- 2m 120W",
}


class FakeWahooTransport:
    """Mocked Wahoo HTTP transport that keeps plans like the real service."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.plans: dict[int, dict[str, Any]] = {}

    def __call__(self, method: str, url: str, **kwargs: Any) -> Any:
        path = urlsplit(url).path
        fields = (
            parse_qs(kwargs["raw_body"].decode("ascii"))
            if kwargs.get("raw_body")
            else {}
        )
        self.requests.append(
            {
                "method": method,
                "path": path,
                "headers": kwargs.get("headers"),
                "fields": fields,
            }
        )
        if method == "GET" and path == "/v1/plans":
            return [dict(plan) for plan in self.plans.values()]
        if method == "POST" and path == "/v1/plans":
            plan_id = 500 + len(self.plans)
            self.plans[plan_id] = {
                "id": plan_id,
                "external_id": fields["plan[external_id]"][0],
                "file": fields["plan[file]"][0],
            }
            return self.plans[plan_id]
        if method == "PUT" and path.startswith("/v1/plans/"):
            plan_id = int(path.rsplit("/", 1)[1])
            self.plans[plan_id]["file"] = fields["plan[file]"][0]
            return self.plans[plan_id]
        raise AssertionError(f"unexpected request {method} {path}")

    def writes(self) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["method"] in {"POST", "PUT", "DELETE"}]


@unittest.skipIf(
    cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
)
class WahooPlanPushEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.path = Path(root.name) / "encrypted.db"
        self.manager = DatabaseManager(
            self.path,
            cipher_backend,
            password="synthetic-e2e-test-key",
            configure=configure_cipher,
            row_factory=row_factory,
        )
        self.addCleanup(self.manager.close)
        raw = json.dumps(WORKOUT)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (LOCAL_ID, LOCAL_ID, raw, "2026-10-01T00:00:00+00:00"),
            )
        self.hash = planning_library.library_payload_hash(raw)
        self.transport = FakeWahooTransport()
        client = WahooClient(
            request=self.transport,
            access_token=lambda: TOKEN,
            refresh_access_token=lambda rejected: TOKEN,
            invalidate_access_token=None,
        )
        service = WahooPlanPushService(
            configured=lambda: True,
            database_manager=lambda: self.manager,
            export=lambda: WahooWorkoutExport(lambda: client, now=lambda: NOW),
            now=lambda: NOW,
            redactor=lambda text: text,
        )
        self.adapter = WahooJobAdapter(sync=None, plan_push=service)  # type: ignore[arg-type]

    def sync(self) -> dict[str, Any]:
        return self.adapter.execute(
            {"id": "job-1"},
            {
                "entries": [
                    {
                        "library_workout_id": LOCAL_ID,
                        "expected_payload_hash": self.hash,
                    }
                ],
                "reason": "job",
            },
            "manual",
            job_type="plan_push",
        )

    def link(self):
        with self.manager.unit_of_work() as db:
            return RemoteLinkRepository().get(
                db, RemoteEntityKind.LIBRARY_WORKOUT, LOCAL_ID, "wahoo"
            )

    def test_database_is_encrypted_at_rest(self) -> None:
        self.assertNotIn(b"SQLite format 3", self.path.read_bytes()[:16])

    def test_sync_uploads_the_plan_then_updates_it_instead_of_duplicating(self) -> None:
        first = self.sync()

        self.assertTrue(first["ok"])
        (create,) = self.transport.writes()
        self.assertEqual(("POST", "/v1/plans"), (create["method"], create["path"]))
        self.assertEqual({"Authorization": f"Bearer {TOKEN}"}, create["headers"])
        self.assertEqual(
            [wahoo_external_id(LOCAL_ID)], create["fields"]["plan[external_id]"]
        )
        encoded = create["fields"]["plan[file]"][0].split(",", 1)[1]
        document = json.loads(base64.b64decode(encoded))
        self.assertEqual("Sweet spot", document["header"]["name"])
        self.assertEqual(
            [150, 250, 120],
            [i["targets"][0]["low"] for i in document["intervals"]],
        )
        link = self.link()
        self.assertEqual("500", link.remote_id)
        self.assertEqual("synced", link.sync_state.value)

        second = self.sync()

        self.assertTrue(second["ok"])
        self.assertEqual(1, len(self.transport.plans))
        self.assertEqual(
            ["POST", "PUT"], [r["method"] for r in self.transport.writes()]
        )
        self.assertEqual("/v1/plans/500", self.transport.writes()[1]["path"])
        self.assertEqual("500", self.link().remote_id)


if __name__ == "__main__":
    unittest.main()
