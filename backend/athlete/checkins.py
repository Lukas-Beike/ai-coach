"""Pure athlete check-in validation and normalization helpers."""

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.db.repositories import CheckinRepository
from backend.errors import AppError

CHECKIN_TEXT_LIMITS = {
    "day_form": 2000,
    "illness": 1000,
    "pain": 1000,
    "availability_notes": 2000,
    "notes": 4000,
}
CHECKIN_SCORE_FIELDS = ("soreness", "stress", "motivation", "session_rpe")
CHECKIN_TAGS = ("travel", "late_meal", "high_stress")
CHECKIN_DAY_STATUSES = ("unknown", "rest", "pause")


def bounded_score(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(400, "Lokale Feedback-Werte müssen ganze Zahlen sein.") from exc
    if not 0 <= number <= 10:
        raise AppError(400, "Lokale Feedback-Werte müssen zwischen 0 und 10 liegen.")
    return number


def bounded_minutes(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(
            400, "Die verfügbare Trainingszeit muss eine ganze Zahl sein."
        ) from exc
    if not 0 <= number <= 1440:
        raise AppError(
            400, "Die verfügbare Trainingszeit muss zwischen 0 und 1440 Minuten liegen."
        )
    return number


def normalize_checkin(value: Any, *, today: date) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError(400, "Das lokale Feedback muss ein Objekt sein.")
    raw_date = str(value.get("checkin_date") or today.isoformat()).strip()
    try:
        checkin_date = date.fromisoformat(raw_date).isoformat()
    except ValueError as exc:
        raise AppError(400, "Das Datum des lokalen Feedbacks ist ungültig.") from exc
    if checkin_date > today.isoformat():
        raise AppError(400, "Ein Tages-Check-in kann nicht in der Zukunft liegen.")
    result: dict[str, Any] = {"checkin_date": checkin_date}
    if "day_status" in value:
        if value["day_status"] not in CHECKIN_DAY_STATUSES:
            raise AppError(
                400,
                "Tagesstatus muss unbekannt, Ruhetag oder bestätigte Trainingspause sein.",
            )
        result["day_status"] = value["day_status"]
    if "tag_answers" in value:
        answers = value["tag_answers"]
        if (
            not isinstance(answers, dict)
            or set(answers) - set(CHECKIN_TAGS)
            or any(type(answer) is not bool for answer in answers.values())
        ):
            raise AppError(
                400, "Tags benötigen ausdrücklich bestätigte Ja-/Nein-Angaben."
            )
        result["tag_answers"] = dict(answers)
    for field in CHECKIN_SCORE_FIELDS:
        result[field] = bounded_score(value.get(field))
    result["available_minutes"] = bounded_minutes(value.get("available_minutes"))
    for field, limit in CHECKIN_TEXT_LIMITS.items():
        result[field] = str(value.get(field) or "").strip()[:limit]
    return result


class CheckinService:
    """Coordinate local athlete check-in use cases and their transactions."""

    def __init__(
        self,
        manager: Any,
        repository: CheckinRepository,
        today: Callable[[], date],
    ):
        self._manager = manager
        self._repository = repository
        self._today = today

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 365))
        with self._manager.unit_of_work() as db:
            rows = self._repository.list(db, bounded_limit)
            for row in rows:
                tags = db.execute(
                    "SELECT value FROM kv WHERE key=?",
                    ("checkin_tags:" + row["checkin_date"],),
                ).fetchone()
                if tags:
                    row["tag_answers"] = json.loads(tags["value"])
                status = db.execute(
                    "SELECT value FROM kv WHERE key=?",
                    ("checkin_day_status:" + row["checkin_date"],),
                ).fetchone()
                if status:
                    row["day_status"] = json.loads(status["value"])
            return rows

    def _save_normalized(self, checkin: dict[str, Any]) -> dict[str, Any]:
        with self._manager.unit_of_work() as db:
            self._repository.upsert(db, checkin)
            if "day_status" in checkin:
                db.execute(
                    "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                    (
                        "checkin_day_status:" + checkin["checkin_date"],
                        json.dumps(checkin["day_status"]),
                        self._today().isoformat(),
                    ),
                )
            if "tag_answers" in checkin:
                db.execute(
                    "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                    (
                        "checkin_tags:" + checkin["checkin_date"],
                        json.dumps(checkin["tag_answers"]),
                        self._today().isoformat(),
                    ),
                )
        saved = next(
            (
                item
                for item in self.list(365)
                if item["checkin_date"] == checkin["checkin_date"]
            ),
            checkin,
        )
        return {"status": "ok", "checkin": saved}

    def save(self, value: Any) -> dict[str, Any]:
        checkin = normalize_checkin(value, today=self._today())
        return self._save_normalized(checkin)

    def save_coach(self, arguments: Any) -> dict[str, Any]:
        """Save a coach-supplied check-in while preserving omitted edit fields."""
        if not isinstance(arguments, dict):
            raise AppError(400, "Der Tages-Check-in muss als Objekt gesendet werden.")
        value = dict(arguments)
        for field in CHECKIN_SCORE_FIELDS + ("available_minutes",):
            if value.get(field) == -1:
                value[field] = None
        normalized = normalize_checkin(value, today=self._today())
        with self._manager.unit_of_work() as db:
            existing = self._repository.get(db, normalized["checkin_date"])
        if existing:
            for field in CHECKIN_SCORE_FIELDS + (
                "available_minutes",
                "day_form",
                "illness",
                "pain",
                "availability_notes",
                "notes",
            ):
                if normalized[field] in (None, ""):
                    normalized[field] = existing[field]
        return {"stored_locally": True, **self._save_normalized(normalized)}

    def context(self) -> dict[str, Any]:
        checkins = self.list()
        today = self._today().isoformat()
        return {
            "today": next(
                (item for item in checkins if item["checkin_date"] == today), None
            ),
            "recent": checkins[:14],
            "scope": "Only athlete-entered subjective feedback and constraints; wearable/provider values remain in their source sections.",
        }
