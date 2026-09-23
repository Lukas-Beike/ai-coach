"""Atomic saving of the athlete profile and target competitions."""

from collections.abc import Callable
from typing import Any

from backend import change_history
from backend.errors import AppError


class AthleteContextService:
    """Persist a normalized athlete profile and its complete competition set."""

    def __init__(
        self,
        manager: Any,
        profile_service: Any,
        competition_repository: Any,
        normalize_profile: Callable[..., dict[str, Any]],
        normalize_competition: Callable[[Any], dict[str, Any]],
        now: Callable[[], str],
        new_id: Callable[[], Any],
    ):
        self.manager = manager
        self.profile_service = profile_service
        self.competition_repository = competition_repository
        self.normalize_profile = normalize_profile
        self.normalize_competition = normalize_competition
        self.now = now
        self.new_id = new_id

    def save(self, profile: Any, competitions: Any) -> dict[str, Any]:
        normalized_profile, normalized_competitions, competition_ids = (
            self._validated_context(profile, competitions)
        )
        now = self.now()
        with self.manager.unit_of_work() as db:
            listed = self.competition_repository.list(db)
            existing = {
                row["id"]: full_row
                for row in listed
                if (full_row := self.competition_repository.get(db, row["id"]))
            }
            retained_ids = set(competition_ids)
            self._record_removed_competition_tombstones(existing, retained_ids, now, db)
            self.profile_service.save_in_transaction(
                normalized_profile, db, already_normalized=True
            )
            for competition in normalized_competitions:
                self._save_competition(competition, existing, now, db)
            self._delete_removed_competitions(
                existing, competition_ids, retained_ids, db
            )
            saved_competitions = self.competition_repository.list(db)
        return {"profile": normalized_profile, "competitions": saved_competitions}

    def _validated_context(
        self, profile: Any, competitions: Any
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        if not isinstance(profile, dict):
            raise AppError(400, "Das Profil muss ein Objekt sein.")
        if not isinstance(competitions, list):
            raise AppError(400, "Wettkämpfe müssen als Liste übergeben werden.")
        if len(competitions) > 20:
            raise AppError(400, "Es können maximal 20 Wettkämpfe gespeichert werden.")
        normalized_profile = self.normalize_profile(profile, validate_timezone=True)
        normalized_competitions = [
            self.normalize_competition(value) for value in competitions
        ]
        competition_ids = [competition["id"] for competition in normalized_competitions]
        if len(competition_ids) != len(set(competition_ids)):
            raise AppError(400, "Wettkampf-IDs müssen eindeutig sein.")
        return normalized_profile, normalized_competitions, competition_ids

    def _record_removed_competition_tombstones(
        self, existing: dict[str, Any], retained_ids: set[str], now: str, db: Any
    ) -> None:
        for removed_id, row in existing.items():
            if removed_id not in retained_ids and (
                row.get("intervals_event_id") or row.get("external_id")
            ):
                db.execute(
                    "INSERT INTO competition_sync_tombstones "
                    "(id, intervals_event_id, external_id, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        str(self.new_id()),
                        row.get("intervals_event_id"),
                        row.get("external_id"),
                        now,
                    ),
                )

    def _save_competition(
        self, competition: dict[str, Any], existing: dict[str, Any], now: str, db: Any
    ) -> None:
        db.execute(
            "INSERT INTO competitions "
            "(id, name, event_date, sport, priority, distance, target, course_profile, "
            "notes, category, start_date_local, description, moving_time, external_id, "
            "sync_dirty, sync_state, sync_conflict, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULLIF(?, ''), 1, "
            "'local', '', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "event_date=excluded.event_date, sport=excluded.sport, "
            "priority=excluded.priority, distance=excluded.distance, "
            "target=excluded.target, course_profile=excluded.course_profile, "
            "notes=excluded.notes, category=excluded.category, "
            "start_date_local=excluded.start_date_local, "
            "description=excluded.description, moving_time=excluded.moving_time, "
            "external_id=COALESCE(excluded.external_id, competitions.external_id), "
            "sync_dirty=1, sync_state='local', sync_conflict='', "
            "updated_at=excluded.updated_at",
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
                competition["external_id"],
                now,
                now,
            ),
        )
        change_history.record_change(
            db,
            "competition",
            competition["id"],
            "create" if competition["id"] not in existing else "update",
            existing.get(competition["id"]),
            {**competition, "sync_state": "local"},
        )

    def _delete_removed_competitions(
        self,
        existing: dict[str, Any],
        competition_ids: list[str],
        retained_ids: set[str],
        db: Any,
    ) -> None:
        for removed_id, row in existing.items():
            if removed_id not in retained_ids:
                change_history.record_change(
                    db, "competition", removed_id, "delete", dict(row), None
                )
        if competition_ids:
            placeholders = ",".join("?" for _ in competition_ids)
            db.execute(
                f"DELETE FROM competitions WHERE id NOT IN ({placeholders})",
                competition_ids,
            )
        else:
            db.execute("DELETE FROM competitions")
