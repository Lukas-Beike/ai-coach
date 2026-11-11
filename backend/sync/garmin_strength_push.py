"""Explicit push of selected strength planned units to Garmin Connect.

Runs only from a ``plan_push`` job that names Garmin as its provider, which the
athlete starts explicitly. Every selected unit is validated and mapped locally
before the first remote write, so an unresolved exercise, a stale preview or a
past date writes nothing for that unit. A unit becomes one Garmin strength
workout scheduled on its planned date; the workout id and the schedule id live
in ``remote_links`` (provider ``garmin``, entity ``planned_unit``), so a second
push updates the same workout and moves its own schedule instead of creating a
duplicate. An entry with ``remove`` deletes only that linked workout and its own
schedule; the calendar and the Coach card add such entries for the links of
units that no longer exist (``planning.garmin_orphans``). A workout the update
cannot find is replaced by a new upload after the old one is unscheduled and
deleted. Writes go through the unofficial SDK, because the Personal API is
read-only. One remote failure other than a client error stops the remaining
units of the run, so a Garmin outage never turns into a burst of requests.

The one write without a request (athlete decision 2026-11-11, #2185): after each
Garmin refresh, ``remove_past`` unschedules and deletes the linked workouts whose
planned day has passed, so they do not fill the watch's workout list. It touches
only linked ids, never a recorded activity.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from backend.canonical.vocabulary import (
    ProviderId,
    RemoteEntityKind,
    RemoteLinkState,
    Sport,
)
from backend.db import DatabaseManager
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.planning import planned_units, strength_structure
from backend.planning.exercise_mappings import remembered_exercises
from backend.planning.push_state import garmin_fingerprint
from backend.planning.sport import planned_sport_environment
from backend.providers.garmin_personal import GarminTransportClient
from backend.providers.garmin_strength_workout import (
    NO_STRUCTURE_MESSAGE,
    GarminExercise,
    GarminStrengthMappingError,
    strength_workout,
    workout_exercise_steps,
)
from backend.sync.garmin_service import _persist_garmin_tokens, shared_garmin_sync_lock
from backend.sync.gates import ProviderResyncGate

GARMIN = ProviderId.GARMIN.value
_REMOTE_LINKS = RemoteLinkRepository()
_RETRY_SCOPE = "Nur fehlgeschlagene Objekte erneut auswählen."
_LOCK_WAIT_S = 30.0
_LOGGER = logging.getLogger("intervals_coach")
SDK_REQUIRED_MESSAGE = (
    "Garmin-Workouts brauchen die Garmin-Anmeldung (SDK); "
    "die Personal API kann nicht schreiben."
)
# First line of every description, so a workout this app sent can be told apart.
WORKOUT_MARKER = "Pacecraft"
# Workouts of past days removed per refresh; the next refresh takes the rest.
_PAST_REMOVAL_BATCH = 50
_STOPPED = "Nicht gesendet: Der Lauf wurde nach einem Garmin-Fehler beendet."


class _StopRun(Exception):
    """A remote failure that must not be repeated for the remaining units."""


@dataclass(frozen=True)
class _Prepared:
    local_id: str
    payload_hash: str | None
    remove: bool
    plan_date: str = ""
    document: dict[str, Any] | None = None
    # What the calendar compares to show the sync button again (push_state).
    fingerprint: str | None = None


def _status(error: BaseException) -> int | None:
    status = getattr(getattr(error, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def _not_found(error: BaseException) -> bool:
    return type(error).__name__ == "GarminConnectNotFoundError" or _status(error) == 404


def _remote_failure(error: BaseException) -> AppError | _StopRun:
    """Map an SDK failure to a fixed message; never forward Garmin's text."""
    status = _status(error)
    if status is not None and 400 <= status < 500 and status not in (401, 408, 429):
        return AppError(
            502,
            f"Garmin hat das Workout abgelehnt (HTTP {status}).",
            reason="garmin_workout_rejected",
        )
    return _StopRun(
        "Garmin ist nicht erreichbar oder hat die Anfrage abgelehnt"
        + (f" (HTTP {status})." if status else ".")
    )


