"""Resolve activity references at the boundary.

A caller may send a local canonical id (``act_...``), the id of a provider record
or the id of an alias session. ``resolve_reference`` leads any of them to the live
effective session id, following ``merged_into`` and, for an alias deleted with
its survivor retained, ``merged_into_retained``. That session id is the one key
feedback, equipment assignments and session metrics are stored under. A
reference that leads to no live session passes through unchanged so each caller
keeps its own not-found or validation response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.canonical.vocabulary import ActivitySessionState
from backend.db import canonical_store


@dataclass(frozen=True)
class ActivityReference:
    """A resolved activity id and the provider that owns it, when known.

    ``provider`` is None for a session id or an unresolved id.
    """

    activity_id: Any
    provider: str | None = None


class ActivityReferenceResolver(Protocol):
    def resolve_reference(self, reference: Any) -> ActivityReference: ...


class ActivityReferences(ActivityReferenceResolver):
    """Resolve activity references through the canonical session rows."""

    def __init__(self, database_manager: Any) -> None:
        self._database_manager = database_manager

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


class NoActivityReferences(ActivityReferenceResolver):
    """Identity resolver for owners that are composed without a canonical store."""

    def resolve_reference(self, reference: Any) -> ActivityReference:
        return ActivityReference(reference)
