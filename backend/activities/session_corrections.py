"""Athlete corrections of how provider records are bundled into canonical sessions.

The athlete confirms a bundle, splits one provider copy off it, or merges two
sessions the heuristics kept apart. Every correction marks the sessions it leaves
as athlete-confirmed, so session linking never merges them again, and records a
change-history receipt whose undo restores the touched session rows. Records,
provider data and feedback rows are never changed: feedback stays with the
session it was written for and follows that session's merges.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, Final

from backend import change_history
from backend.activities.session_linking import session_age
from backend.canonical.vocabulary import (
    ActivityLinkKind,
    ActivitySessionState,
    ProviderId,
)
from backend.db import canonical_store
from backend.errors import AppError
from backend.providers.source_labels import SourceView, provider_label

ENTITY_TYPE: Final = "activity_session"
# The receipt keeps every touched session row; bounded so it stays restorable.
MAX_CORRECTED_SESSIONS: Final = 16
_ACTIVE = ActivitySessionState.ACTIVE.value
_DUPLICATE = ActivitySessionState.DUPLICATE.value
_UNKNOWN = "Diese Aktivität ist nicht (mehr) vorhanden."
_NOT_IN_BUNDLE = "Diese Aufzeichnung gehört nicht zu der Aktivität."
_SINGLE = "Die Aktivität besteht nur aus einer Aufzeichnung."
_SAME = "Beide Angaben bezeichnen dieselbe Aktivität."
_SAME_ORIGIN = (
    "Beide Aktivitäten enthalten eine Aufzeichnung derselben Quelle und können "
    "nicht zusammengeführt werden."
)
_OTHER_DAY = "Nur Aktivitäten desselben Tages können zusammengeführt werden."
_TOO_LARGE = "Diese Aktivität ist zu groß für eine rücknehmbare Korrektur."


class SessionCorrectionService:
    """Own confirm, split and merge of canonical sessions with receipt and undo."""

    def __init__(
        self,
        database_manager: Any,
        clock: Callable[[], str],
        event_buffer: Any = None,
    ) -> None:
        self._database_manager = database_manager
        self._clock = clock
        self._event_buffer = event_buffer
        self._rows_cache: dict[str, dict[str, Any]] = {}

    def bundle(self, activity_id: str) -> dict[str, Any] | None:
        """Return the provider copies of a live session and the merge candidates."""
        with self._database_manager.read_snapshot() as db:
            survivor = _survivor(db, activity_id)
            if survivor is None:
                return None
            members = canonical_store.session_member_rows(db, survivor["activity_id"])
            candidates = (
                canonical_store.merge_candidate_rows(
                    db, str(survivor["local_date"]), survivor["activity_id"]
                )
                if survivor["local_date"]
                else []
            )
        return {
            "activity_id": survivor["activity_id"],
            "link_kind": survivor["link_kind"],
            "athlete_confirmed": bool(survivor["athlete_confirmed"]),
            "members": [_entry(row) for row in members],
            "merge_candidates": [
                _entry(row) for row in _mergeable_candidates(members, candidates)
            ],
        }

    def confirm(self, activity_id: str, *, source: str = "local") -> dict[str, Any]:
        """Confirm a session as it is bundled now."""

        def correct(db: Any, survivor: dict[str, Any]) -> list[str]:
            members = _member_sessions(db, survivor["activity_id"])
            survivor["athlete_confirmed"] = 1
            if len(members) > 1:
                survivor["link_kind"] = ActivityLinkKind.CONFIRMED.value
            return [survivor["activity_id"]]

        return self._correct(activity_id, correct, "confirmed", source)

    def split(
        self, activity_id: str, member_id: str, *, source: str = "local"
    ) -> dict[str, Any]:
        """Detach the provider copy created as ``member_id`` into its own session."""

        def correct(db: Any, survivor: dict[str, Any]) -> list[str]:
            members = _member_sessions(db, survivor["activity_id"])
            if member_id not in members:
                raise AppError(409, _NOT_IN_BUNDLE)
            if len(members) < 2:
                raise AppError(409, _SINGLE)
            survivor_id = survivor["activity_id"]
            touched = sorted(
                {*members, *canonical_store.session_bundle_ids(db, survivor_id)}
            )
            rows = self._rows(db, touched)
            remaining = [rows[session] for session in members if session != member_id]
            detached = rows[member_id]
            keep = (
                min(remaining, key=session_age)
                if member_id == survivor_id
                else rows[survivor_id]
            )
            keep_id = keep["activity_id"]
            if member_id == survivor_id:
                # Every alias and retaining deletion of the detached survivor,
                # with or without an active record, follows the kept bundle.
                _repoint(rows.values(), survivor_id, keep_id)
            keep.update(
                state=_ACTIVE,
                merged_into=None,
                athlete_confirmed=1,
                link_kind=_kind(len(remaining)),
            )
            detached.update(
                state=_ACTIVE,
                merged_into=None,
                athlete_confirmed=1,
                link_kind=ActivityLinkKind.SINGLE.value,
            )
            return touched

        return self._correct(activity_id, correct, "split", source)

    def merge(
        self, activity_id: str, other_id: str, *, source: str = "local"
    ) -> dict[str, Any]:
        """Merge two live sessions; the older one stays and the younger becomes its alias."""

        def correct(db: Any, first: dict[str, Any]) -> list[str]:
            second = _survivor(db, other_id)
            if second is None:
                raise AppError(404, _UNKNOWN)
            if second["activity_id"] == first["activity_id"]:
                raise AppError(409, _SAME)
            if second["local_date"] != first["local_date"]:
                raise AppError(409, _OTHER_DAY)
            origins = [
                {
                    _origin(row)
                    for row in canonical_store.session_member_rows(
                        db, row["activity_id"]
                    )
                }
                for row in (first, second)
            ]
            if origins[0] & origins[1]:
                raise AppError(409, _SAME_ORIGIN)
            keep, drop = sorted((first, second), key=session_age)
            touched = [
                *canonical_store.session_bundle_ids(db, keep["activity_id"]),
                *canonical_store.session_bundle_ids(db, drop["activity_id"]),
            ]
            rows = self._rows(db, touched)
            _repoint(rows.values(), drop["activity_id"], keep["activity_id"])
            rows[drop["activity_id"]].update(
                state=_DUPLICATE, merged_into=keep["activity_id"]
            )
            rows[keep["activity_id"]].update(
                athlete_confirmed=1, link_kind=ActivityLinkKind.CONFIRMED.value
            )
            return touched

        return self._correct(activity_id, correct, "merged", source)

    # Change-history hooks: the entity id lists the touched sessions.

    def current(
        self, db: Any, entity_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The bundling columns of the sessions one correction touched."""
        value = _value(
            canonical_store.session_correction_rows(db, entity_id.split(","))
        )
        return value, change_history.audit_projection(ENTITY_TYPE, value)

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        _current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Write the recorded session rows back; the current rows are not needed."""
        rows = (target or {}).get("sessions")
        if not isinstance(rows, list) or {
            str(row.get("activity_id")) for row in rows if isinstance(row, dict)
        } != set(entity_id.split(",")):
            raise AppError(409, "Die Änderungshistorie ist beschädigt.")
        canonical_store.write_session_correction_rows(db, rows, now=self._clock())
        return target

    def _correct(
        self,
        activity_id: str,
        correct: Callable[[Any, dict[str, Any]], list[str]],
        status: str,
        source: str,
    ) -> dict[str, Any]:
        self._rows_cache = {}
        with self._database_manager.unit_of_work() as db:
            survivor = _survivor(db, activity_id)
            if survivor is None:
                raise AppError(404, _UNKNOWN)
            self._rows_cache[survivor["activity_id"]] = survivor
            touched = sorted(set(correct(db, survivor)))
            if len(touched) > MAX_CORRECTED_SESSIONS:
                raise AppError(409, _TOO_LARGE)
            before = _value(canonical_store.session_correction_rows(db, touched))
            changed = [self._rows(db, touched)[session] for session in touched]
            canonical_store.write_session_correction_rows(
                db, changed, now=self._clock()
            )
            after = _value(canonical_store.session_correction_rows(db, touched))
            change = change_history.record_change(
                db,
                ENTITY_TYPE,
                ",".join(touched),
                "update",
                before,
                after,
                source=source,
            )
        self._publish()
        return {
            "status": status,
            "activity_id": survivor["activity_id"]
            if survivor["state"] == _ACTIVE
            else survivor["merged_into"],
            "change": None
            if change is None
            else {key: change[key] for key in change_history.UNDO_REFERENCE_FIELDS},
        }

    def _rows(self, db: Any, session_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """The working copies of session rows; a correction edits them in place."""
        missing = [
            session for session in session_ids if session not in self._rows_cache
        ]
        for row in canonical_store.session_correction_rows(db, missing):
            self._rows_cache[str(row["activity_id"])] = dict(row)
        return {session: self._rows_cache[session] for session in session_ids}

    def _publish(self) -> None:
        if self._event_buffer is not None:
            self._event_buffer.publish("provider", {"status": "sessions_corrected"})


def _survivor(db: Any, activity_id: str) -> dict[str, Any] | None:
    """The live session ``activity_id`` resolves to through its merges."""
    reference = str(activity_id or "").strip()
    if not reference:
        return None
    effective = canonical_store.effective_session_ids(db, [reference]).get(reference)
    if effective is None:
        return None
    rows = canonical_store.session_correction_rows(db, [effective])
    if not rows or rows[0]["state"] != _ACTIVE:
        return None
    return dict(rows[0])


def _origin(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["provider"]), str(row["recorded_by"])


def _mergeable_candidates(
    members: Sequence[dict[str, Any]], candidates: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Drop candidate sessions a merge would refuse for sharing a recording origin."""
    own = {_origin(row) for row in members}
    refused = {row["session_id"] for row in candidates if _origin(row) in own}
    return [row for row in candidates if row["session_id"] not in refused]


