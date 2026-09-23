"""Stage and commit local Coach training-plan artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.errors import AppError
from backend.planning import artifacts as planning_artifacts
from backend.planning import workouts as planning_workouts


class TrainingPlanArtifactService:
    """Own the local artifact lifecycle and its atomic plan commit."""

    def __init__(
        self,
        database_manager: Any,
        local_plan_creation_service: Any,
        today: Callable[[], date],
        now: Callable[[], str],
        id_factory: Callable[[], Any],
    ) -> None:
        self._database_manager = database_manager
        self._local_plan_creation_service = local_plan_creation_service
        self._today = today
        self._now = now
        self._id_factory = id_factory

    def stage(
        self, arguments: dict[str, Any], conversation_id: str, client_turn_id: str
    ) -> dict[str, Any]:
        payload = planning_artifacts.structured_artifact_payload(arguments)
        planning_artifacts.validate_structured_plan_limits(payload)
        payload = {
            **payload,
            "workouts": [
                planning_workouts.normalize_workout(workout, today=self._today())
                for workout in payload["workouts"]
            ],
        }

        # Calendar validation is read-only and must complete before an artifact
        # is inserted, so a rejected draft leaves no durable state behind.
        self._local_plan_creation_service.validate_calendar(payload["workouts"])

        with self._database_manager.unit_of_work() as db:
            revision_row = db.execute(
                "SELECT revision FROM planning_state WHERE id=1"
            ).fetchone()
            base_revision = int((revision_row or {}).get("revision") or 0)
            artifact_id = str(self._id_factory())
            now = self._now()
            db.execute(
                "INSERT INTO coach_plan_artifacts "
                "(id, conversation_id, client_turn_id, base_revision, status, payload, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
                (
                    artifact_id,
                    conversation_id,
                    client_turn_id,
                    base_revision,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    now,
                    now,
                ),
            )
        return {
            "ok": True,
            "status": "draft",
            "artifact_id": artifact_id,
            "base_revision": base_revision,
        }

    def commit(
        self,
        artifact_id: str,
        conversation_id: str,
        *,
        explicit_artifact: bool = False,
    ) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            artifact = db.execute(
                "SELECT * FROM coach_plan_artifacts WHERE id=?", (artifact_id,)
            ).fetchone()
            if not artifact:
                raise AppError(
                    404, "Planartefakt nicht gefunden.", reason="artifact_not_found"
                )
            if artifact["status"] == "committed":
                return {
                    "ok": True,
                    "status": "already_applied",
                    "artifact_id": artifact_id,
                }
            if artifact["status"] != "draft":
                raise AppError(
                    409,
                    "Das Planartefakt ist nicht mehr verfügbar.",
                    reason="artifact_not_available",
                )

            self._validate_committed_artifact(
                db,
                artifact,
                artifact_id,
                conversation_id,
                explicit_artifact=explicit_artifact,
            )
            # Keep JSON parsing errors visible; a corrupt persisted payload is
            # not a new, defaultable empty plan.
            payload = json.loads(artifact["payload"] or "{}")
            planning_artifacts.validate_structured_plan_limits(payload)
            entries = self._local_plan_creation_service.save(
                payload.get("workouts") or [],
                plan_name=str(payload.get("plan_name") or "Coach-Plan"),
                goal=str(payload.get("goal") or ""),
                db=db,
            )
            updated = db.execute(
                "UPDATE coach_plan_artifacts SET status='committed', updated_at=? "
                "WHERE id=? AND conversation_id=? AND status='draft'",
                (self._now(), artifact_id, conversation_id),
            )
            if updated.rowcount != 1:
                raise AppError(
                    409,
                    "Das Planartefakt wurde inzwischen verarbeitet.",
                    reason="artifact_revision_conflict",
                )
            return {
                "ok": True,
                "status": "committed",
                "artifact_id": artifact_id,
                "library_entry_ids": [entry["id"] for entry in entries],
            }

    def _validate_committed_artifact(
        self,
        db: Any,
        artifact: dict[str, Any],
        artifact_id: str,
        conversation_id: str,
        *,
        explicit_artifact: bool,
    ) -> None:
        if str(artifact.get("conversation_id") or "") != str(conversation_id):
            if not explicit_artifact:
                raise AppError(
                    409,
                    "Der Planentwurf gehört zu einer anderen Coach-Unterhaltung; bitte bestätige die Artefakt-ID.",
                    reason="artifact_conversation_conflict",
                )
            db.execute(
                "UPDATE coach_plan_artifacts SET conversation_id=?, updated_at=? "
                "WHERE id=? AND status='draft'",
                (conversation_id, self._now(), artifact_id),
            )

        revision_row = db.execute(
            "SELECT revision FROM planning_state WHERE id=1"
        ).fetchone()
        current_revision = int((revision_row or {}).get("revision") or 0)
        if int(artifact["base_revision"] or 0) != current_revision:
            raise AppError(
                409,
                "Der lokale Plan wurde inzwischen geändert.",
                reason="planning_revision_conflict",
            )
