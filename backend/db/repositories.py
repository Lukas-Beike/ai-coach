"""Explicit persistence interfaces for application repositories."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any


class KeyValueRepository:
    """Read and write the application's durable key/value settings."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def get(self, db: Any, key: str) -> str | None:
        row = db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, db: Any, key: str, value: str) -> None:
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, self._now()),
        )


class ProfileRepository:
    """Persist the serialized athlete profile through the key/value store."""

    _KEY = "profile"

    def __init__(self, key_value: KeyValueRepository):
        self._key_value = key_value

    def get(self, db: Any) -> str | None:
        return self._key_value.get(db, self._KEY)

    def set(self, db: Any, payload: str) -> None:
        self._key_value.set(db, self._KEY, payload)


class CompetitionRepository:
    """Read local competitions without owning a database connection."""

    _LIST_FIELDS = (
        "id, name, event_date, start_date_local, sport, priority, category, distance, target, "
        "course_profile, notes, description, moving_time, external_id, intervals_event_id, sync_dirty, "
        "sync_state, sync_conflict, last_synced_at"
    )

    def list(self, db: Any, limit: int | None = None) -> list[dict[str, Any]]:
        query = f"SELECT {self._LIST_FIELDS} FROM competitions ORDER BY event_date, priority, name"
        params: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        return [dict(row) for row in db.execute(query, params).fetchall()]

    def get(self, db: Any, competition_id: str) -> dict[str, Any] | None:
        row = db.execute("SELECT * FROM competitions WHERE id = ?", (competition_id,)).fetchone()
        return dict(row) if row else None


class TrainingPlanRepository:
    """Persist and retrieve local training-plan metadata without owning a connection."""

    def create(
        self,
        db: Any,
        plan_id: str,
        name: str,
        goal: str,
        start_date: str,
        end_date: str,
        status: str,
        created_at: str,
    ) -> None:
        db.execute(
            "INSERT INTO training_plans(id, name, goal, start_date, end_date, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (plan_id, name, goal, start_date, end_date, status, created_at, created_at),
        )

    def list(self, db: Any, limit: int = 30) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT id, name, goal, start_date, end_date, status, created_at, updated_at "
            "FROM training_plans ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, db: Any, plan_id: str) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT id, name, goal, start_date, end_date, status, created_at, updated_at "
            "FROM training_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        return dict(row) if row else None

    def update(
        self,
        db: Any,
        plan_id: str,
        name: str,
        goal: str,
        start_date: str,
        end_date: str,
        status: str,
        updated_at: str,
    ) -> None:
        db.execute(
            "UPDATE training_plans SET name=?, goal=?, start_date=?, end_date=?, status=?, updated_at=? WHERE id=?",
            (name, goal, start_date, end_date, status, updated_at, plan_id),
        )

    def delete(self, db: Any, plan_id: str) -> None:
        db.execute("DELETE FROM training_plans WHERE id = ?", (plan_id,))


class PlanAdjustmentRepository:
    """Persist adaptive-replanning previews and their application status."""

    def create_preview(self, db: Any, adjustment_id: str, payload: str, created_at: str) -> None:
        db.execute(
            "INSERT INTO plan_adjustments(id, payload, status, created_at) VALUES (?, ?, 'preview', ?)",
            (adjustment_id, payload, created_at),
        )

    def latest(self, db: Any) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT id, payload, status, created_at, applied_at FROM plan_adjustments ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def list_recent(self, db: Any, limit: int = 100) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT payload, status FROM plan_adjustments ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, db: Any, adjustment_id: str) -> dict[str, Any] | None:
        row = db.execute("SELECT payload, status FROM plan_adjustments WHERE id = ?", (adjustment_id,)).fetchone()
        return dict(row) if row else None

    def mark_applied(self, db: Any, adjustment_id: str, payload: str, status: str, applied_at: str) -> None:
        db.execute(
            "UPDATE plan_adjustments SET payload=?, status=?, applied_at=? WHERE id=?",
            (payload, status, applied_at, adjustment_id),
        )


