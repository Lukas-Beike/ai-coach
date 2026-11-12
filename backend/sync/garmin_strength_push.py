"""Explicit push of selected strength and run planned units to Garmin Connect.

Runs only from a ``plan_push`` job that names Garmin as its provider, which the
athlete starts explicitly. Every selected unit is validated and mapped locally
before the first remote write, so an unresolved exercise, a stale preview or a
past date writes nothing for that unit. A strength unit becomes one Garmin
strength workout; a run unit becomes one running workout whose percent and zone
targets are resolved into absolute watts, bpm or m/s from the athlete's run
zones, one snapshot per run (``planning.run_lthr``), and whose heart-rate cap is
sent as bpm; rides and other sports are refused. Either is scheduled on its
planned date; the workout id and the schedule id live in ``remote_links`` (provider ``garmin``, entity ``planned_unit``), so a second
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
only linked ids of any sport, never a recorded activity. Once (athlete decision 2026-11-12,
#2373) it also removes the app's own older strength workouts that lost their
unit: only those whose description starts with ``WORKOUT_MARKER``, that no unit
of today or later links and that no day from today on schedules.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.activities.hr_cap_export import capped_description
from backend.activities.workout_text import structured_blocks
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.vocabulary import (
    ProviderId,
    RemoteEntityKind,
    RemoteLinkState,
    Sport,
)
from backend.db import DatabaseManager
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.planning import planned_units, strength_structure
from backend.planning.exercise_mappings import remembered_exercises
from backend.planning.push_state import garmin_fingerprint
from backend.planning.sport import planned_sport_environment
from backend.providers.garmin_personal import GarminTransportClient
from backend.providers.garmin_run_workout import (
    GarminRunTargets,
    comparable_steps,
    run_workout,
)
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
_KEY_VALUES = KeyValueRepository(lambda: datetime.now(UTC).isoformat())
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
_PAST_REMOVAL_BATCH = 20
_PAST_REMOVAL_ATTEMPTS = 2 * _PAST_REMOVAL_BATCH
_STOPPED = "Nicht gesendet: Der Lauf wurde nach einem Garmin-Fehler beendet."
# The one-time removal of the app's unlinked old workouts (#2373): its progress
# (done, and the ids read as not the app's), workout list pages, detail reads per
# refresh and the scheduled days it keeps.
APP_WORKOUT_CLEANUP_KEY = "garmin_app_workout_cleanup"
_CLEANUP_PAGE = 100
_CLEANUP_MAX_PAGES = 10
_CLEANUP_READS = 40
_CLEANUP_SCHEDULE_DAYS = 90

_ZonesFor = Callable[[Mapping[str, Any]], ZoneSettings | None]


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
    """Upload, update, schedule or remove Garmin strength and run workouts on request."""

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
        write_ready: Callable[[], bool] = lambda: True,
        run_zones: Callable[[], _ZonesFor] | None = None,
    ) -> None:
        self._configured = configured
        # False while the latest refresh could not log the SDK in (login, MFA).
        self._write_ready = write_ready
        self._database_manager = database_manager
        self._sdk_session = sdk_session
        self._today = today
        self._now = now
        self._redact = redactor
        self._gate = gate
        # One snapshot of the run zones per push run resolves relative run targets.
        self._run_zones = run_zones
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
        """Delete the linked workouts of units dated before today; return how many.

        Runs after a Garmin refresh. Nothing happens while the latest refresh
        could not log the SDK in, so no extra login is tried. A failure is logged
        and never fails the refresh: the links stay for the next refresh. Every
        run logs its count, zero included, and stores its time, outcome,
        removals and the links still waiting for the diagnostics (#2408); a skip
        logs its reason.
        """
        try:
            if not self._configured():
                return 0
            ready = self._write_ready()
        except Exception:  # noqa: BLE001 - the refresh outcome stays unchanged
            _LOGGER.warning(
                "Garmin past workout removal failed",
                extra={"event": "garmin_past_workout_removal_failed"},
            )
            return 0
        if not ready:
            # Counts only: the removal waits for a refresh that logs the SDK in.
            _LOGGER.info(
                "Garmin past workout removal skipped",
                extra={
                    "event": "garmin_past_workout_removal_skipped",
                    "context": {"reason": "sdk_skipped"},
                },
            )
            self._record_run(0, "skipped")
            return 0
        removed = [0]
        cleanup: dict[str, Any] | None = None
        failed = False
        try:
            cleanup = self._cleanup_state()
            if self._past_links() or not cleanup["done"]:
                operation = (
                    self._gate.operation() if self._gate is not None else nullcontext()
                )
                with operation, self._lock, self._sdk_session() as client:
                    # Read again under the lock: a push may have moved a unit meanwhile.
                    self._remove_links(client, self._past_links(), removed)
                    if not cleanup["done"]:
                        self._remove_unlinked(client, cleanup, removed)
        except Exception:  # noqa: BLE001 - the refresh outcome stays unchanged
            failed = True
            _LOGGER.warning(
                "Garmin past workout removal failed",
                extra={"event": "garmin_past_workout_removal_failed"},
            )
        if cleanup is not None:
            self._record_run(removed[0], "failed" if failed else "ok")
        if failed and not removed[0]:
            return 0
        # Logged on every run, zero included, so a quiet run is visible (#2408).
        _LOGGER.info(
            "Garmin past workouts removed",
            extra={
                "event": "garmin_past_workouts_removed",
                "context": {"count": removed[0]},
            },
        )
        return removed[0]

    def _record_run(self, removed: int, outcome: str) -> None:
        """Store the run's time, outcome and removals, and the links still waiting."""
        try:
            state = self._cleanup_state()
            self._save_cleanup(
                {
                    **state,
                    "removed": state["removed"] + removed,
                    "last_run_at": self._now().astimezone(UTC).isoformat(),
                    "last_outcome": outcome,
                    # Athlete-local cutoff, the one the removal itself uses.
                    "pending": len(self._past_links()),
                }
            )
        except Exception:  # noqa: BLE001 - a status write never fails the refresh
            _LOGGER.warning(
                "Garmin past workout removal state not stored",
                extra={"event": "garmin_past_workout_state_failed"},
            )

    def _past_links(self) -> list[tuple[str, str | None, str | None]]:
        """(unit id, workout id, schedule id) of linked units before today, oldest first."""
        with self._database_manager().unit_of_work() as db:
            rows = db.execute(
                "SELECT l.local_id, l.remote_id, l.remote_external_id FROM remote_links l "
                "JOIN planned_units p ON p.local_id = l.local_id "
                "WHERE l.provider=? AND l.entity_kind=? AND json_valid(p.payload) "
                "AND substr(json_extract(p.payload, '$.date'), 1, 10) "
                "BETWEEN '0001-01-01' AND ? "
                "ORDER BY substr(json_extract(p.payload, '$.date'), 1, 10), l.local_id",
                (
                    GARMIN,
                    RemoteEntityKind.PLANNED_UNIT.value,
                    # BETWEEN is inclusive: the day before today is the last one.
                    (self._today() - timedelta(days=1)).isoformat(),
                ),
            ).fetchall()
        return [
            (str(row["local_id"]), row["remote_id"], row["remote_external_id"])
            for row in rows
        ]

    def _remove_links(
        self,
        client: Any,
        links: list[tuple[str, str | None, str | None]],
        removed: list[int],
    ) -> None:
        """Remove up to one batch with a bounded number of attempts.

        A refused workout keeps its link and uses an attempt but no removal slot,
        so a few refusals never block the later workouts and many never turn into
        a burst of requests. An outage stops the run and is logged by the caller.
        """
        for attempt, (local_id, workout_id, schedule_id) in enumerate(links):
            if removed[0] >= _PAST_REMOVAL_BATCH or attempt >= _PAST_REMOVAL_ATTEMPTS:
                return
            try:
                self._discard(client, workout_id, schedule_id)
            except AppError:
                continue  # Garmin refused this one; the next refresh tries again
            with self._database_manager().unit_of_work() as db:
                _REMOTE_LINKS.delete(
                    db, RemoteEntityKind.PLANNED_UNIT, local_id, GARMIN
                )
            removed[0] += 1

    def _remove_unlinked(
        self, client: Any, state: dict[str, Any], removed: list[int]
    ) -> None:
        """Remove the app's old workouts no unit of today or later uses, once.

        A workout counts as the app's only by its description's first line. The
        ids read as someone else's are remembered, so the bounded reads move on;
        a pass that reaches the end of the list finishes the removal for good.
        """
        today = self._today()
        keep = self._upcoming_workout_ids(today) | _scheduled_from(client, today)
        checked = set(state["checked"])
        reads = 0
        finished = False
        try:
            for workout_id in _strength_workout_ids(client):
                if workout_id in keep or workout_id in checked:
                    continue
                if removed[0] >= _PAST_REMOVAL_BATCH or reads >= _CLEANUP_READS:
                    break
                reads += 1
                if self._remove_if_own(client, workout_id):
                    removed[0] += 1
                else:
                    checked.add(workout_id)
            else:
                finished = True
        finally:
            # A Garmin outage keeps what this pass already read.
            self._save_cleanup({**state, "done": finished, "checked": sorted(checked)})

    def _remove_if_own(self, client: Any, workout_id: str) -> bool:
        """Delete one workout if the app sent it; False for another's or a refused one.

        A refused workout is not retried forever: the finished pass leaves it.
        """
        try:
            if not _app_created(_call(client.get_workout_by_id, workout_id)):
                return False
            _call(client.delete_workout, workout_id)
        except _Missing:
            pass
        except AppError:
            return False
        with self._database_manager().unit_of_work() as db:
            db.execute(
                "DELETE FROM remote_links WHERE provider=? AND entity_kind=? "
                "AND remote_id=?",
                (GARMIN, RemoteEntityKind.PLANNED_UNIT.value, workout_id),
            )
        return True

    def _upcoming_workout_ids(self, today: date) -> set[str]:
        """Workouts linked to a stored unit dated today or later."""
        with self._database_manager().unit_of_work() as db:
            rows = db.execute(
                "SELECT l.remote_id FROM remote_links l "
                "JOIN planned_units p ON p.local_id = l.local_id "
                "WHERE l.provider=? AND l.entity_kind=? AND l.remote_id IS NOT NULL "
                "AND json_valid(p.payload) "
                "AND substr(json_extract(p.payload, '$.date'), 1, 10) >= ?",
                (GARMIN, RemoteEntityKind.PLANNED_UNIT.value, today.isoformat()),
            ).fetchall()
        return {str(row["remote_id"]) for row in rows}

    def _cleanup_state(self) -> dict[str, Any]:
        with self._database_manager().unit_of_work() as db:
            raw = _KEY_VALUES.get(db, APP_WORKOUT_CLEANUP_KEY)
        try:
            value = json.loads(raw or "{}")
        except TypeError, ValueError:
            value = {}
        if not isinstance(value, dict):
            value = {}
        checked = value.get("checked")
        removed = value.get("removed")
        last_run = value.get("last_run_at")
        return {
            "done": value.get("done") is True,
            "checked": [str(item) for item in checked]
            if isinstance(checked, list)
            else [],
            "removed": removed
            if isinstance(removed, int) and not isinstance(removed, bool)
            else 0,
            "last_run_at": last_run if isinstance(last_run, str) else None,
        }

    def _save_cleanup(self, state: dict[str, Any]) -> None:
        with self._database_manager().unit_of_work() as db:
            _KEY_VALUES.set(db, APP_WORKOUT_CLEANUP_KEY, json.dumps(state))

    def _run(self, requested: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        prepared: list[_Prepared] = []
        zones_for = self._run_zones() if self._run_zones else _no_zones
        for item in requested:
            outcome = self._prepare(item, zones_for)
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

    def _prepare(
        self, item: dict[str, Any], zones_for: _ZonesFor
    ) -> _Prepared | dict[str, Any]:
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
            plan_date, document = self._document(unit, remembered, zones_for)
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
        self, unit: Any, remembered: Mapping[str, GarminExercise], zones_for: _ZonesFor
    ) -> tuple[str, dict[str, Any]]:
        if (
            not isinstance(unit, dict)
            or unit.get("local_deleted")
            or unit.get("archived")
        ):
            raise ValueError("Die Einheit ist gelöscht oder archiviert.")
        sport, _environment = planned_sport_environment(unit)
        if sport not in (Sport.STRENGTH, Sport.RUN):
            raise ValueError(
                "Nur Kraft- und Laufeinheiten können an Garmin gesendet werden."
            )
        plan_date = str(unit.get("date") or "")[:10]
        try:
            day = date.fromisoformat(plan_date)
        except ValueError:
            raise ValueError("Die Einheit hat kein gültiges Datum.") from None
        if day < self._today():
            raise ValueError("Vergangene Einheiten werden nicht an Garmin gesendet.")
        if sport is Sport.RUN:
            return plan_date, _run_document(unit, zones_for(unit))
        exercises = strength_structure.normalize_structure(
            unit.get("strength_structure"), stored=True
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
        """Whether the saved workout kept every sent exercise or run step."""
        saved = _call(client.get_workout_by_id, workout_id)
        running = (document.get("sportType") or {}).get("sportTypeKey") == "running"
        steps = comparable_steps if running else workout_exercise_steps
        return isinstance(saved, dict) and steps(saved) == steps(document)

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
            "Garmin hat das Workout nicht vollständig übernommen; nichts terminiert.",
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


def _no_zones(_unit: Mapping[str, Any]) -> ZoneSettings | None:
    return None


def _run_document(
    unit: Mapping[str, Any], zones: ZoneSettings | None
) -> dict[str, Any]:
    """The Garmin running workout of a run unit; relative targets need ``zones``."""
    description = str(unit.get("description") or "")
    capped = capped_description(description, unit, lthr=zones.lthr if zones else None)
    return run_workout(
        name=str(unit.get("name") or ""),
        description=f"{WORKOUT_MARKER}\n{description}",
        blocks=structured_blocks(capped, str(unit.get("target") or "AUTO")),
        targets=None
        if zones is None
        else GarminRunTargets(
            ftp=zones.ftp,
            threshold_hr=zones.lthr,
            max_hr=zones.max_hr,
            threshold_speed=zones.threshold_pace,
            hr_zone_basis=zones.hr_zone_reference,
            power_limits=zones.power_limits,
            hr_limits=zones.hr_limits,
            pace_limits=zones.pace_limits,
        ),
    )


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


def _app_created(workout: Any) -> bool:
    """Whether this app sent the workout: its description's first line is the marker."""
    if not isinstance(workout, dict):
        return False
    lines = str(workout.get("description") or "").splitlines()
    return bool(lines) and lines[0].strip() == WORKOUT_MARKER


def _strength_workout_ids(client: Any) -> list[str]:
    """The ids of the strength workouts in the athlete's Garmin library."""
    ids: list[str] = []
    for page in range(_CLEANUP_MAX_PAGES):
        rows = _call(client.get_workouts, page * _CLEANUP_PAGE, _CLEANUP_PAGE)
        rows = rows if isinstance(rows, list) else []
        ids.extend(
            str(row["workoutId"])
            for row in rows
            if isinstance(row, dict)
            and row.get("workoutId") is not None
            and (row.get("sportType") or {}).get("sportTypeKey") == "strength_training"
        )
        if len(rows) < _CLEANUP_PAGE:
            break
    return ids


def _scheduled_from(client: Any, today: date) -> set[str]:
    """Workouts scheduled on a day from today on: they stay."""
    last = today + timedelta(days=_CLEANUP_SCHEDULE_DAYS)
    items = _call(
        client.get_scheduled_workouts_by_period, today.isoformat(), last.isoformat()
    )
    owners: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        workout = item.get("workout")
        workout = workout if isinstance(workout, dict) else {}
        owner = item.get("workoutId") or workout.get("workoutId")
        if owner is not None:
            owners.add(str(owner))
    return owners


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
