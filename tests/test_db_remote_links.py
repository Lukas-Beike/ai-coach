"""RemoteLinkRepository over the live schema."""

import sqlite3
import unittest
from typing import Any, cast

from backend.canonical.vocabulary import ProviderId, RemoteEntityKind, RemoteLinkState
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.schema import initialize_schema

INTERVALS = ProviderId.INTERVALS.value
OTHER = "synthetic-provider"


class RemoteLinkRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        initialize_schema(self.db)
        self.repository = RemoteLinkRepository()

    def link(self, local_id="1", provider=INTERVALS, **values) -> RemoteLink:
        values.setdefault("sync_state", RemoteLinkState.SYNCED)
        return RemoteLink(
            entity_kind=values.pop("entity_kind", RemoteEntityKind.COMPETITION),
            local_id=local_id,
            provider=provider,
            **values,
        )

    def test_get_returns_none_for_an_unknown_link(self) -> None:
        self.assertIsNone(
            self.repository.get(self.db, RemoteEntityKind.COMPETITION, "1", INTERVALS)
        )

    def test_upsert_inserts_then_updates_in_place(self) -> None:
        first = self.link(remote_id="9", remote_external_id="ext", baseline_hash="h1")
        self.repository.upsert(self.db, first)
        self.assertEqual(
            self.repository.get(self.db, RemoteEntityKind.COMPETITION, "1", INTERVALS),
            first,
        )

        second = self.link(
            remote_id="10",
            sync_state=RemoteLinkState.PENDING,
            last_synced_at="2026-10-01T08:00:00+00:00",
        )
        self.repository.upsert(self.db, second)
        self.assertEqual(
            self.repository.get(self.db, RemoteEntityKind.COMPETITION, "1", INTERVALS),
            second,
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM remote_links").fetchone()[0], 1
        )

    def test_one_entity_can_link_to_several_providers(self) -> None:
        self.repository.upsert(self.db, self.link(provider=OTHER, remote_id="a"))
        self.repository.upsert(self.db, self.link(provider=INTERVALS, remote_id="b"))
        links = self.repository.list_for_entity(
            self.db, RemoteEntityKind.COMPETITION, "1"
        )
        self.assertEqual([link.provider for link in links], [INTERVALS, OTHER])

    def test_remote_id_is_unique_per_provider_and_kind(self) -> None:
        self.repository.upsert(self.db, self.link("1", remote_id="9"))
        self.repository.upsert(self.db, self.link("2", provider=OTHER, remote_id="9"))
        self.repository.upsert(
            self.db,
            self.link("1", entity_kind=RemoteEntityKind.LIBRARY_WORKOUT, remote_id="9"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.upsert(self.db, self.link("3", remote_id="9"))

    def test_get_by_remote_id_finds_the_owning_link(self) -> None:
        stored = self.link("4", remote_id="77")
        self.repository.upsert(self.db, stored)
        self.assertEqual(
            self.repository.get_by_remote_id(
                self.db, RemoteEntityKind.COMPETITION, INTERVALS, "77"
            ),
            stored,
        )
        self.assertIsNone(
            self.repository.get_by_remote_id(
                self.db, RemoteEntityKind.COMPETITION, OTHER, "77"
            )
        )

    def test_delete_reports_whether_a_link_was_removed(self) -> None:
        self.repository.upsert(self.db, self.link(remote_id="9"))
        self.assertTrue(
            self.repository.delete(
                self.db, RemoteEntityKind.COMPETITION, "1", INTERVALS
            )
        )
        self.assertFalse(
            self.repository.delete(
                self.db, RemoteEntityKind.COMPETITION, "1", INTERVALS
            )
        )

    def test_list_for_provider_filters_by_kind(self) -> None:
        self.repository.upsert(self.db, self.link("1", remote_id="1"))
        self.repository.upsert(
            self.db,
            self.link("2", entity_kind=RemoteEntityKind.PLANNED_UNIT, remote_id="2"),
        )
        self.repository.upsert(self.db, self.link("3", provider=OTHER, remote_id="3"))
        self.assertEqual(
            [
                link.local_id
                for link in self.repository.list_for_provider(self.db, INTERVALS)
            ],
            ["1", "2"],
        )
        self.assertEqual(
            [
                link.local_id
                for link in self.repository.list_for_provider(
                    self.db, INTERVALS, RemoteEntityKind.PLANNED_UNIT
                )
            ],
            ["2"],
        )

    def test_invalid_vocabulary_and_identity_are_rejected_before_storage(self) -> None:
        with self.assertRaises(ValueError):
            RemoteLink(cast(Any, "not-a-kind"), "1", INTERVALS, RemoteLinkState.SYNCED)
        with self.assertRaises(ValueError):
            RemoteLink(
                RemoteEntityKind.COMPETITION, "1", INTERVALS, cast(Any, "not-a-state")
            )
        with self.assertRaises(ValueError):
            self.link(local_id="")
        with self.assertRaises(ValueError):
            self.link(remote_id="  ")
        with self.assertRaises(ValueError):
            self.link(sync_state=RemoteLinkState.SYNCED, remote_id=None)
        with self.assertRaises(ValueError):
            self.link(provider="")
        with self.assertRaises(ValueError):
            self.link(provider="p" * 65)


if __name__ == "__main__":
    unittest.main()
