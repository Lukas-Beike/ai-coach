"""Explicit persistence interfaces for application repositories."""

from __future__ import annotations

import json
from collections.abc import Callable
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
        row = db.execute(
            "SELECT * FROM competitions WHERE id = ?", (competition_id,)
        ).fetchone()
        return dict(row) if row else None

    def count(self, db: Any) -> int:
        return int(
            db.execute("SELECT COUNT(*) AS count FROM competitions").fetchone()["count"]
        )

    def create_local(self, db: Any, competition: dict[str, Any], now: str) -> None:
        db.execute(
            "INSERT INTO competitions(id, name, event_date, sport, priority, distance, target, course_profile, notes, category, start_date_local, description, moving_time, external_id, sync_dirty, sync_state, sync_conflict, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, 'local', '', ?, ?)",
            (
                competition["id"],
                competition["name"],
                competition["event_date"],
                competition["sport"],
                competition["priority"],
                competition["distance"],
                competition["target"],
                competition["course_profile"],
                competition["notes"],
                competition["category"],
                competition["start_date_local"],
                competition["description"],
                competition["moving_time"],
                now,
                now,
            ),
        )

    def update_local(self, db: Any, competition: dict[str, Any], now: str) -> None:
        db.execute(
            "UPDATE competitions SET name=?, event_date=?, sport=?, priority=?, distance=?, target=?, course_profile=?, notes=?, category=?, start_date_local=?, description=?, moving_time=?, sync_dirty=1, sync_state='local', sync_conflict='', updated_at=? WHERE id=?",
            (
                competition["name"],
                competition["event_date"],
                competition["sport"],
                competition["priority"],
                competition["distance"],
                competition["target"],
                competition["course_profile"],
                competition["notes"],
                competition["category"],
                competition["start_date_local"],
                competition["description"],
                competition["moving_time"],
                now,
                competition["id"],
            ),
        )

    def add_tombstone(
        self,
        db: Any,
        tombstone_id: str,
        intervals_event_id: Any,
        external_id: Any,
        now: str,
    ) -> None:
        db.execute(
            "INSERT INTO competition_sync_tombstones(id, intervals_event_id, external_id, created_at) VALUES (?, ?, ?, ?)",
            (tombstone_id, intervals_event_id, external_id, now),
        )

    def delete(self, db: Any, competition_id: str) -> None:
        db.execute("DELETE FROM competitions WHERE id=?", (competition_id,))

    def unlink_public_event_candidate(
        self, db: Any, competition_id: str, now: str
    ) -> None:
        db.execute(
            "UPDATE public_event_candidates SET imported_competition_id=NULL, updated_at=? WHERE imported_competition_id=?",
            (now, competition_id),
        )

    def resolve_adopt_remote(
        self,
        db: Any,
        competition_id: str,
        data: dict[str, Any],
        external_id: str,
        now: str,
    ) -> None:
        db.execute(
            "UPDATE competitions SET name=?, event_date=?, start_date_local=?, sport=?, priority=?, category=?, distance=?, target=?, description=?, moving_time=?, notes=?, intervals_event_id=?, external_id=?, sync_dirty=0, sync_state='synced', sync_conflict='', last_synced_at=?, updated_at=? WHERE id=?",
            (
                data["name"],
                data["event_date"],
                data["start_date_local"],
                data["sport"],
                data["priority"],
                data["category"],
                data["distance"],
                data["target"],
                data["description"],
                data["moving_time"],
                data["notes"],
                data["intervals_event_id"],
                external_id,
                now,
                now,
                competition_id,
            ),
        )

    def resolve_keep_local(self, db: Any, competition_id: str, now: str) -> None:
        db.execute(
            "UPDATE competitions SET sync_dirty=1, sync_state='local_override', sync_conflict='', updated_at=? WHERE id=?",
            (now, competition_id),
        )


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


class PlanningStateRepository:
    """Persist the singleton optimistic-concurrency revision."""

    def bump(self, db: Any, amount: int, updated_at: str) -> bool:
        updated = db.execute(
            "UPDATE planning_state SET revision=revision+?, updated_at=? WHERE id=1",
            (int(amount), updated_at),
        )
        return updated.rowcount == 1

    def initialize(self, db: Any, updated_at: str) -> None:
        db.execute(
            "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
            (updated_at,),
        )

    def read(self, db: Any) -> int:
        row = db.execute("SELECT revision FROM planning_state WHERE id=1").fetchone()
        return int((row or {}).get("revision") or 0)


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

    def add(self, db: Any, role: str, content: str, *, client_turn_id: str | None = None) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise ValueError("Chat role must be user or assistant")
        created_at = self._now()
        clean_content = content.strip()
        cursor = db.execute(
            "INSERT INTO messages(role, content, client_turn_id, created_at) VALUES (?, ?, ?, ?)",
            (role, clean_content, client_turn_id, created_at),
        )
        return {"id": cursor.lastrowid, "role": role, "content": clean_content, "client_turn_id": client_turn_id, "created_at": created_at}

    def list(self, db: Any, limit: int = 100) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT id, role, content, client_turn_id, created_at, (SELECT json_group_array(json_extract(value, '$.name')) FROM json_each(messages.attachments)) AS attachment_names FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{key: value for key, value in row.items() if (key != "client_turn_id" or value is not None) and (key != "attachment_names" or value != "[]")} for row in reversed(rows)]


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

    def get(self, db: Any, checkin_date: str) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT soreness, stress, motivation, session_rpe, day_form, illness, pain, "
            "available_minutes, availability_notes, notes "
            "FROM athlete_checkins WHERE checkin_date = ?",
            (checkin_date,),
        ).fetchone()
        return dict(row) if row else None

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


