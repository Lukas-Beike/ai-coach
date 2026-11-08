"""Resolve activity references at the boundary.

A caller may send a local canonical id (``act_...``), the id of a provider record
or the id of an alias session. ``resolve_reference`` leads any of them to the live
effective session id, following ``merged_into`` and, for an alias deleted with
its survivor retained, ``merged_into_retained``. That session id is the one key
feedback, equipment assignments and session metrics are stored under. A
reference that leads to no live session passes through unchanged so each caller
keeps its own not-found or validation response.

The provider calls (detail refresh) and the duplicate deletion still need the
Intervals.icu record id of a session while that ingest data exists:
``provider_reference`` finds it through a session's primary record, a merged
Intervals.icu record or the survivor a deleted alias retained; the strict
``resolve`` (duplicate deletion, detail jobs) uses the primary alone and passes
deleted sessions through.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from backend.canonical.vocabulary import ActivitySessionState, ProviderId
from backend.db import canonical_store


@dataclass(frozen=True)
class ActivityReference:
    """A resolved activity id and the provider that owns it, when known.

    ``provider`` is set only for an Intervals.icu record id from
    ``provider_reference``; a session id or an unresolved id carries None.
    """

    activity_id: Any
    provider: str | None = None


class ActivityReferenceResolver(Protocol):
    def resolve(self, reference: Any) -> Any: ...

    def resolve_reference(self, reference: Any) -> ActivityReference: ...

    def provider_reference(self, reference: Any) -> ActivityReference: ...

    def local_ids(self, provider_activity_ids: Iterable[str]) -> dict[str, str]: ...


class ActivityReferences(ActivityReferenceResolver):
    """Resolve activity references through the canonical session rows."""

    def __init__(self, database_manager: Any) -> None:
        self._database_manager = database_manager

    def resolve(self, reference: Any) -> Any:
        """Return the Intervals.icu provider id of a primary session, or the input."""
        return self._provider(reference, merged_copies=False).activity_id

    def provider_reference(self, reference: Any) -> ActivityReference:
        """Return the Intervals.icu record id of a session, merged copies included."""
        return self._provider(reference, merged_copies=True)

    def resolve_reference(self, reference: Any) -> ActivityReference:
        """Return the session a reference was written for, else the input.

        A provider record id leads to the session of that record, an ``act_`` id
        stays as given, so athlete data is stored under the session it belongs
        to and stays with it when a bundle is split. A deleted alias leads to
        the live survivor it retained. Readers resolve merges themselves.
        """
        if not isinstance(reference, str) or not reference.strip():
            return ActivityReference(reference)
        text = reference.strip()
        with self._database_manager.reader() as db:
            # An id that names several records stays unresolved.
            origin = canonical_store.feedback_origin_sessions(db, [(text, None)])
            live = (
                canonical_store.live_session_id(db, origin[text])
                if text in origin
                else None
            )
            state = (
                canonical_store.activity_sessions_by_ids(db, [origin[text]])[
                    origin[text]
                ]["state"]
                if live is not None
                else None
            )
        if live is None:
            return ActivityReference(reference)
        deleted = state == ActivitySessionState.DELETED.value
        return ActivityReference(live if deleted else origin[text])

    def _provider(self, reference: Any, *, merged_copies: bool) -> ActivityReference:
        """Resolve a local ``act_`` id to its Intervals.icu record id.

        Raw provider ids pass through with provider None.
        """
        if not isinstance(reference, str):
            return ActivityReference(reference)
        candidate = reference.strip()
        if not candidate.startswith(canonical_store.ACTIVITY_ID_PREFIX):
            return ActivityReference(reference)
        with self._database_manager.reader() as db:
            provider_activity_id = _intervals_provider_activity_id(
                db, candidate, follow_retained=merged_copies
            )
            if provider_activity_id is None and merged_copies:
                record = canonical_store.activity_record_for_session(
                    db, ProviderId.INTERVALS.value, candidate
                )
                if record is not None:
                    provider_activity_id = str(record["provider_activity_id"])
        if provider_activity_id is None:
            return ActivityReference(reference)
        return ActivityReference(provider_activity_id, ProviderId.INTERVALS.value)

    def local_ids(self, provider_activity_ids: Iterable[str]) -> dict[str, str]:
        """Return local ids for provider ids that have a canonical record."""
        ids = [str(value) for value in provider_activity_ids if value]
        if not ids:
            return {}
        with self._database_manager.reader() as db:
            return canonical_store.activity_local_ids(
                db, ProviderId.INTERVALS.value, ids
            )


class NoActivityReferences(ActivityReferenceResolver):
    """Identity resolver for owners that are composed without a canonical store."""

    def resolve(self, reference: Any) -> Any:
        return reference

    def resolve_reference(self, reference: Any) -> ActivityReference:
        return ActivityReference(reference)

    def provider_reference(self, reference: Any) -> ActivityReference:
        return ActivityReference(reference)

    def local_ids(self, provider_activity_ids: Iterable[str]) -> dict[str, str]:
        return {}


_MAX_ALIAS_DEPTH: Final = 64


def _intervals_provider_activity_id(
    db: Any, activity_id: str, *, follow_retained: bool
) -> str | None:
    seen: set[str] = set()
    current: str | None = activity_id
    while current is not None and current not in seen and len(seen) < _MAX_ALIAS_DEPTH:
        seen.add(current)
        session = canonical_store.activity_sessions_by_ids(db, [current]).get(current)
        if session is None:
            return None
        if session["primary_provider"] == ProviderId.INTERVALS.value and (
            session["state"] != ActivitySessionState.DELETED.value
        ):
            return str(session["primary_provider_activity_id"])
        current = _next_alias(session, follow_retained=follow_retained)
    return None


def _next_alias(session: Any, *, follow_retained: bool) -> str | None:
    """The session an alias points at; a deleted one only keeps its retained target.

    A deleted session leads nowhere unless ``follow_retained`` asks for the survivor
    its deletion retained.
    """
    if session["state"] == ActivitySessionState.DELETED.value:
        retained = session["merged_into_retained"] if follow_retained else None
        return str(retained) if retained else None
    merged_into = session["merged_into"]
    return str(merged_into) if merged_into else None