def _repoint(rows: Iterable[dict[str, Any]], old: str, new: str) -> None:
    """Point the aliases and retaining deletions of ``old`` at ``new``."""
    for row in rows:
        if row["merged_into"] == old:
            row["merged_into"] = new
        if row["merged_into_retained"] == old:
            row["merged_into_retained"] = new


def _member_sessions(db: Any, survivor_id: str) -> list[str]:
    """The sessions whose active records the live session bundles, survivor first."""
    members = {
        str(row["session_id"])
        for row in canonical_store.session_member_rows(db, survivor_id)
    }
    return sorted(members, key=lambda session: (session != survivor_id, session))


def _value(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sessions": [
            {
                column: (
                    bool(row[column]) if column == "athlete_confirmed" else row[column]
                )
                for column in canonical_store.SESSION_CORRECTION_COLUMNS
            }
            for row in rows
        ]
    }


def _kind(members: int) -> str:
    return (
        ActivityLinkKind.CONFIRMED.value
        if members > 1
        else ActivityLinkKind.SINGLE.value
    )


def _label(value: Any) -> str | None:
    try:
        return provider_label(ProviderId(value), SourceView.ACTIVITY_DETAIL)
    except ValueError:
        return None


def _entry(row: dict[str, Any]) -> dict[str, Any]:
    """One provider copy; its label names the recording device when it differs."""
    label = _label(row["provider"]) or str(row["provider"])
    origin = _label(row["recorded_by"])
    if origin and origin != label:
        label = f"{label} ({origin})"
    return {
        "session_id": row["session_id"],
        "provider": row["provider"],
        "label": label,
        "recorded_by": row["recorded_by"],
        "sport": row["sport"],
        "started_at": row["started_at"],
        "duration_s": row["duration_s"],
        "distance_m": row["distance_m"],
        "name": row["name"],
    }
