"""Provider-neutral links between local entities and their remote counterparts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.canonical.vocabulary import RemoteEntityKind, RemoteLinkState

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
