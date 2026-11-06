"""Explicit push of selected strength planned units to Garmin Connect.

Runs only from a ``plan_push`` job that names Garmin as its provider, which the
athlete starts explicitly. Every selected unit is validated and mapped locally
before the first remote write, so an unresolved exercise, a stale preview or a
past date writes nothing for that unit. A unit becomes one Garmin strength
workout scheduled on its planned date; the workout id and the schedule id live
in ``remote_links`` (provider ``garmin``, entity ``planned_unit``), so a second
push updates the same workout and moves its own schedule instead of creating a
duplicate. An entry with ``remove`` deletes only that linked workout and its own
schedule. Writes go through the unofficial SDK, because the Personal API is
read-only. One remote failure other than a client error stops the remaining
units of the run, so a Garmin outage never turns into a burst of requests.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator
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
from backend.planning import strength_structure
from backend.planning.sport import planned_sport_environment
from backend.providers.garmin_personal import GarminTransportClient
from backend.providers.garmin_strength_workout import (
    GarminStrengthMappingError,
    strength_workout,
    workout_exercise_pairs,
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


def _status(error: BaseException) -> int | None:
    status = getattr(getattr(error, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def _not_found(error: BaseException) -> bool:
    return type(error).__name__ == "GarminConnectNotFoundError" or _status(error) == 404


def _remote_failure(error: BaseException) -> Exception:
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
        status = (
            "ok" if not failed else "partial" if len(failed) < len(results) else "error"
        )
        return {
            "ok": not failed,
            "status": status,
            "results": results,
            "failed_object_ids": failed,
            "retry_scope": _RETRY_SCOPE if failed else None,
        }

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
                results[unit.local_id] = _error_result(unit.local_id, str(exc))
            except Exception as exc:  # noqa: BLE001 - isolate each selected unit
                results[unit.local_id] = _error_result(
                    unit.local_id, self._redact(str(exc))[:500]
                )

    def _prepare(self, item: dict[str, Any]) -> _Prepared | dict[str, Any]:
        local_id = item["library_workout_id"]
        if item.get("remove"):
            if self._link(local_id) is None:
                return _error_result(local_id, "Nicht an Garmin gesendet.", "conflict")
            return _Prepared(local_id, None, True)
        with self._database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT payload, tombstone FROM planned_units WHERE local_id=?",
                (local_id,),
            ).fetchone()
        if not row or row["tombstone"]:
            return _error_result(local_id, "Einheit nicht gefunden", "conflict")
        payload_hash = planning_library.library_payload_hash(row["payload"])
        if payload_hash != item["expected_payload_hash"]:
            return _error_result(local_id, "Seit der Vorschau geändert", "conflict")
        try:
            unit = json.loads(row["payload"] or "{}")
            plan_date, document = self._document(unit)
        except (AppError, GarminStrengthMappingError, TypeError, ValueError) as exc:
            return _error_result(local_id, self._redact(str(exc))[:500])
        return _Prepared(local_id, payload_hash, False, plan_date, document)

    def _document(self, unit: Any) -> tuple[str, dict[str, Any]]:
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
            raise ValueError("Die Einheit hat keine Kraftstruktur.")
        document = strength_workout(
            name=str(unit.get("name") or ""),
            description=strength_structure.render(exercises),
            exercises=exercises,
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
        if workout_id:
            try:
                _call(client.update_workout, workout_id, unit.document)
            except _Missing:
                workout_id = None
        if not workout_id:
            saved = _call(client.upload_workout, unit.document)
            workout_id = _workout_id(saved)
            created = True
        self._verify(client, workout_id, unit.document, created=created)
        # Link the workout before scheduling, so a failure below never leads
        # to a duplicate upload on the next push.
        schedule_id = link.remote_external_id if link else None
        self._save_link(unit, workout_id, schedule_id, None)
        if schedule_id:
            try:
                _call(client.unschedule_workout, schedule_id)
            except _Missing:
                pass
            self._save_link(unit, workout_id, None, None)
        schedule_id = _schedule_id(
            _call(client.schedule_workout, workout_id, unit.plan_date)
        )
        self._save_link(unit, workout_id, schedule_id, unit.payload_hash)
        return {
            "library_workout_id": unit.local_id,
            "status": "synced",
            "remote_id": workout_id,
            "date": unit.plan_date,
        }

    def _save_link(
        self,
        unit: _Prepared,
        workout_id: str,
        schedule_id: str | None,
        payload_hash: str | None,
    ) -> None:
        """Store the workout and schedule ids; the hash only once fully pushed."""
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
    def _verify(
        client: Any, workout_id: str, document: dict[str, Any], *, created: bool
    ) -> None:
        """Reject a saved workout whose exercise steps Garmin did not keep."""
        saved = _call(client.get_workout_by_id, workout_id)
        expected = workout_exercise_pairs(document)
        if isinstance(saved, dict) and workout_exercise_pairs(saved) == expected:
            return
        if created:
            try:
                _call(client.delete_workout, workout_id)
            except Exception:  # noqa: BLE001 - the verification error is reported
                _LOGGER.warning(
                    "Garmin workout cleanup failed",
                    extra={"event": "garmin_workout_cleanup_failed"},
                )
        raise AppError(
            502,
            "Garmin hat nicht alle Übungen übernommen.",
            reason="garmin_workout_verification_failed",
        )

    def _remove(self, client: Any, unit: _Prepared) -> dict[str, Any]:
        link = self._link(unit.local_id)
        if link is None:
            return _error_result(unit.local_id, "Nicht an Garmin gesendet.", "conflict")
        if link.remote_external_id:
            try:
                _call(client.unschedule_workout, link.remote_external_id)
            except _Missing:
                pass
        if link.remote_id:
            try:
                _call(client.delete_workout, link.remote_id)
            except _Missing:
                pass
        with self._database_manager().unit_of_work() as db:
            _REMOTE_LINKS.delete(
                db, RemoteEntityKind.PLANNED_UNIT, unit.local_id, GARMIN
            )
        return {"library_workout_id": unit.local_id, "status": "removed"}


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