class GarminStrengthPushService:
    """Upload, update, schedule or remove Garmin strength workouts on request."""

    def __init__(
        self,
        *,
        configured: Callable[[], bool],
        database_manager: Callable[[], DatabaseManager],
        sdk_session: Callable[[], Any],
        today: Callable[[], date],
        now: Callable[[], datetime],
        redactor: Callable[[str], str],
        gate: ProviderResyncGate | None = None,
    ) -> None:
        self._configured = configured
        self._database_manager = database_manager
        self._sdk_session = sdk_session
        self._today = today
        self._now = now
        self._redact = redactor
        self._gate = gate
        self._lock = threading.Lock()

    def sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("repair"):
            raise AppError(
                400,
                "Die Reparatur ist für Garmin nicht verfügbar.",
                reason="invalid_job_request",
            )
        if not self._configured():
            raise AppError(
                409, "Garmin ist nicht konfiguriert.", reason="not_configured"
            )
        requested = _entries(payload.get("entries"))
        operation = self._gate.operation() if self._gate is not None else nullcontext()
        with operation, self._lock:
            results = self._run(requested)
        failed = [
            item["library_workout_id"]
            for item in results
            if item["status"] in {"error", "conflict"}
        ]
        status = "ok"
        if failed:
            status = "partial" if len(failed) < len(results) else "error"
        return {
            "ok": not failed,
            "status": status,
            "results": results,
            "failed_object_ids": failed,
            "retry_scope": _RETRY_SCOPE if failed else None,
        }

    def remove_past(self) -> int:
        """Delete the linked workouts of past days; return how many went.

        Runs after a Garmin refresh. A failure is logged and never fails the
        refresh: the links stay, and the next refresh tries again.
        """
        try:
            if not self._configured():
                return 0
            links = self._past_links()
            if not links:
                return 0
            operation = (
                self._gate.operation() if self._gate is not None else nullcontext()
            )
            with operation, self._lock, self._sdk_session() as client:
                return self._remove_links(client, links)
        except Exception:  # noqa: BLE001 - the refresh outcome stays unchanged
            _LOGGER.warning(
                "Garmin past workout removal failed",
                extra={"event": "garmin_past_workout_removal_failed"},
            )
            return 0

    def _past_links(self) -> list[RemoteLink]:
        """Linked units dated before today, oldest first, at most one batch."""
        today = self._today().isoformat()
        with self._database_manager().unit_of_work() as db:
            rows = db.execute(
                "SELECT l.local_id, p.payload FROM remote_links l "
                "JOIN planned_units p ON p.local_id = l.local_id "
                "WHERE l.provider=? AND l.entity_kind=? ORDER BY l.local_id",
                (GARMIN, RemoteEntityKind.PLANNED_UNIT.value),
            ).fetchall()
            past = sorted(
                (day, str(row["local_id"]))
                for row in rows
                if (day := _payload_day(row["payload"])) and day < today
            )
            links = [
                _REMOTE_LINKS.get(db, RemoteEntityKind.PLANNED_UNIT, local_id, GARMIN)
                for _day, local_id in past[:_PAST_REMOVAL_BATCH]
            ]
        return [link for link in links if link is not None]

    def _remove_links(self, client: Any, links: list[RemoteLink]) -> int:
        removed = 0
        for link in links:
            try:
                self._discard(client, link.remote_id, link.remote_external_id)
            except _StopRun:
                break
            except AppError:
                continue  # Garmin refused this one; the link stays for a retry
            with self._database_manager().unit_of_work() as db:
                _REMOTE_LINKS.delete(
                    db, RemoteEntityKind.PLANNED_UNIT, link.local_id, GARMIN
                )
            removed += 1
        if removed:
            _LOGGER.info(
                "Garmin past workouts removed",
                extra={
                    "event": "garmin_past_workouts_removed",
                    "context": {"count": removed},
                },
            )
        return removed

    def _run(self, requested: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        prepared: list[_Prepared] = []
        for item in requested:
            outcome = self._prepare(item)
            if isinstance(outcome, _Prepared):
                prepared.append(outcome)
            else:
                results[item["library_workout_id"]] = outcome
        if prepared:
            with self._sdk_session() as client:
                self._write_all(client, prepared, results)
        return [results[item["library_workout_id"]] for item in requested]

    def _write_all(
        self,
        client: Any,
        prepared: list[_Prepared],
        results: dict[str, dict[str, Any]],
    ) -> None:
        stopped = False
        for unit in prepared:
            if stopped:
                results[unit.local_id] = _error_result(unit.local_id, _STOPPED)
                continue
            try:
                results[unit.local_id] = (
                    self._remove(client, unit)
                    if unit.remove
                    else self._push(client, unit)
                )
            except _StopRun as exc:
                stopped = True
                results[unit.local_id] = _error_result(
                    unit.local_id, _removal_context(unit, str(exc))
                )
            except Exception as exc:  # noqa: BLE001 - isolate each selected unit
                results[unit.local_id] = _error_result(
                    unit.local_id,
                    _removal_context(unit, self._redact(str(exc))[:500]),
                )

    def _prepare(self, item: dict[str, Any]) -> _Prepared | dict[str, Any]:
        local_id = item["library_workout_id"]
        if item.get("remove"):
            if self._link(local_id) is None:
                return _already_removed(local_id)
            return _Prepared(local_id, None, True)
        with self._database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT payload, tombstone FROM planned_units WHERE local_id=?",
                (local_id,),
            ).fetchone()
            remembered = remembered_exercises(db)
        if not row or row["tombstone"]:
            return _error_result(local_id, "Einheit nicht gefunden", "conflict")
        if not planned_units.plan_push_hash_matches(
            row["payload"], item["expected_payload_hash"]
        ):
            return _error_result(local_id, "Seit der Vorschau geändert", "conflict")
        try:
            unit = json.loads(row["payload"] or "{}")
            plan_date, document = self._document(unit, remembered)
        except (AppError, GarminStrengthMappingError, TypeError, ValueError) as exc:
            return _error_result(local_id, self._redact(str(exc))[:500])
        return _Prepared(
            local_id,
            planned_units.plan_push_payload_hash(row["payload"]),
            False,
            plan_date,
            document,
            garmin_fingerprint(unit),
        )

    def _document(
        self, unit: Any, remembered: Mapping[str, GarminExercise]
    ) -> tuple[str, dict[str, Any]]:
        if (
            not isinstance(unit, dict)
            or unit.get("local_deleted")
            or unit.get("archived")
        ):
            raise ValueError("Die Einheit ist gelöscht oder archiviert.")
        sport, _environment = planned_sport_environment(unit)
        if sport is not Sport.STRENGTH:
            raise ValueError("Nur Krafteinheiten können an Garmin gesendet werden.")
        plan_date = str(unit.get("date") or "")[:10]
        try:
            day = date.fromisoformat(plan_date)
        except ValueError:
            raise ValueError("Die Einheit hat kein gültiges Datum.") from None
        if day < self._today():
            raise ValueError("Vergangene Einheiten werden nicht an Garmin gesendet.")
        exercises = strength_structure.normalize_structure(
            unit.get("strength_structure")
        )
        if not exercises:
            raise ValueError(NO_STRUCTURE_MESSAGE)
        document = strength_workout(
            name=str(unit.get("name") or ""),
            description=f"{WORKOUT_MARKER}\n{strength_structure.render(exercises)}",
            exercises=exercises,
            remembered=remembered,
        )
        return plan_date, document

    def _link(self, local_id: str) -> RemoteLink | None:
        with self._database_manager().unit_of_work() as db:
            return _REMOTE_LINKS.get(
                db, RemoteEntityKind.PLANNED_UNIT, local_id, GARMIN
            )

    def _push(self, client: Any, unit: _Prepared) -> dict[str, Any]:
        assert unit.document is not None
        link = self._link(unit.local_id)
        workout_id = link.remote_id if link else None
        created = False
        schedule_id = link.remote_external_id if link else None
        if workout_id:
            try:
                _call(client.update_workout, workout_id, unit.document)
            except _Missing:
                # The fresh upload replaces it; nothing of the old one may stay.
                self._discard(client, workout_id, schedule_id)
                workout_id = schedule_id = None
        if not workout_id:
            saved = _call(client.upload_workout, unit.document)
            workout_id = _workout_id(saved)
            created = True
        # Link the workout at once, so a failure below never leads to a
        # duplicate upload on the next push.
        self._save_link(unit, workout_id, schedule_id, None)
        if not self._verified(client, workout_id, unit.document):
            self._drop_broken(client, unit, workout_id, schedule_id, created=created)
        if schedule_id:
            try:
                _call(client.unschedule_workout, schedule_id)
            except _Missing:
                pass
            self._save_link(unit, workout_id, None, None)
        schedule_id = _schedule_id(
            _call(client.schedule_workout, workout_id, unit.plan_date)
        ) or _scheduled_on(client, workout_id, unit.plan_date)
        if schedule_id is None:
            # Without the id a later push could not move this entry; the push
            # stays incomplete instead of reporting success.
            raise AppError(
                502,
                "Garmin hat den Termin ohne Termin-ID bestätigt; bitte den "
                "Garmin-Kalender prüfen, bevor erneut gesendet wird.",
                reason="garmin_schedule_unconfirmed",
            )
        self._save_link(unit, workout_id, schedule_id, unit.fingerprint)
        return {
            "library_workout_id": unit.local_id,
            "status": "synced",
            "remote_id": workout_id,
            "date": unit.plan_date,
        }

    @staticmethod
    def _discard(client: Any, workout_id: str | None, schedule_id: str | None) -> None:
        """Unschedule and delete a linked workout; one already gone is fine."""
        for method, remote_id in (
            (client.unschedule_workout, schedule_id),
            (client.delete_workout, workout_id),
        ):
            if remote_id:
                try:
                    _call(method, remote_id)
                except _Missing:
                    pass

    def _save_link(
        self,
        unit: _Prepared,
        workout_id: str,
        schedule_id: str | None,
        payload_hash: str | None,
    ) -> None:
        """Store the workout and schedule ids; the fingerprint only once fully pushed."""
        with self._database_manager().unit_of_work() as db:
            _REMOTE_LINKS.upsert(
                db,
                RemoteLink(
                    entity_kind=RemoteEntityKind.PLANNED_UNIT,
                    local_id=unit.local_id,
                    provider=GARMIN,
                    sync_state=RemoteLinkState.SYNCED,
                    remote_id=workout_id,
                    remote_external_id=schedule_id,
                    baseline_hash=payload_hash,
                    last_synced_at=self._now().astimezone(UTC).isoformat(),
                ),
            )

    @staticmethod
    def _verified(client: Any, workout_id: str, document: dict[str, Any]) -> bool:
        """Whether the saved workout kept every sent exercise step."""
        saved = _call(client.get_workout_by_id, workout_id)
        return isinstance(saved, dict) and workout_exercise_steps(
            saved
        ) == workout_exercise_steps(document)

    def _drop_broken(
        self,
        client: Any,
        unit: _Prepared,
        workout_id: str,
        schedule_id: str | None,
        *,
        created: bool,
    ) -> None:
        """Keep a blanked workout off the watch, then report the failure.

        A new workout is deleted again; an updated one is unscheduled so its
        planned day shows no broken steps, and the next push updates it.
        """
        try:
            if created:
                _call(client.delete_workout, workout_id)
                with self._database_manager().unit_of_work() as db:
                    _REMOTE_LINKS.delete(
                        db, RemoteEntityKind.PLANNED_UNIT, unit.local_id, GARMIN
                    )
            elif schedule_id:
                _call(client.unschedule_workout, schedule_id)
                self._save_link(unit, workout_id, None, None)
        except _Missing:
            pass
        except Exception:  # noqa: BLE001 - the verification error is reported
            _LOGGER.warning(
                "Garmin workout cleanup failed",
                extra={"event": "garmin_workout_cleanup_failed"},
            )
        raise AppError(
            502,
            "Garmin hat nicht alle Übungen übernommen; nichts terminiert.",
            reason="garmin_workout_verification_failed",
        )

    def _remove(self, client: Any, unit: _Prepared) -> dict[str, Any]:
        link = self._link(unit.local_id)
        if link is None:
            return _already_removed(unit.local_id)
        self._discard(client, link.remote_id, link.remote_external_id)
        with self._database_manager().unit_of_work() as db:
            _REMOTE_LINKS.delete(
                db, RemoteEntityKind.PLANNED_UNIT, unit.local_id, GARMIN
            )
        # "synced" is the job store's success state; "action" tells the cases apart.
        return {
            "library_workout_id": unit.local_id,
            "status": "synced",
            "action": "removed",
        }


