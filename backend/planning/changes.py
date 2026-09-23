"""Transaction-scoped application of structured planning changes."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.db.repositories import PlanningStateRepository
from backend.errors import (
    INVALID_PLANNING_DATE_ERROR,
    STALE_PLANNING_REVISION_ERROR,
    AppError,
)
from backend.planning import library as planning_library
from backend.planning.workouts import normalize_workout


def validated_training_date(value: Any) -> str:
    candidate_date = str(value or "").strip()[:10]
    try:
        date.fromisoformat(candidate_date)
    except ValueError as exc:
        raise AppError(
            400, INVALID_PLANNING_DATE_ERROR, reason="invalid_change"
        ) from exc
    return candidate_date


def prepare_structured_training_change(
    change: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    action = str(change.get("action") or "update").strip().casefold()
    if action != "create":
        return change
    if change.get("local_id"):
        raise AppError(
            400,
            "Eine neue geplante Einheit darf keine lokale ID vorgeben.",
            reason="invalid_change",
        )
    required_fields = (
        "date",
        "sport",
        "name",
        "description",
        "duration_minutes",
        "target",
        "rationale",
    )
    missing_fields = [
        field
        for field in required_fields
        if field not in change
        or change[field] is None
        or (isinstance(change[field], str) and not change[field].strip())
    ]
    if missing_fields:
        raise AppError(
            400,
            "Eine neue geplante Einheit benötigt alle Workout-Felder.",
            reason="invalid_change",
        )
    if change.get("target") not in {"AUTO", "POWER", "HR", "PACE"}:
        raise AppError(
            400,
            "Das Workout-Ziel muss AUTO, POWER, HR oder PACE sein.",
            reason="invalid_change",
        )
    normalized = normalize_workout(change, today=today)
    prepared = {
        "action": "create",
        **{
            key: normalized[key]
            for key in (
                "date",
                "sport",
                "name",
                "description",
                "duration_minutes",
                "target",
                "rationale",
            )
        },
    }
    if "plan_id" in change:
        prepared["plan_id"] = str(change.get("plan_id") or "").strip()
    return prepared


def prepare_structured_training_changes(
    arguments: dict[str, Any],
    *,
    today: date,
    max_changes: int,
) -> list[dict[str, Any]]:
    changes = arguments.get("changes") or []
    if not isinstance(changes, list) or not changes or len(changes) > max_changes:
        raise AppError(
            400,
            f"Ein Coach-Kommando darf höchstens {max_changes} Änderungen enthalten.",
            reason="change_limit",
        )
    prepared = []
    for change in changes:
        if not isinstance(change, dict):
            raise AppError(
                400, "Jede Planänderung muss ein Objekt sein.", reason="invalid_change"
            )
        prepared.append(prepare_structured_training_change(change, today=today))
    return prepared


class StructuredTrainingChangeValidator:
    """Validate a structured change batch on the caller's transaction."""

    def __init__(
        self,
        planning_state_repository: PlanningStateRepository,
        calendar_conflict_service: Any,
    ) -> None:
        self.planning_state_repository = planning_state_repository
        self.calendar_conflict_service = calendar_conflict_service

    @staticmethod
    def _record_created_training_change(
        change: dict[str, Any],
        change_identity: str,
        final_dates: dict[str, str],
        final_active: dict[str, bool],
    ) -> None:
        candidate_date = str(change.get("date") or "").strip()[:10]
        if not candidate_date:
            raise AppError(
                400,
                "Eine neue geplante Einheit benötigt ein Datum.",
                reason="invalid_change",
            )
        final_dates[change_identity] = validated_training_date(candidate_date)
        final_active[change_identity] = True

    @staticmethod
    def _record_existing_training_change(
        change: dict[str, Any],
        change_identity: str,
        db: Any,
        original_dates: dict[str, str],
        final_dates: dict[str, str],
        final_active: dict[str, bool],
        restore_identities: set[str],
    ) -> None:
        action = str(change.get("action") or "update").strip().casefold()
        if action == "restore":
            restore_identities.add(change_identity)
        local_id = str(change.get("local_id") or "").strip()
        row = db.execute(
            "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
        ).fetchone()
        if not row:
            return
        try:
            current = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            current = {}
        if not isinstance(current, dict):
            return
        current_date = str(current.get("date") or "").strip()[:10]
        if current_date:
            original_dates.setdefault(change_identity, current_date)
        final_active.setdefault(
            change_identity,
            not bool(current.get("archived"))
            and not bool(current.get("local_deleted")),
        )
        if action in {"delete", "archive"}:
            final_active[change_identity] = False
            return
        if action == "restore":
            final_active[change_identity] = True
        candidate_date = str(
            change.get("date")
            or final_dates.get(change_identity)
            or current.get("date")
            or ""
        ).strip()[:10]
        if candidate_date:
            final_dates[change_identity] = validated_training_date(candidate_date)

    def _validate_training_change_dates(
        self,
        final_dates: dict[str, str],
        final_active: dict[str, bool],
        original_dates: dict[str, str],
        restore_identities: set[str],
        batch_ids: set[str],
    ) -> None:
        occupied_dates: dict[str, str] = {}
        for change_identity, candidate_date in final_dates.items():
            if not final_active.get(change_identity, True):
                continue
            previous_identity = occupied_dates.get(candidate_date)
            if previous_identity is not None and previous_identity != change_identity:
                raise AppError(
                    409,
                    f"Der Plan enthält mehrere Einheiten für den {candidate_date}; pro Tag ist eine Einheit möglich.",
                    reason="plan_date_conflict",
                )
            occupied_dates[candidate_date] = change_identity
        dates_needing_calendar_check = {
            candidate_date
            for change_identity, candidate_date in final_dates.items()
            if final_active.get(change_identity, True)
            and (
                change_identity.startswith("create:")
                or original_dates.get(change_identity) != candidate_date
                or change_identity in restore_identities
            )
        }
        for candidate_date in dates_needing_calendar_check:
            if self.calendar_conflict_service.conflicts(
                {"date": candidate_date}, batch_ids
            ):
                raise AppError(
                    409,
                    f"Für den {candidate_date} existiert bereits eine lokale Kalendereinheit.",
                    reason="plan_date_conflict",
                )

    def _validate_training_change_batch(
        self, changes: list[dict[str, Any]], db: Any
    ) -> None:
        """Validate all final dates before applying any member of a batch."""
        batch_ids = {str(change.get("local_id") or "").strip() for change in changes}
        batch_ids.discard("")
        original_dates: dict[str, str] = {}
        final_dates: dict[str, str] = {}
        final_active: dict[str, bool] = {}
        restore_identities: set[str] = set()
        for index, change in enumerate(changes):
            local_id = str(change.get("local_id") or "").strip()
            change_identity = local_id or f"create:{index}"
            if str(change.get("action") or "update").strip().casefold() == "create":
                self._record_created_training_change(
                    change, change_identity, final_dates, final_active
                )
                continue
            self._record_existing_training_change(
                change,
                change_identity,
                db,
                original_dates,
                final_dates,
                final_active,
                restore_identities,
            )
        self._validate_training_change_dates(
            final_dates,
            final_active,
            original_dates,
            restore_identities,
            batch_ids,
        )

    def validate_batch(self, changes: list[dict[str, Any]], db: Any) -> None:
        """Validate final batch dates without revision or payload-hash checks."""
        self._validate_training_change_batch(changes, db)

    def _validate_structured_training_revision(
        self, arguments: dict[str, Any], *, require_revision: bool, db: Any
    ) -> int:
        current_revision = self.planning_state_repository.read(db)
        expected_revision = arguments.get("expected_revision")
        if require_revision and expected_revision is None:
            raise AppError(
                400,
                "Eine vollständige Planänderung benötigt die gelesene Planrevision.",
                reason="planning_revision_required",
            )
        if expected_revision is not None and int(expected_revision) != current_revision:
            raise AppError(
                409,
                STALE_PLANNING_REVISION_ERROR,
                reason="planning_revision_conflict",
            )
        return current_revision

    @staticmethod
    def _validate_structured_training_change_hash(
        change: dict[str, Any], *, require_revision: bool, db: Any
    ) -> None:
        if not change.get("local_id"):
            raise AppError(
                400,
                "Jede Planänderung benötigt eine lokale ID.",
                reason="invalid_change",
            )
        expected_hash = str(change.get("expected_payload_hash") or "").strip().lower()
        if require_revision and not re.fullmatch(
            planning_library.PAYLOAD_HASH_PATTERN, expected_hash
        ):
            raise AppError(
                400,
                "Eine vollständige Planänderung benötigt aktuelle Payload-Hashes.",
                reason="payload_hash_required",
            )
        if expected_hash:
            row = db.execute(
                "SELECT payload FROM planned_units WHERE local_id=?",
                (str(change["local_id"]),),
            ).fetchone()
            if (
                not row
                or planning_library.library_payload_hash(row["payload"])
                != expected_hash
            ):
                raise AppError(
                    409,
                    "Eine Planänderung ist inzwischen veraltet.",
                    reason="payload_hash_conflict",
                )

    def _validate_structured_training_change_hashes(
        self,
        changes: list[dict[str, Any]],
        *,
        require_revision: bool,
        db: Any,
    ) -> None:
        for change in changes:
            if str(change.get("action") or "update").strip().casefold() != "create":
                self._validate_structured_training_change_hash(
                    change, require_revision=require_revision, db=db
                )

    def _validate_structured_training_change_revisions(
        self,
        changes: list[dict[str, Any]],
        arguments: dict[str, Any],
        *,
        require_revision: bool,
        db: Any,
    ) -> int:
        current_revision = self._validate_structured_training_revision(
            arguments, require_revision=require_revision, db=db
        )
        self._validate_structured_training_change_hashes(
            changes, require_revision=require_revision, db=db
        )
        self._validate_training_change_batch(changes, db)
        return current_revision

    def validate(
        self,
        changes: list[dict[str, Any]],
        arguments: dict[str, Any],
        db: Any,
        require_revision: bool,
    ) -> int:
        return self._validate_structured_training_change_revisions(
            changes,
            arguments,
            require_revision=require_revision,
            db=db,
        )


