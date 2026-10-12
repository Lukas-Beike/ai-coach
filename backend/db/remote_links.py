"""Provider-neutral links between local entities and their remote counterparts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.canonical.vocabulary import (
    ProviderId,
    RemoteEntityKind,
    RemoteLinkState,
)

_MAX_PROVIDER_LENGTH = 64


@dataclass(frozen=True)
class RemoteLink:
    """One local entity as known at one remote provider.

    The identity is (entity_kind, local_id, provider). remote_id is the
    provider's own identifier and is unique per provider and entity kind.
    """

    entity_kind: RemoteEntityKind
    local_id: str
    provider: str
    sync_state: RemoteLinkState
    remote_id: str | None = None
    remote_external_id: str | None = None
    baseline_hash: str | None = None
    last_synced_at: str | None = None

    def __post_init__(self) -> None:
        # Coerce the closed vocabularies so a misspelled value is rejected here
        # rather than stored; the table only constrains their length.
        object.__setattr__(self, "entity_kind", RemoteEntityKind(self.entity_kind))
        object.__setattr__(self, "sync_state", RemoteLinkState(self.sync_state))
        _require_local_id(self.local_id)
        _require_provider(self.provider)
        if self.remote_id is not None and not self.remote_id.strip():
            raise ValueError("A remote id must be absent or non-blank.")
        if self.sync_state is RemoteLinkState.SYNCED and self.remote_id is None:
            raise ValueError("A synced remote link needs a remote id.")


@dataclass(frozen=True)
class _Slots:
    """The legacy remote-identifier slots of one record."""

    remote_id: str | None
    external_id: str | None
    baseline_hash: str | None
    last_synced_at: str | None


def _slot_text(value: Any) -> str | None:
    """Normalize a legacy slot like the schema-version-8 upgrade does."""
    if value is None:
        return None
    return str(value).strip() or None


def _payload_remote_event_id(raw_payload: Any) -> str | None:
    """Return the payload's scalar text/integer remote_event_id, else None."""
    try:
        payload = json.loads(raw_payload or "{}")
    except TypeError, ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("remote_event_id")
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    return _slot_text(value)


def _require_local_id(local_id: str) -> None:
    if not isinstance(local_id, str) or not local_id:
        raise ValueError("A remote link needs a non-empty local id.")


def _require_provider(provider: str) -> None:
    if not isinstance(provider, str) or not 1 <= len(provider) <= _MAX_PROVIDER_LENGTH:
        raise ValueError("A remote link needs a provider id of 1 to 64 characters.")


