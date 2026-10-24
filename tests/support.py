"""Reusable test setup; deliberately independent of any test case class."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.coach import streams as coach_streams
from backend.config import Config
from backend.db.manager import DATABASE_MANAGER_CACHE
from backend.planning.context import compact_snapshot
from backend.runtime import clock as runtime_clock

PROVIDER_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "providers"
PROVIDER_SYNCED_TEXT = "2026-10-10T06:00:00+00:00"
GARMIN_FIXTURE_SECTIONS = (
    "activities",
    "sleep",
    "hrv",
    "resting_hr",
    "readiness",
    "max_metrics",
    "cycling_ftp",
    "running_threshold",
    "weight",
    "cycling_ftp_history",
    "daily_training_status",
    "training_load_balance",
)


class IntervalsRequestRecorder:
    """Record only safe request metadata for provider contract tests."""

    def __init__(self):
        self.calls = []

    def record(self, method, path, payload=None):
        metadata = {
            "method": method.upper(),
            "path": str(path).split("?", 1)[0],
            "payload_keys": sorted(payload) if isinstance(payload, dict) else None,
            "payload_count": len(payload) if isinstance(payload, list) else None,
        }
        self.calls.append(metadata)
        return metadata

    @property
    def mutations(self):
        return [
            call for call in self.calls if call["method"] in {"POST", "PUT", "DELETE"}
        ]


def parsed_workout_fixture(
    duration=1800, *, sport="Ride", kind="power", units="%ftp", value=85, distance=None
):
    """One synthetic provider-parsed step using the documented response schema."""
    step = {"duration": duration, kind: {"units": units, "value": value}}
    if distance is not None:
        step["distance"] = distance
    return {
        "type": sport,
        "moving_time": duration,
        "icu_training_load": 20,
        "workout_doc": {"duration": duration, "steps": [step]},
    }


class RecordedIntervalsClient:
    """Small provider fake shared by remote-mutation contract tests."""

    def __init__(self, recorder, snapshot=None, competitions=None, library=None):
        self.recorder = recorder
        self.snapshot = snapshot or {
            "synced_at": "2026-08-31T08:00:00+00:00",
            "athlete": {},
            "recent_activities": [],
            "recent_wellness": [],
            "upcoming_calendar": [],
        }
        self.competitions = list(competitions or [])
        self.library = list(library or [])

    def fetch_snapshot(self, activity_days):
        self.recorder.record(
            "GET", "/athlete/0/activities", {"activity_days": activity_days}
        )
        return self.snapshot

    def fetch_competition_events(self):
        self.recorder.record("GET", "/athlete/0/events")
        return list(self.competitions)

    def get_workout_library(self):
        self.recorder.record("GET", "/athlete/0/workouts")
        return list(self.library)

    def upsert_competition_events(self, events):
        if events:
            self.recorder.record("POST", "/athlete/0/events", events)
        return [
            {**event, "id": event.get("id") or "remote-event-1"} for event in events
        ]

    def bulk_delete_events(self, identifiers):
        if identifiers:
            self.recorder.record("DELETE", "/athlete/0/events", identifiers)
        return len(identifiers)

    def create_library_workouts(self, workouts):
        if workouts:
            self.recorder.record("POST", "/athlete/0/workouts", workouts)
        return [
            {**workout, "id": workout.get("id") or "remote-workout-1"}
            for workout in workouts
        ]

    def update_library_workout(self, workout_id, workout):
        self.recorder.record("PUT", f"/athlete/0/workouts/{workout_id}", workout)
        return {**workout, "id": workout_id}

    def plan_library_workout(self, payload):
        self.recorder.record("POST", "/athlete/0/events", payload)
        return {**payload, "id": "remote-planned-event"}

    def upsert_calendar_events(self, events):
        if events:
            self.recorder.record("POST", "/athlete/0/events/bulk", events)
        return [
            {**event, "id": event.get("id") or "remote-planned-event"}
            for event in events
        ]

    def delete_event(self, event_id):
        self.recorder.record("DELETE", f"/athlete/0/events/{event_id}")

    def delete_activity(self, activity_id):
        self.recorder.record("DELETE", f"/activity/{activity_id}")


@contextmanager
def isolated_server(server, root: Path, *, app_password: str = ""):
    """Run application setup against temporary state and restore globals."""
    patches = (
        patch.object(
            server, "CONFIG", replace(server.CONFIG, app_password=app_password)
        ),
        patch.object(server, "DATA_DIR", root),
        patch.object(server, "DB_PATH", root / "test.db"),
        patch.object(server, "LOG_PATH", root / "test.log"),
    )
    for item in patches:
        item.start()
    try:
        server.initialise_database()
        yield
    finally:
        DATABASE_MANAGER_CACHE.reset()
        for item in reversed(patches):
            item.stop()


@contextmanager
def canonical_backfill_stopped(server, timeout: float = 10.0):
    """Stop and join the backfill thread a real restore starts before cleanup."""
    try:
        yield
    finally:
        server.CANONICAL_BACKFILL.worker.stop()
        server.CANONICAL_BACKFILL.worker.join(timeout)


def create_test_session(server) -> str:
    """Create one authenticated session without depending on a test case."""
    import uuid

    from backend.http_api.auth import SESSION_TTL_SECONDS

    token = f"session-{uuid.uuid4().hex}"
    now = server.time.time()
    auth = server.session_auth_service()
    with server.DB_LOCK, server.database_manager().unit_of_work() as db:
        db.execute(
            "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
            (
                auth.session_token_hash(token),
                auth.session_token_hash("csrf"),
                now + SESSION_TTL_SECONDS,
                runtime_clock.utc_now(),
                runtime_clock.utc_now(),
            ),
        )
    return token


def make_config(**overrides: Any) -> Config:
    """Return a real, inert Config; tests never read a real .env."""
    values: dict[str, Any] = {
        "port": 8090,
        "openai_api_key": "",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "model",
        "intervals_api_key": "",
        "intervals_athlete_id": "0",
        "garmin_email": "",
        "garmin_password": "",
        "garmin_tokenstore": "unused",
        "garmin_fixture_path": "",
        "calendar_ical_url": "",
        "app_password": "",
        "secure_cookies": False,
        "data_retention_days": -1,
    }
    values.update(overrides)
    return Config(**values)


def application_tables(db: Any) -> list[str]:
    """Discover every application table so reset cannot drift from the schema."""
    rows = db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND substr(name, 1, 7) <> 'sqlite_' "
        "ORDER BY name"
    ).fetchall()
    return [row["name"] for row in rows]


def reset_application_state(server) -> None:
    """Clear disposable application state without invoking a test case lifecycle.

    All tables are emptied in one transaction with deferred foreign keys, so the
    delete order is irrelevant. planning_state is re-seeded because a missing
    singleton row is treated as database corruption by planning revision bumps.
    """
    with server.DB_LOCK, server.database_manager().unit_of_work() as db:
        db.execute("PRAGMA defer_foreign_keys = ON")
        for table in application_tables(db):
            db.execute(f'DELETE FROM "{table}"')
        db.execute(
            "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
            (runtime_clock.utc_now(),),
        )
    server.ATHLETE_DATA.profile().save({})
    coach_streams.CHAT_STREAM_REGISTRY.clear_state()


def load_provider_fixture(path: str) -> Any:
    """Read one read-only wire fixture under tests/fixtures/providers."""
    return json.loads((PROVIDER_FIXTURE_ROOT / path).read_text(encoding="utf-8"))


def intervals_snapshot_fixture(synced_at: str = PROVIDER_SYNCED_TEXT) -> dict[str, Any]:
    """Compact Intervals.icu snapshot built from the wire fixtures."""
    return compact_snapshot(
        load_provider_fixture("intervals/athlete.json"),
        load_provider_fixture("intervals/activities.json"),
        load_provider_fixture("intervals/wellness.json"),
        load_provider_fixture("intervals/events.json"),
        all_sync_days=42,
        synced_at=synced_at,
    )


def garmin_payload_fixture(synced_at: str = PROVIDER_SYNCED_TEXT) -> dict[str, Any]:
    """Stored Garmin payload with every fixture section and its sync time."""
    payload: dict[str, Any] = {"synced_at": synced_at}
    for name in GARMIN_FIXTURE_SECTIONS:
        payload[name] = load_provider_fixture(f"garmin/{name}.json")
    return payload
