"""Resolve local canonical and legacy provider activity references at the boundary.

A caller may send either a local canonical id (``act_...``) or the legacy
Intervals.icu provider id. Resolution happens once, at the entry point, and
yields the provider id that every stored key and provider request uses. The
mapping is one-to-one with the ``local_activity_id`` that read surfaces report:
each Intervals.icu-primary session resolves to its own provider id, including a
duplicate session, so feedback keyed by either id stays reachable.

A duplicate session whose own primary is not Intervals.icu is an alias created by
session linking. It resolves through ``merged_into`` (following the chain, guarded
against cycles) to the first Intervals.icu-primary session that is not deleted.

Other Garmin- or Wahoo-primary sessions, deleted sessions and unknown ids pass
through unchanged so each caller keeps its existing not-found or validation
response.
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

    ``provider`` is None for an id that passed through unresolved, because the
    caller did not name a provider and no local session confirmed one.
    """

    activity_id: Any
    provider: str | None = None


class ActivityReferenceResolver(Protocol):
    def resolve(self, reference: Any) -> Any: ...

    def resolve_reference(self, reference: Any) -> ActivityReference: ...

    def local_ids(self, provider_activity_ids: Iterable[str]) -> dict[str, str]: ...


class ActivityReferences(ActivityReferenceResolver):
    """Resolve local activity ids through the canonical session rows."""

    def __init__(self, database_manager: Any) -> None:
        self._database_manager = database_manager

    def resolve(self, reference: Any) -> Any:
        """Return the Intervals.icu provider id for a local id, or the input unchanged."""
        return self.resolve_reference(reference).activity_id

    def resolve_reference(self, reference: Any) -> ActivityReference:
        """Return the reference with its owning provider when a local session confirms it.

        Only local ``act_`` ids carry a provider. Raw provider ids (for example
        the Intervals.icu id posted by the activity detail view) pass through
        with provider None: mapping them would need a provider-id lookup that
        the existing helpers do not offer for writes, and the stored key must
        stay the id the client sent. Feedback written that way keeps NULL
        provider until the client posts the local id.
        """
        if not isinstance(reference, str):
            return ActivityReference(reference)
        candidate = reference.strip()
        if not candidate.startswith(canonical_store.ACTIVITY_ID_PREFIX):
            return ActivityReference(reference)
        with self._database_manager.reader() as db:
            provider_activity_id = _intervals_provider_activity_id(db, candidate)
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


DUPLICATE_ID_FIELDS: Final = ("canonical_id", "duplicate_id")


def resolve_duplicate_ids(payload: Any, references: ActivityReferenceResolver) -> Any:
    """Return a duplicate-deletion payload with both activity ids resolved."""
    if not isinstance(payload, dict):
        return payload
    return {
        **payload,
        **{
            key: references.resolve(payload[key])
            for key in DUPLICATE_ID_FIELDS
            if key in payload
        },
    }


class NoActivityReferences(ActivityReferenceResolver):
    """Identity resolver for owners that are composed without a canonical store."""

    def resolve(self, reference: Any) -> Any:
        return reference

    def resolve_reference(self, reference: Any) -> ActivityReference:
        return ActivityReference(reference)

    def local_ids(self, provider_activity_ids: Iterable[str]) -> dict[str, str]:
        return {}


_MAX_ALIAS_DEPTH: Final = 64


def _intervals_provider_activity_id(db: Any, activity_id: str) -> str | None:
    seen: set[str] = set()
    current: str | None = activity_id
    while current is not None and current not in seen and len(seen) < _MAX_ALIAS_DEPTH:
        seen.add(current)
        session = canonical_store.activity_sessions_by_ids(db, [current]).get(current)
        if session is None or session["state"] == ActivitySessionState.DELETED.value:
            return None
        if session["primary_provider"] == ProviderId.INTERVALS.value:
            return str(session["primary_provider_activity_id"])
        merged_into = session["merged_into"]
        current = str(merged_into) if merged_into else None
    return None