class RemoteLinkRepository:
    """Persist remote links on a caller-owned connection and transaction."""

    _COLUMNS = (
        "entity_kind, local_id, provider, remote_id, remote_external_id, "
        "baseline_hash, sync_state, last_synced_at"
    )

    @staticmethod
    def _link(row: Any) -> RemoteLink:
        return RemoteLink(
            entity_kind=RemoteEntityKind(row["entity_kind"]),
            local_id=row["local_id"],
            provider=row["provider"],
            remote_id=row["remote_id"],
            remote_external_id=row["remote_external_id"],
            baseline_hash=row["baseline_hash"],
            sync_state=RemoteLinkState(row["sync_state"]),
            last_synced_at=row["last_synced_at"],
        )

    def get(
        self,
        db: Any,
        entity_kind: RemoteEntityKind,
        local_id: str,
        provider: str,
    ) -> RemoteLink | None:
        row = db.execute(
            f"SELECT {self._COLUMNS} FROM remote_links "
            "WHERE entity_kind=? AND local_id=? AND provider=?",
            (RemoteEntityKind(entity_kind).value, local_id, provider),
        ).fetchone()
        return self._link(row) if row else None

    def get_by_remote_id(
        self,
        db: Any,
        entity_kind: RemoteEntityKind,
        provider: str,
        remote_id: str,
    ) -> RemoteLink | None:
        row = db.execute(
            f"SELECT {self._COLUMNS} FROM remote_links "
            "WHERE provider=? AND entity_kind=? AND remote_id=?",
            (provider, RemoteEntityKind(entity_kind).value, remote_id),
        ).fetchone()
        return self._link(row) if row else None

    def upsert(self, db: Any, link: RemoteLink) -> None:
        """Insert or replace the link; a remote id already used raises IntegrityError."""
        db.execute(
            f"INSERT INTO remote_links({self._COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(entity_kind, local_id, provider) DO UPDATE SET "
            "remote_id=excluded.remote_id, "
            "remote_external_id=excluded.remote_external_id, "
            "baseline_hash=excluded.baseline_hash, "
            "sync_state=excluded.sync_state, "
            "last_synced_at=excluded.last_synced_at",
            (
                link.entity_kind.value,
                link.local_id,
                link.provider,
                link.remote_id,
                link.remote_external_id,
                link.baseline_hash,
                link.sync_state.value,
                link.last_synced_at,
            ),
        )

    def delete(
        self,
        db: Any,
        entity_kind: RemoteEntityKind,
        local_id: str,
        provider: str,
    ) -> bool:
        return (
            db.execute(
                "DELETE FROM remote_links "
                "WHERE entity_kind=? AND local_id=? AND provider=?",
                (RemoteEntityKind(entity_kind).value, local_id, provider),
            ).rowcount
            > 0
        )

    def delete_for_entity(
        self, db: Any, entity_kind: RemoteEntityKind, local_id: str
    ) -> None:
        """Forget every provider's link of a local entity that no longer exists."""
        db.execute(
            "DELETE FROM remote_links WHERE entity_kind=? AND local_id=?",
            (RemoteEntityKind(entity_kind).value, local_id),
        )

    def refresh_from_slots(
        self, db: Any, entity_kind: RemoteEntityKind, local_id: str
    ) -> None:
        """Mirror the Intervals.icu legacy remote slots of one record.

        Call it on the same connection right after any write that can change a
        record's remote identifiers, so slot and link commit or roll back
        together. The link is derived exactly as the schema-version-8 upgrade
        derives it: a remote id (the calendar event id) makes it synced, an
        external id alone leaves it pending, and a record without either has no
        link. A remote id already held by another record stays with that record
        (the unique index allows one), as in the upgrade.
        """
        self._refresh(db, RemoteEntityKind(entity_kind), local_id, True)

    def _refresh(
        self,
        db: Any,
        entity_kind: RemoteEntityKind,
        local_id: str,
        settle_holder: bool,
    ) -> None:
        slots = self._read_slots(db, entity_kind, local_id)
        if slots is None or (slots.remote_id is None and slots.external_id is None):
            self.delete(db, entity_kind, local_id, ProviderId.INTERVALS.value)
            return
        remote_id = slots.remote_id
        if remote_id is not None:
            holder = self.get_by_remote_id(
                db, entity_kind, ProviderId.INTERVALS.value, remote_id
            )
            if holder is not None and holder.local_id != local_id:
                if settle_holder:
                    # The holder may only be stale (its slot moved in the same
                    # transaction); settle it once, then re-check the claim.
                    self._refresh(db, entity_kind, holder.local_id, False)
                    holder = self.get_by_remote_id(
                        db, entity_kind, ProviderId.INTERVALS.value, remote_id
                    )
                if holder is not None and holder.local_id != local_id:
                    remote_id = None
        self.upsert(
            db,
            RemoteLink(
                entity_kind=entity_kind,
                local_id=local_id,
                provider=ProviderId.INTERVALS.value,
                remote_id=remote_id,
                remote_external_id=slots.external_id,
                baseline_hash=slots.baseline_hash,
                sync_state=(
                    RemoteLinkState.SYNCED
                    if remote_id is not None
                    else RemoteLinkState.PENDING
                ),
                last_synced_at=slots.last_synced_at,
            ),
        )

    @staticmethod
    def _read_slots(
        db: Any, entity_kind: RemoteEntityKind, local_id: str
    ) -> _Slots | None:
        if entity_kind is RemoteEntityKind.COMPETITION:
            row = db.execute(
                "SELECT intervals_event_id AS remote_id, external_id, "
                "NULL AS baseline_hash, last_synced_at, NULL AS payload "
                "FROM competitions WHERE id=?",
                (local_id,),
            ).fetchone()
        elif entity_kind is RemoteEntityKind.PLANNED_UNIT:
            row = db.execute(
                "SELECT NULL AS remote_id, external_id, baseline_hash, "
                "last_synced_at, payload FROM planned_units WHERE local_id=?",
                (local_id,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT NULL AS remote_id, external_id, NULL AS baseline_hash, "
                "last_synced_at, payload FROM workout_library WHERE local_id=?",
                (local_id,),
            ).fetchone()
        if row is None:
            return None
        remote_id = (
            _slot_text(row["remote_id"])
            if entity_kind is RemoteEntityKind.COMPETITION
            else _payload_remote_event_id(row["payload"])
        )
        return _Slots(
            remote_id=remote_id,
            external_id=_slot_text(row["external_id"]),
            baseline_hash=row["baseline_hash"],
            last_synced_at=row["last_synced_at"],
        )

    def resolve_remote_id(
        self,
        db: Any,
        entity_kind: RemoteEntityKind,
        local_id: str,
        legacy_remote_id: Any = None,
    ) -> str | None:
        """Return the Intervals.icu remote id, preferring the link over the slot."""
        link = self.get(db, entity_kind, local_id, ProviderId.INTERVALS.value)
        if link is not None and link.remote_id is not None:
            return link.remote_id
        return _slot_text(legacy_remote_id)

    def resolve_remote_external_id(
        self,
        db: Any,
        entity_kind: RemoteEntityKind,
        local_id: str,
        legacy_external_id: Any = None,
    ) -> str | None:
        """Return the Intervals.icu external id, preferring the link over the slot."""
        link = self.get(db, entity_kind, local_id, ProviderId.INTERVALS.value)
        if link is not None and link.remote_external_id is not None:
            return link.remote_external_id
        return _slot_text(legacy_external_id)

    def list_for_entity(
        self, db: Any, entity_kind: RemoteEntityKind, local_id: str
    ) -> Sequence[RemoteLink]:
        """Return every provider's link of one local entity, ordered by provider."""
        return [
            self._link(row)
            for row in db.execute(
                f"SELECT {self._COLUMNS} FROM remote_links "
                "WHERE entity_kind=? AND local_id=? ORDER BY provider",
                (RemoteEntityKind(entity_kind).value, local_id),
            ).fetchall()
        ]

    def list_for_provider(
        self,
        db: Any,
        provider: str,
        entity_kind: RemoteEntityKind | None = None,
    ) -> Sequence[RemoteLink]:
        """Return a provider's links, optionally of one entity kind."""
        query = f"SELECT {self._COLUMNS} FROM remote_links WHERE provider=?"
        params: tuple[Any, ...] = (provider,)
        if entity_kind is not None:
            query += " AND entity_kind=?"
            params += (RemoteEntityKind(entity_kind).value,)
        query += " ORDER BY entity_kind, local_id"
        return [self._link(row) for row in db.execute(query, params).fetchall()]