class _Missing(Exception):
    """The addressed Garmin object no longer exists."""


def _call(method: Callable[..., Any], *args: Any) -> Any:
    try:
        return method(*args)
    except AppError:
        raise
    except Exception as exc:
        if _not_found(exc):
            raise _Missing() from exc
        raise _remote_failure(exc) from exc


def _workout_id(saved: Any) -> str:
    value = saved.get("workoutId") if isinstance(saved, dict) else None
    if (
        isinstance(value, bool)
        or not isinstance(value, int | str)
        or not str(value).strip()
    ):
        raise _StopRun("Garmin hat keine Workout-ID zurückgegeben.")
    return str(value)


def _schedule_id(saved: Any) -> str | None:
    if not isinstance(saved, dict):
        return None
    for key in ("workoutScheduleId", "scheduleId", "id"):
        value = saved.get(key)
        if (
            not isinstance(value, bool)
            and isinstance(value, int | str)
            and str(value).strip()
        ):
            return str(value)
    return None


def _scheduled_on(client: Any, workout_id: str, day: str) -> str | None:
    """Find this workout's schedule id on ``day`` in Garmin's calendar."""
    items = _call(client.get_scheduled_workouts_by_period, day, day)
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        workout = item.get("workout")
        workout = workout if isinstance(workout, dict) else {}
        owner = item.get("workoutId") or workout.get("workoutId")
        if str(owner or "") == workout_id:
            return _schedule_id(item)
    return None


