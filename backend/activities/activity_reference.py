"""Resolve local canonical and legacy provider activity references at the boundary.

A caller may send either a local canonical id (``act_...``) or the legacy
Intervals.icu provider id. Resolution happens once, at the entry point, and
yields the provider id that every stored key and provider request uses. The
mapping is one-to-one with the ``local_activity_id`` that read surfaces report:
each session resolves to its own provider id, including a duplicate session.

Only Intervals.icu-primary sessions that are not deleted resolve. Garmin-primary
sessions, deleted sessions and unknown ids pass through unchanged so each caller
keeps its existing not-found or validation response.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from backend.canonical.vocabulary import ActivitySessionState, ProviderId
from backend.db import canonical_store


class ActivityReferenceResolver(Protocol):
    def resolve(self, reference: Any) -> Any: ...

    def local_ids(self, provider_activity_ids: Iterable[str]) -> dict[str, str]: ...


class ActivityReferences(ActivityReferenceResolver):
    """Resolve local activity ids through the canonical session rows."""

    def __init__(self, database_manager: Any) -> None:
        self._database_manager = database_manager

    def resolve(self, reference: Any) -> Any:
        """Return the Intervals.icu provider id for a local id, or the input unchanged."""
        if not isinstance(reference, str):
            return reference
        candidate = reference.strip()
        if not candidate.startswith(canonical_store.ACTIVITY_ID_PREFIX):
            return reference
        with self._database_manager.reader() as db:
            provider_activity_id = _intervals_provider_activity_id(db, candidate)
        return reference if provider_activity_id is None else provider_activity_id

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

    def local_ids(self, provider_activity_ids: Iterable[str]) -> dict[str, str]:
        return {}


def _intervals_provider_activity_id(db: Any, activity_id: str) -> str | None:
    session = canonical_store.activity_sessions_by_ids(db, [activity_id]).get(
        activity_id
    )
    if session is None:
        return None
    if session["primary_provider"] != ProviderId.INTERVALS.value:
        return None
    if session["state"] == ActivitySessionState.DELETED.value:
        return None
    return str(session["primary_provider_activity_id"])