class ChatRepository:
    """Persist and retrieve local chat messages without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def add(self, db: Any, role: str, content: str) -> dict[str, Any]:
        created_at = self._now()
        clean_content = content.strip()
        cursor = db.execute(
            "INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)",
            (role, clean_content, created_at),
        )
        return {"id": cursor.lastrowid, "role": role, "content": clean_content, "created_at": created_at}

    def list(self, db: Any, limit: int = 100) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT id, role, content, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in reversed(rows)]


class CheckinRepository:
    """Persist and retrieve athlete check-ins without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def list(self, db: Any, limit: int = 30) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT checkin_date, soreness, stress, motivation, session_rpe, day_form, illness, pain, "
            "available_minutes, availability_notes, notes, created_at, updated_at "
            "FROM athlete_checkins ORDER BY checkin_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert(self, db: Any, checkin: dict[str, Any]) -> None:
        now = self._now()
        db.execute(
            "INSERT INTO athlete_checkins(checkin_date, soreness, stress, motivation, session_rpe, day_form, illness, pain, "
            "available_minutes, availability_notes, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(checkin_date) DO UPDATE SET soreness=excluded.soreness, stress=excluded.stress, "
            "motivation=excluded.motivation, session_rpe=excluded.session_rpe, day_form=excluded.day_form, illness=excluded.illness, "
            "pain=excluded.pain, available_minutes=excluded.available_minutes, "
            "availability_notes=excluded.availability_notes, notes=excluded.notes, updated_at=excluded.updated_at",
            (
                checkin["checkin_date"], checkin["soreness"], checkin["stress"], checkin["motivation"],
                checkin["session_rpe"], checkin["day_form"], checkin["illness"], checkin["pain"], checkin["available_minutes"],
                checkin["availability_notes"], checkin["notes"], now, now,
            ),
        )


class ActivityFeedbackRepository:
    """Persist athlete notes about completed activities without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def list(self, db: Any, limit: int = 100) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT activity_id, activity_name, activity_date, notes, created_at, updated_at "
            "FROM activity_feedback ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, db: Any, activity_id: str) -> None:
        db.execute("DELETE FROM activity_feedback WHERE activity_id = ?", (activity_id,))

    def upsert(self, db: Any, feedback: dict[str, str]) -> None:
        now = self._now()
        db.execute(
            "INSERT INTO activity_feedback(activity_id, activity_name, activity_date, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(activity_id) DO UPDATE SET activity_name=excluded.activity_name, "
            "activity_date=excluded.activity_date, notes=excluded.notes, updated_at=excluded.updated_at",
            (feedback["activity_id"], feedback["activity_name"], feedback["activity_date"], feedback["notes"], now, now),
        )


class SnapshotRepository:
    """Persist bounded provider snapshots without owning a connection."""

    def save(self, db: Any, snapshot: dict[str, Any], created_at: str, *, keep: int = 12) -> None:
        db.execute(
            "INSERT INTO snapshots(payload, created_at) VALUES (?, ?)",
            (json.dumps(snapshot, ensure_ascii=False), created_at),
        )
        db.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)", (keep,))

    def latest_payload(self, db: Any) -> str | None:
        row = db.execute("SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        return row["payload"] if row else None


class WorkoutDraftRepository:
    """Persist and retrieve local workout drafts without owning a connection."""

    def create(self, db: Any, draft_id: str, payload: str, created_at: str) -> None:
        db.execute(
            "INSERT INTO workout_drafts(id, payload, status, created_at, updated_at) VALUES (?, ?, 'draft', ?, ?)",
            (draft_id, payload, created_at, created_at),
        )

    def list(self, db: Any, limit: int = 50) -> list[dict[str, Any]]:
        rows = db.execute("SELECT * FROM workout_drafts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get(self, db: Any, draft_id: str) -> dict[str, Any] | None:
        row = db.execute("SELECT * FROM workout_drafts WHERE id = ?", (draft_id,)).fetchone()
        return dict(row) if row else None

    def delete(self, db: Any, draft_id: str) -> None:
        db.execute("DELETE FROM workout_drafts WHERE id = ?", (draft_id,))