def _payload_day(raw_payload: Any) -> str:
    """The unit's planned day, or "" for an unreadable payload."""
    try:
        payload = json.loads(raw_payload or "{}")
    except TypeError, ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    day = str(payload.get("date") or "")[:10]
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError:
        return ""


def _already_removed(local_id: str) -> dict[str, Any]:
    """Nothing is linked any more, e.g. a listed leftover removed by another sync."""
    return {"library_workout_id": local_id, "status": "already_synced"}


def _removal_context(unit: _Prepared, message: str) -> str:
    """Say which write failed, since a job may mix a push with leftover removals."""
    return f"Altes Garmin-Workout nicht entfernt: {message}" if unit.remove else message


def _error_result(local_id: str, message: str, status: str = "error") -> dict[str, Any]:
    return {"library_workout_id": local_id, "status": status, "error": message}


def _entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or not entries:
        raise AppError(400, "Mindestens eine Einheit muss ausgewählt werden.")
    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise AppError(400, "Ungültige Auswahl.", reason="invalid_job_request")
        local_id = planning_library.workout_library_entry_id(
            entry.get("library_workout_id")
        )
        if entry.get("remove") is True:
            result.append({"library_workout_id": local_id, "remove": True})
            continue
        selected = planning_library.library_bulk_request_entries(
            [entry], require_hash=True
        )[0]
        result.append(selected)
    if len({item["library_workout_id"] for item in result}) != len(result):
        raise AppError(400, "Eine Einheit darf nur einmal ausgewählt werden.")
    return result


