"""Reusable test setup; deliberately independent of any test case class."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.coach import limits as coach_limits
from backend.coach import streams as coach_streams


def build_gemini_request_payload(server, payload, model):
    """Exercise the concrete Gemini request owner with active test settings."""
    return server.gemini_request_payload_service().build(
        payload,
        model,
        default_max_output_tokens=coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
        default_thinking_level=server.SETTINGS.selected_thinking_level(),
        json_media_type=server.JSON_MEDIA_TYPE,
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
        return [call for call in self.calls if call["method"] in {"POST", "PUT", "DELETE"}]


def parsed_workout_fixture(duration=1800, *, sport="Ride", kind="power", units="%ftp", value=85, distance=None):
    """One synthetic provider-parsed step using the documented response schema."""
    step = {"duration": duration, kind: {"units": units, "value": value}}
    if distance is not None:
        step["distance"] = distance
    return {"type": sport, "moving_time": duration, "icu_training_load": 20, "workout_doc": {"duration": duration, "steps": [step]}}


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
        self.recorder.record("GET", "/athlete/0/activities", {"activity_days": activity_days})
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
        return [{**event, "id": event.get("id") or "remote-event-1"} for event in events]

    def bulk_delete_events(self, identifiers):
        if identifiers:
            self.recorder.record("DELETE", "/athlete/0/events", identifiers)
        return len(identifiers)

    def create_library_workouts(self, workouts):
        if workouts:
            self.recorder.record("POST", "/athlete/0/workouts", workouts)
        return [{**workout, "id": workout.get("id") or "remote-workout-1"} for workout in workouts]

    def update_library_workout(self, workout_id, workout):
        self.recorder.record("PUT", f"/athlete/0/workouts/{workout_id}", workout)
        return {**workout, "id": workout_id}

    def plan_library_workout(self, workout_id, workout, plan_date):
        self.recorder.record("POST", "/athlete/0/events", {"workout_id": workout_id, "date": plan_date})
        return {"id": "remote-planned-event"}

    def upsert_calendar_events(self, events):
        if events:
            self.recorder.record("POST", "/athlete/0/events/bulk", events)
        return [{**event, "id": event.get("id") or "remote-planned-event"} for event in events]

    def delete_event(self, event_id):
        self.recorder.record("DELETE", f"/athlete/0/events/{event_id}")

    def delete_activity(self, activity_id):
        self.recorder.record("DELETE", f"/activity/{activity_id}")


@contextmanager
def isolated_server(server, root: Path, *, app_password: str = ""):
    """Run application setup against temporary state and restore globals."""
    patches = (
        patch.object(server, "CONFIG", replace(server.CONFIG, app_password=app_password)),
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
        if server.DATABASE_MANAGER:
            server.DATABASE_MANAGER.close()
        server.DATABASE_MANAGER = None
        server.DATABASE_MANAGER_SIGNATURE = None
        for item in reversed(patches):
            item.stop()


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
            (auth.session_token_hash(token), auth.session_token_hash("csrf"), now + SESSION_TTL_SECONDS, server.utc_now(), server.utc_now()),
        )
    return token


def reset_application_state(server) -> None:
    """Clear disposable application state without invoking a test case lifecycle."""
    tables = (
        "messages", "coach_commands", "coach_plan_artifacts", "snapshots", "training_plans",
        "workout_library", "planned_units", "competitions", "competition_sync_tombstones",
        "athlete_checkins", "activity_feedback", "plan_adjustments", "coach_action_proposals",
        "change_history", "provider_refresh_history", "sync_job_items", "sync_jobs",
        "provider_sync_cursors", "public_event_candidates", "public_event_sources",
        "external_calendar_events", "sessions", "kv",
    )
    with server.DB_LOCK, server.database_manager().unit_of_work() as db:
        for table in tables:
            db.execute(f"DELETE FROM {table}")
    server.profile_service().save({})
    coach_streams.CHAT_STREAM_REGISTRY.clear_state()