class StructuredTrainingPlanResolver:
    """Resolve plan membership using the caller's repository and transaction."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    @staticmethod
    def _change_moves_bounds(
        action: str, change: dict[str, Any], current: dict[str, Any]
    ) -> bool:
        if action in {"delete", "archive", "restore"}:
            return True
        return (
            action == "update"
            and "date" in change
            and not str(change.get("date") or "").startswith(
                str(current.get("date") or "")[:10]
            )
        )

    def _membership_update(
        self, change: dict[str, Any], db: Any
    ) -> tuple[str | None, str | None]:
        action = str(change.get("action") or "update").strip().casefold()
        local_id = str(change.get("local_id") or "").strip()
        if action == "create" or not local_id:
            return None, None
        row = db.execute(
            "SELECT payload FROM planned_units WHERE local_id=?", (local_id,)
        ).fetchone()
        if not row:
            return None, None
        try:
            current = json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError):
            current = {}
        if not isinstance(current, dict):
            return None, None
        membership = str(current.get("plan_id") or "").strip()
        if self._change_moves_bounds(action, change, current) and membership:
            return membership, membership
        return membership, None

    def _collect_memberships(
        self, changes: list[dict[str, Any]], db: Any
    ) -> tuple[set[str], set[str]]:
        referenced_memberships: set[str] = set()
        plans_needing_bounds: set[str] = set()
        for change in changes:
            membership, bounds_membership = self._membership_update(change, db)
            if membership is not None:
                referenced_memberships.add(membership)
            if bounds_membership:
                plans_needing_bounds.add(bounds_membership)
        return referenced_memberships, plans_needing_bounds

    def _derived_plan(
        self, referenced_memberships: set[str], db: Any
    ) -> dict[str, str]:
        derived_plan: dict[str, str] = {}
        if len(referenced_memberships) == 1:
            membership = next(iter(referenced_memberships))
            candidate_plan = self.repository.get(db, membership) if membership else None
            if candidate_plan and candidate_plan.get("status") != "archived":
                derived_plan = {
                    "plan_id": str(candidate_plan["id"]),
                    "plan_name": str(candidate_plan.get("name") or "")[:200],
                }
        return derived_plan

    def _apply_authorized_plan(
        self,
        derived_plan: dict[str, str],
        authorized_plan_id: str | None,
        db: Any,
    ) -> dict[str, str]:
        authorized_plan_id = str(authorized_plan_id or "").strip()
        if not authorized_plan_id:
            return derived_plan
        authorized_plan = self.repository.get(db, authorized_plan_id)
        if not authorized_plan or authorized_plan.get("status") == "archived":
            raise AppError(
                409,
                "Der benannte Trainingsplan ist nicht aktiv.",
                reason="plan_not_available",
            )
        if derived_plan and derived_plan["plan_id"] != authorized_plan_id:
            raise AppError(
                403,
                "Die Planreferenzen der Änderung sind nicht eindeutig.",
                reason="intent_scope_denied",
            )
        return {
            "plan_id": str(authorized_plan["id"]),
            "plan_name": str(authorized_plan.get("name") or "")[:200],
        }

    def _resolve_plan_reference(
        self,
        referenced_memberships: set[str],
        authorized_plan_id: str | None,
        db: Any,
    ) -> dict[str, str]:
        derived_plan = self._derived_plan(referenced_memberships, db)
        return self._apply_authorized_plan(derived_plan, authorized_plan_id, db)

    @staticmethod
    def _validate_create_plan_ids(
        changes: list[dict[str, Any]],
        derived_plan: dict[str, str],
        plans_needing_bounds: set[str],
    ) -> None:
        for change in changes:
            if str(change.get("action") or "update").strip().casefold() != "create":
                continue
            requested_plan_id = (
                str(change.get("plan_id") or "").strip()
                if "plan_id" in change
                else None
            )
            if requested_plan_id and requested_plan_id != derived_plan.get("plan_id"):
                raise AppError(
                    403,
                    "Eine neue Einheit darf nur dem eindeutig abgeleiteten Plan zugeordnet werden.",
                    reason="intent_scope_denied",
                )
            if requested_plan_id or ("plan_id" not in change and derived_plan):
                plans_needing_bounds.add(derived_plan["plan_id"])

    def derive(
        self,
        changes: list[dict[str, Any]],
        authorized_plan_id: str | None,
        db: Any,
    ) -> tuple[dict[str, str], set[str]]:
        referenced_memberships, plans_needing_bounds = self._collect_memberships(
            changes, db
        )
        derived_plan = self._resolve_plan_reference(
            referenced_memberships, authorized_plan_id, db
        )
        self._validate_create_plan_ids(changes, derived_plan, plans_needing_bounds)
        return derived_plan, plans_needing_bounds


class StructuredTrainingChangeService:
    """Apply a complete structured planning batch with one owned transaction."""

    def __init__(
        self,
        database_manager: Any,
        validator: StructuredTrainingChangeValidator,
        plan_resolver: StructuredTrainingPlanResolver,
        planned_unit_service: Any,
        revision_service: Any,
        training_plan_service: Any,
        today: Callable[[], date],
        max_changes: int,
        publish_change: Callable[[], None],
    ) -> None:
        self._database_manager = database_manager
        self._validator = validator
        self._plan_resolver = plan_resolver
        self._planned_unit_service = planned_unit_service
        self._revision_service = revision_service
        self._training_plan_service = training_plan_service
        self._today = today
        self._max_changes = max_changes
        self._publish_change = publish_change

    def apply(
        self,
        arguments: dict[str, Any],
        *,
        require_revision: bool = False,
        authorized_plan_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply and commit one batch, then publish its state change once."""
        with self._database_manager.unit_of_work() as db:
            result = self.apply_in_db(
                db,
                arguments,
                require_revision=require_revision,
                authorized_plan_id=authorized_plan_id,
            )
        self._publish_change()
        return result

    def apply_in_db(
        self,
        db: Any,
        arguments: dict[str, Any],
        *,
        require_revision: bool = False,
        authorized_plan_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply one batch using only the transaction owned by the caller."""
        changes = prepare_structured_training_changes(
            arguments, today=self._today(), max_changes=self._max_changes
        )
        current_revision = self._validator.validate(
            changes, arguments, db, require_revision
        )
        derived_plan, plans_needing_bounds = self._plan_resolver.derive(
            changes, authorized_plan_id, db
        )

        applied = []
        for change in changes:
            if str(change.get("action") or "update").strip().casefold() == "create":
                entry_payload = {**change, "source": "coach"}
                if "plan_id" not in change:
                    entry_payload.update(derived_plan)
                elif not str(change.get("plan_id") or "").strip():
                    entry_payload.pop("plan_id", None)
                    entry_payload.pop("plan_name", None)
                else:
                    entry_payload.update(derived_plan)
                applied.append(
                    {
                        "local_id": self._planned_unit_service.create(
                            entry_payload, db=db, bump_planning_revision=False
                        )["id"],
                        "status": "local",
                    }
                )
            else:
                applied.append(
                    self._planned_unit_service.update(
                        change["local_id"],
                        change,
                        skip_calendar_conflict=True,
                        bump_planning_revision=False,
                        db=db,
                    )
                )

        self._revision_service.bump(db)
        self._training_plan_service.update_bounds(db, plans_needing_bounds)
        revision = self._revision_service.read(db)
        result_changes = [
            {"local_id": item.get("local_id"), "status": item.get("status")}
            for item in applied
        ]
        return {
            "ok": True,
            "status": "applied",
            "planning_revision": revision or current_revision,
            "changes": result_changes,
            "library_entry_ids": list(
                dict.fromkeys(
                    item["local_id"] for item in result_changes if item.get("local_id")
                )
            ),
        }