class GarminSdkWriteSession:
    """Open one authenticated SDK client under Garmin's shared lock.

    Refreshed tokens are written back after the run, whatever its outcome.
    """

    def __init__(self, reader: Any, fixture_loader: Any, tokens: Any) -> None:
        self._reader = reader
        self._fixture_loader = fixture_loader
        self._tokens = tokens

    @contextmanager
    def __call__(self) -> Iterator[Any]:
        lock = shared_garmin_sync_lock()
        if not lock.acquire(timeout=_LOCK_WAIT_S):
            raise AppError(
                409,
                "Garmin wird gerade synchronisiert. Bitte später erneut senden.",
                reason="garmin_busy",
            )
        try:
            if self._fixture_loader.path() is not None:
                raise AppError(409, SDK_REQUIRED_MESSAGE, reason="garmin_sdk_required")
            client, login_argument = self._reader._authenticated_client(
                lambda _service, _operation, call, _details: call()
            )
            sdk = client.sdk if isinstance(client, GarminTransportClient) else client
            if sdk is None:
                raise AppError(409, SDK_REQUIRED_MESSAGE, reason="garmin_sdk_required")
            try:
                yield sdk
            finally:
                try:
                    _persist_garmin_tokens(self._tokens, sdk, login_argument)
                except Exception:  # noqa: BLE001 - keep the push outcome
                    _LOGGER.warning(
                        "Garmin token persistence failed",
                        extra={"event": "garmin_token_persist_failed"},
                    )
        finally:
            lock.release()
