"""Explicit persistence interfaces for application repositories."""

from __future__ import annotations

import builtins
import json
from collections.abc import Callable
from typing import Any


class NutritionTemplateRepository:
    """Persist reusable meals separately from consumed nutrition records."""

    def list(self, db: Any) -> list[dict[str, Any]]:
        return [
            json.loads(row["payload"])
            for row in db.execute(
                "SELECT payload FROM nutrition_templates ORDER BY name COLLATE NOCASE"
            ).fetchall()
        ]

    def get(self, db: Any, template_id: str) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT payload FROM nutrition_templates WHERE id=?", (template_id,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def save(self, db: Any, template: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO nutrition_templates(id, name, payload, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, payload=excluded.payload, updated_at=excluded.updated_at",
            (
                template["id"],
                template["name"],
                json.dumps(template, ensure_ascii=False),
                template["updated_at"],
            ),
        )

    def delete(self, db: Any, template_id: str) -> bool:
        return (
            db.execute(
                "DELETE FROM nutrition_templates WHERE id=?", (template_id,)
            ).rowcount
            > 0
        )


class NutritionProductRepository:
    """Persist athlete-confirmed food products independently from meal logs."""

    _SELECT = (
        "SELECT id, barcode, name, brand, basis_amount, basis_unit, kcal, carbs_g, "
        "protein_g, fat_g, sugar_g, fiber_g, salt_g, source, source_url, external_id, "
        "provenance, extraction_confidence, status, created_at, updated_at FROM nutrition_products"
    )

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        product = dict(row)
        try:
            product["provenance"] = json.loads(product["provenance"])
        except KeyError, TypeError, ValueError:
            product["provenance"] = {"kind": product.get("source", "manual")}
        return product

    def list(
        self,
        db: Any,
        *,
        query: str | None = None,
        barcode: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_archived:
            clauses.append("status = 'active'")
        if barcode:
            clauses.append("barcode = ?")
            params.append(barcode)
        if query:
            clauses.append(
                "(name LIKE ? COLLATE NOCASE OR brand LIKE ? COLLATE NOCASE)"
            )
            pattern = f"%{query}%"
            params.extend((pattern, pattern))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = db.execute(
            self._SELECT
            + where
            + " ORDER BY updated_at DESC, name COLLATE NOCASE LIMIT ?",
            (*params, max(1, min(int(limit), 100))),
        ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, db: Any, product_id: str) -> dict[str, Any] | None:
        row = db.execute(self._SELECT + " WHERE id = ?", (product_id,)).fetchone()
        return self._row(row) if row else None

    def save(self, db: Any, product: dict[str, Any]) -> dict[str, Any]:
        columns = (
            "id",
            "barcode",
            "name",
            "brand",
            "basis_amount",
            "basis_unit",
            "kcal",
            "carbs_g",
            "protein_g",
            "fat_g",
            "sugar_g",
            "fiber_g",
            "salt_g",
            "source",
            "source_url",
            "external_id",
            "provenance",
            "extraction_confidence",
            "status",
            "created_at",
            "updated_at",
        )
        db.execute(
            "INSERT INTO nutrition_products("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ") ON CONFLICT(id) DO UPDATE SET "
            + ",".join(
                f"{column}=excluded.{column}" for column in columns if column != "id"
            ),
            tuple(
                json.dumps(product.get(column), ensure_ascii=False)
                if column == "provenance"
                else product.get(column)
                for column in columns
            ),
        )
        return self.get(db, str(product["id"])) or product

    def archive(self, db: Any, product_id: str, updated_at: str) -> bool:
        return (
            db.execute(
                "UPDATE nutrition_products SET status='archived', updated_at=? WHERE id=? AND status='active'",
                (updated_at, product_id),
            ).rowcount
            > 0
        )


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


class SessionRepository:
    """Persist authentication sessions without owning their transaction."""

    def cleanup_expired(self, db: Any, now: float, limit: int) -> int:
        return db.execute(
            "DELETE FROM sessions WHERE token_hash IN ("
            "SELECT token_hash FROM sessions WHERE expires_at <= ? LIMIT ?"
            ")",
            (now, limit),
        ).rowcount

    def get(self, db: Any, token_hash: str) -> Any:
        return db.execute(
            "SELECT csrf_hash, expires_at, last_seen FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()

    def delete(self, db: Any, token_hash: str) -> None:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def touch(self, db: Any, token_hash: str, last_seen: str) -> None:
        db.execute(
            "UPDATE sessions SET last_seen = ? WHERE token_hash = ?",
            (last_seen, token_hash),
        )

    def create(
        self,
        db: Any,
        token_hash: str,
        csrf_hash: str,
        expires_at: float,
        created_at: str,
        last_seen: str,
    ) -> None:
        db.execute(
            "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (token_hash, csrf_hash, expires_at, created_at, last_seen),
        )

    def list_csrf(self, db: Any) -> list[Any]:
        return db.execute("SELECT csrf_hash, expires_at FROM sessions").fetchall()


class LibraryPageRepository:
    """Read deterministic pages of active, undated library templates."""

    def page(self, db: Any, cursor: list[str] | None, limit: int) -> list[Any]:
        after_clause = ""
        params: list[Any] = []
        if cursor is not None:
            after_clause = "WHERE (sport_key, name_key, id) > (?, ?, ?)"
            params.extend(cursor)
        return db.execute(
            "WITH templates AS ("
            "SELECT id, payload, lower(COALESCE(json_extract(payload, '$.type'), '')) AS sport_key, "
            "lower(COALESCE(json_extract(payload, '$.name'), '')) AS name_key "
            "FROM workout_library WHERE json_valid(payload) AND json_type(payload)='object' "
            "AND json_extract(payload, '$.date') IS NULL AND COALESCE(json_extract(payload, '$.archived'), 0)=0) "
            f"SELECT id, payload, sport_key, name_key FROM templates {after_clause} "
            "ORDER BY sport_key, name_key, id LIMIT ?",
            (*params, limit),
        ).fetchall()


class ReadinessRepository:
    """Provide the minimal persistence probe used by readiness checks."""

    def database_available(self, db: Any) -> bool:
        return bool(db.execute("SELECT 1").fetchone())


class StateVersionRepository:
    """Read compact counters used to version public state projections."""

    def counters(self, db: Any) -> dict[str, Any]:
        return {
            "message": db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(id), 0) AS latest FROM messages"
            ).fetchone(),
            "library": db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest "
                "FROM workout_library WHERE json_extract(payload, '$.date') IS NULL"
            ).fetchone(),
            "planned": db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest "
                "FROM planned_units"
            ).fetchone(),
            "checkins": db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest "
                "FROM athlete_checkins"
            ).fetchone(),
            "feedback": db.execute(
                "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS latest "
                "FROM activity_feedback"
            ).fetchone(),
        }


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

    def create_preview(
        self, db: Any, adjustment_id: str, payload: str, created_at: str
    ) -> None:
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
            "SELECT payload, status FROM plan_adjustments ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, db: Any, adjustment_id: str) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT payload, status FROM plan_adjustments WHERE id = ?",
            (adjustment_id,),
        ).fetchone()
        return dict(row) if row else None

    def mark_applied(
        self, db: Any, adjustment_id: str, payload: str, status: str, applied_at: str
    ) -> None:
        db.execute(
            "UPDATE plan_adjustments SET payload=?, status=?, applied_at=? WHERE id=?",
            (payload, status, applied_at, adjustment_id),
        )