class NutritionRepository:
    """Persist and query logged meals and nutrition totals without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def create(self, db: Any, entry: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        entry_id = str(entry["id"])
        db.execute(
            "INSERT INTO nutrition_logs(id, meal_date, logged_at, meal_type, description, kcal, carbs_g, protein_g, fat_g, source, sync_state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                entry["meal_date"],
                entry["logged_at"],
                entry["meal_type"],
                entry["description"],
                entry["kcal"],
                entry.get("carbs_g"),
                entry.get("protein_g"),
                entry.get("fat_g"),
                entry.get("source", "manual"),
                entry.get("sync_state", "local"),
                now,
                now,
            ),
        )
        return self.get(db, entry_id) or entry

    def get(self, db: Any, entry_id: str) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT id, meal_date, logged_at, meal_type, description, kcal, carbs_g, protein_g, fat_g, source, sync_state, created_at, updated_at "
            "FROM nutrition_logs WHERE id = ?",
            (entry_id,),
        ).fetchone()
        return dict(row) if row else None

    def update(self, db: Any, entry_id: str, entry: dict[str, Any]) -> dict[str, Any] | None:
        now = self._now()
        cursor = db.execute(
            "UPDATE nutrition_logs SET meal_date=?, logged_at=?, meal_type=?, description=?, kcal=?, carbs_g=?, protein_g=?, fat_g=?, source=?, sync_state=?, updated_at=? "
            "WHERE id=?",
            (
                entry["meal_date"],
                entry["logged_at"],
                entry["meal_type"],
                entry["description"],
                entry["kcal"],
                entry.get("carbs_g"),
                entry.get("protein_g"),
                entry.get("fat_g"),
                entry.get("source", "manual"),
                entry.get("sync_state", "local"),
                now,
                entry_id,
            ),
        )
        if cursor.rowcount == 0:
            return None
        return self.get(db, entry_id)

    def delete(self, db: Any, entry_id: str) -> bool:
        cursor = db.execute("DELETE FROM nutrition_logs WHERE id = ?", (entry_id,))
        return cursor.rowcount > 0

    def list_by_date(self, db: Any, meal_date: str) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT id, meal_date, logged_at, meal_type, description, kcal, carbs_g, protein_g, fat_g, source, sync_state, created_at, updated_at "
            "FROM nutrition_logs WHERE meal_date = ? ORDER BY logged_at ASC, created_at ASC",
            (meal_date,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_by_range(self, db: Any, start_date: str, end_date: str) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT id, meal_date, logged_at, meal_type, description, kcal, carbs_g, protein_g, fat_g, source, sync_state, created_at, updated_at "
            "FROM nutrition_logs WHERE meal_date >= ? AND meal_date <= ? ORDER BY meal_date ASC, logged_at ASC",
            (start_date, end_date),
        ).fetchall()
        return [dict(row) for row in rows]

    def day_summary(self, db: Any, meal_date: str) -> dict[str, Any]:
        entries = self.list_by_date(db, meal_date)
        total_kcal = sum(int(e["kcal"]) for e in entries)
        total_carbs = round(sum(float(e["carbs_g"]) for e in entries if e.get("carbs_g") is not None), 1)
        total_protein = round(sum(float(e["protein_g"]) for e in entries if e.get("protein_g") is not None), 1)
        total_fat = round(sum(float(e["fat_g"]) for e in entries if e.get("fat_g") is not None), 1)
        return {
            "date": meal_date,
            "total_kcal": total_kcal,
            "total_carbs_g": total_carbs,
            "total_protein_g": total_protein,
            "total_fat_g": total_fat,
            "entry_count": len(entries),
            "entries": entries,
        }

    def list_unsynced_dates(self, db: Any, limit: int = 14) -> list[str]:
        rows = db.execute(
            "SELECT DISTINCT meal_date FROM nutrition_logs WHERE sync_state != 'synced' ORDER BY meal_date ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [str(row["meal_date"]) for row in rows]

    def mark_date_synced(self, db: Any, meal_date: str, updated_at: str) -> None:
        db.execute(
            "UPDATE nutrition_logs SET sync_state = 'synced', updated_at = ? WHERE meal_date = ?",
            (updated_at, meal_date),
        )