class ChatRepository:
    """Persist and retrieve local chat messages without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def add(
        self, db: Any, role: str, content: str, *, client_turn_id: str | None = None
    ) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise ValueError("Chat role must be user or assistant")
        created_at = self._now()
        clean_content = content.strip()
        cursor = db.execute(
            "INSERT INTO messages(role, content, client_turn_id, created_at) VALUES (?, ?, ?, ?)",
            (role, clean_content, client_turn_id, created_at),
        )
        return {
            "id": cursor.lastrowid,
            "role": role,
            "content": clean_content,
            "client_turn_id": client_turn_id,
            "created_at": created_at,
        }

    def list(self, db: Any, limit: int = 100) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT id, role, content, client_turn_id, created_at, (SELECT json_group_array(json_extract(value, '$.name')) FROM json_each(messages.attachments)) AS attachment_names FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                key: value
                for key, value in row.items()
                if (key != "client_turn_id" or value is not None)
                and (key != "attachment_names" or value != "[]")
            }
            for row in reversed(rows)
        ]

    def list_page(
        self,
        db: Any,
        *,
        before_message_id: int | None,
        search: str,
        limit: int,
    ) -> builtins.list[dict[str, Any]]:
        params: list[Any] = []
        clauses: list[str] = []
        if search:
            clauses.append("content LIKE ? ESCAPE '\\'")
            escaped = (
                search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            params.append(f"%{escaped}%")
        if before_message_id is not None:
            clauses.append("id < ?")
            params.append(before_message_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = db.execute(
            "SELECT id, role, content, client_turn_id, created_at, "
            "(SELECT json_group_array(json_extract(value, '$.name')) "
            "FROM json_each(messages.attachments)) AS attachment_names "
            f"FROM messages{where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [
            {
                key: value
                for key, value in row.items()
                if (key != "client_turn_id" or value is not None)
                and (key != "attachment_names" or value != "[]")
            }
            for row in rows
        ]


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
                checkin["checkin_date"],
                checkin["soreness"],
                checkin["stress"],
                checkin["motivation"],
                checkin["session_rpe"],
                checkin["day_form"],
                checkin["illness"],
                checkin["pain"],
                checkin["available_minutes"],
                checkin["availability_notes"],
                checkin["notes"],
                now,
                now,
            ),
        )


class ActivityFeedbackRepository:
    """Persist athlete notes about completed activities without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def list(self, db: Any, limit: int = 100) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT activity_id, activity_name, activity_date, notes, session_rpe, deviation_reason, created_at, updated_at "
            "FROM activity_feedback ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, db: Any, activity_id: str) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT * FROM activity_feedback WHERE activity_id=?", (activity_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete(self, db: Any, activity_id: str) -> None:
        db.execute(
            "DELETE FROM activity_feedback WHERE activity_id = ?", (activity_id,)
        )

    def upsert(self, db: Any, feedback: dict[str, Any]) -> None:
        now = self._now()
        db.execute(
            "INSERT INTO activity_feedback(activity_id, activity_name, activity_date, notes, session_rpe, deviation_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(activity_id) DO UPDATE SET activity_name=excluded.activity_name, "
            "activity_date=excluded.activity_date, notes=excluded.notes, session_rpe=excluded.session_rpe, deviation_reason=excluded.deviation_reason, updated_at=excluded.updated_at",
            (
                feedback["activity_id"],
                feedback["activity_name"],
                feedback["activity_date"],
                feedback["notes"],
                feedback.get("session_rpe"),
                feedback.get("deviation_reason", ""),
                now,
                now,
            ),
        )


class SnapshotRepository:
    """Persist bounded provider snapshots without owning a connection."""

    def save(
        self, db: Any, snapshot: dict[str, Any], created_at: str, *, keep: int = 12
    ) -> None:
        recent = snapshot.get("recent_activities")
        db.execute(
            "INSERT INTO snapshots(payload, created_at, synced_at, recent_activity_count) "
            "VALUES (?, ?, ?, ?)",
            (
                json.dumps(snapshot, ensure_ascii=False),
                created_at,
                str(snapshot.get("synced_at") or ""),
                len(recent) if isinstance(recent, list) else 0,
            ),
        )
        db.execute(
            "DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)",
            (keep,),
        )

    def latest_metadata(self, db: Any) -> dict[str, Any]:
        row = db.execute(
            "SELECT synced_at, recent_activity_count FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else {}

    def latest_payload(self, db: Any) -> str | None:
        row = db.execute(
            "SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["payload"] if row else None


NUTRITION_MACRO_FIELDS = ("carbs_g", "protein_g", "fat_g")
_NUTRITION_ENTRY_COLUMNS = (
    "id, meal_date, logged_at, meal_type, description, kcal, carbs_g, protein_g, "
    "fat_g, source, nutrition_basis, sync_state, created_at, updated_at, "
    "logged_time_known"
)


def nutrition_macro_totals(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Return complete daily macro totals and display-only sums of known values.

    A total_* field stays None unless every entry reports that macro, so sync,
    approval and Coach context never treat a partial sum as a daily total.
    """
    totals: dict[str, Any] = {}
    known_totals: dict[str, float | None] = {}
    for field in NUTRITION_MACRO_FIELDS:
        known = [
            float(entry[field]) for entry in entries if entry.get(field) is not None
        ]
        known_totals[field] = round(sum(known), 1) if known else None
        totals[f"total_{field}"] = (
            round(sum(known), 1) if len(known) == len(entries) else None
        )
    totals["known_macro_totals"] = known_totals
    totals["entries_without_macros"] = sum(
        1
        for entry in entries
        if any(entry.get(field) is None for field in NUTRITION_MACRO_FIELDS)
    )
    return totals


class NutritionRepository:
    """Persist and query logged meals and nutrition totals without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    @staticmethod
    def _entry(row: Any) -> dict[str, Any]:
        entry = dict(row)
        entry["nutrition_basis"] = json.loads(entry["nutrition_basis"])
        entry["logged_time_known"] = bool(entry["logged_time_known"])
        return entry

    def create(self, db: Any, entry: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        entry_id = str(entry["id"])
        db.execute(
            "INSERT INTO nutrition_logs(id, meal_date, logged_at, meal_type, description, kcal, carbs_g, protein_g, fat_g, source, nutrition_basis, sync_state, created_at, updated_at, logged_time_known) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                json.dumps(entry.get("nutrition_basis") or {}, ensure_ascii=False),
                entry.get("sync_state", "local"),
                now,
                now,
                1 if entry.get("logged_time_known", True) else 0,
            ),
        )
        self._mark_pending(db, entry["meal_date"], now)
        return self.get(db, entry_id) or entry

    def get(self, db: Any, entry_id: str) -> dict[str, Any] | None:
        row = db.execute(
            f"SELECT {_NUTRITION_ENTRY_COLUMNS} FROM nutrition_logs WHERE id = ?",
            (entry_id,),
        ).fetchone()
        return self._entry(row) if row else None

    def update(
        self, db: Any, entry_id: str, entry: dict[str, Any]
    ) -> dict[str, Any] | None:
        now = self._now()
        existing = self.get(db, entry_id)
        if not existing:
            return None
        cursor = db.execute(
            "UPDATE nutrition_logs SET meal_date=?, logged_at=?, meal_type=?, description=?, kcal=?, carbs_g=?, protein_g=?, fat_g=?, source=?, nutrition_basis=?, sync_state=?, logged_time_known=?, updated_at=? "
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
                json.dumps(entry.get("nutrition_basis") or {}, ensure_ascii=False),
                entry.get("sync_state", "local"),
                1 if entry.get("logged_time_known", True) else 0,
                now,
                entry_id,
            ),
        )
        if cursor.rowcount == 0:
            return None
        self._mark_pending(db, existing["meal_date"], now)
        self._mark_pending(db, entry["meal_date"], now)
        return self.get(db, entry_id)

    def delete(self, db: Any, entry_id: str) -> bool:
        existing = self.get(db, entry_id)
        if not existing:
            return False
        cursor = db.execute("DELETE FROM nutrition_logs WHERE id = ?", (entry_id,))
        if cursor.rowcount:
            self._mark_pending(db, existing["meal_date"], self._now())
        return cursor.rowcount > 0

    def list_by_date(self, db: Any, meal_date: str) -> list[dict[str, Any]]:
        rows = db.execute(
            f"SELECT {_NUTRITION_ENTRY_COLUMNS} "
            "FROM nutrition_logs WHERE meal_date = ? ORDER BY logged_at ASC, created_at ASC",
            (meal_date,),
        ).fetchall()
        return [self._entry(row) for row in rows]

    def list_by_range(
        self, db: Any, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        rows = db.execute(
            f"SELECT {_NUTRITION_ENTRY_COLUMNS} "
            "FROM nutrition_logs WHERE meal_date >= ? AND meal_date <= ? ORDER BY meal_date ASC, logged_at ASC",
            (start_date, end_date),
        ).fetchall()
        return [self._entry(row) for row in rows]

    def day_summary(self, db: Any, meal_date: str) -> dict[str, Any]:
        entries = self.list_by_date(db, meal_date)
        return {
            "date": meal_date,
            "total_kcal": sum(int(e["kcal"]) for e in entries),
            **nutrition_macro_totals(entries),
            "entry_count": len(entries),
            "entries": entries,
        }

    def list_unsynced_dates(self, db: Any, limit: int = 14) -> list[str]:
        rows = db.execute(
            "SELECT meal_date FROM nutrition_sync_dates WHERE sync_state = 'pending' ORDER BY meal_date ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [str(row["meal_date"]) for row in rows]

    def day_sync_snapshot(
        self, db: Any, meal_date: str, *, create_if_missing: bool = True
    ) -> dict[str, Any]:
        if create_if_missing:
            db.execute(
                "INSERT OR IGNORE INTO nutrition_sync_dates(meal_date, revision, sync_state, updated_at) "
                "VALUES (?, 1, 'pending', ?)",
                (meal_date, self._now()),
            )
        snapshot = self.day_summary(db, meal_date)
        row = db.execute(
            "SELECT revision FROM nutrition_sync_dates WHERE meal_date = ?",
            (meal_date,),
        ).fetchone()
        snapshot["sync_revision"] = int(row["revision"]) if row else 0
        return snapshot

    def mark_date_synced(
        self, db: Any, meal_date: str, revision: int, updated_at: str
    ) -> bool:
        cursor = db.execute(
            "UPDATE nutrition_sync_dates SET sync_state = 'synced', updated_at = ? "
            "WHERE meal_date = ? AND revision = ?",
            (updated_at, meal_date, revision),
        )
        if cursor.rowcount:
            db.execute(
                "UPDATE nutrition_logs SET sync_state = 'synced', updated_at = ? WHERE meal_date = ?",
                (updated_at, meal_date),
            )
        return bool(cursor.rowcount)

    def _mark_pending(self, db: Any, meal_date: str, updated_at: str) -> None:
        db.execute(
            "INSERT INTO nutrition_sync_dates(meal_date, revision, sync_state, updated_at) "
            "VALUES (?, 1, 'pending', ?) "
            "ON CONFLICT(meal_date) DO UPDATE SET revision=revision+1, "
            "sync_state='pending', updated_at=excluded.updated_at",
            (meal_date, updated_at),
        )
