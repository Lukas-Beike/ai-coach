"""Every metric kind and load model is accounted for by actual code.

The check reads the backend source: a member is produced when a provider mapper
(``backend/providers``) names it, and consumed when a reader outside the canonical
infrastructure names it (the vocabulary, persistence, diagnostics, backup and the
table reader only store, count or decode values). A member without a producer or
a consumer must be listed with its reason in ``backend.canonical.vocabulary``, and
a listed member that gained one must leave the list, so the lists stay true.
Listed members stay in the vocabulary: stored text values must remain readable.
"""

from __future__ import annotations

import ast
import sqlite3
import tempfile
import unittest
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from backend.canonical import vocabulary
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    EXPORT_ONLY_METRIC_KINDS,
    UNPRODUCED_LOAD_MODELS,
    UNPRODUCED_METRIC_KINDS,
    LoadModel,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
)
from backend.db import canonical_store, row_factory
from backend.db.schema import initialize_schema
from backend.providers.canonical_plans import current_observation_mapper_versions
from backend.sync.canonical_table_reader import CanonicalTableReader

BACKEND = Path(__file__).resolve().parent.parent / "backend"
PRODUCER_ROOTS = ("providers/",)
# Infrastructure that stores, counts, decodes or exports values for any kind.
NOT_CONSUMERS = (
    "providers/",
    "canonical/",
    "db/",
    "diagnostics/",
    "backup/",
    "sync/canonical_table_reader.py",
)


def references(sources: Mapping[str, str], enum_name: str) -> dict[str, set[str]]:
    """Map each member name of ``enum_name`` to the sources that name it in code."""
    found: dict[str, set[str]] = {}
    for path, text in sources.items():
        for node in ast.walk(ast.parse(text)):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == enum_name
            ):
                found.setdefault(node.attr, set()).add(path)
    return found


def accountability_problems[Member: StrEnum](
    members: Iterable[Member],
    sources: Mapping[str, str],
    *,
    unproduced: Mapping[Member, str],
    export_only: Mapping[Member, str] | None,
) -> list[str]:
    """Return one line per member whose code use and documented status disagree.

    ``export_only`` None skips the consumer side.
    """
    listed = list(members)
    if not listed:
        return []
    named = references(sources, type(listed[0]).__name__)
    problems: list[str] = []
    for member in listed:
        paths = named.get(member.name, set())
        produced = any(path.startswith(PRODUCER_ROOTS) for path in paths)
        consumed = any(not path.startswith(NOT_CONSUMERS) for path in paths)
        if produced == (member in unproduced):
            problems.append(
                f"{member.name}: "
                + ("listed as unproduced but produced" if produced else "no producer")
            )
        if export_only is not None and consumed == (member in export_only):
            problems.append(
                f"{member.name}: "
                + ("listed as export-only but read" if consumed else "no consumer")
            )
        for listing in (unproduced, export_only or {}):
            if member in listing and not listing[member].strip():
                problems.append(f"{member.name}: listed without a reason")
    return problems


def backend_sources() -> dict[str, str]:
    return {
        path.relative_to(BACKEND).as_posix(): path.read_text(encoding="utf-8")
        for path in BACKEND.rglob("*.py")
        if "__pycache__" not in path.parts
    }


class VocabularyAccountabilityTests(unittest.TestCase):
    sources = backend_sources()

    def test_every_metric_kind_has_a_producer_and_a_consumer_or_a_reason(
        self,
    ) -> None:
        self.assertEqual(
            accountability_problems(
                MetricKind,
                self.sources,
                unproduced=UNPRODUCED_METRIC_KINDS,
                export_only=EXPORT_ONLY_METRIC_KINDS,
            ),
            [],
        )

    def test_every_load_model_is_a_provider_model_or_has_a_reason(self) -> None:
        self.assertEqual(
            accountability_problems(
                [member for member in LoadModel if member is not LoadModel.UNKNOWN],
                self.sources,
                unproduced=UNPRODUCED_LOAD_MODELS,
                export_only=None,
            ),
            [],
        )

    def test_load_models_are_provider_models_only(self) -> None:
        for member in LoadModel:
            with self.subTest(member=member):
                self.assertNotIn("rpe", member.value)

    def test_an_orphan_kind_is_rejected(self) -> None:
        class Kind(StrEnum):
            USED = "used"
            ORPHAN = "orphan"

        sources = {
            "providers/mapper.py": "x = Kind.USED\n",
            "performance/reader.py": "y = Kind.USED\n# Kind.ORPHAN in a comment\n",
            "diagnostics/counts.py": "z = Kind.ORPHAN\n",
        }
        self.assertEqual(
            accountability_problems(Kind, sources, unproduced={}, export_only={}),
            ["ORPHAN: no producer", "ORPHAN: no consumer"],
        )
        self.assertEqual(
            accountability_problems(
                Kind,
                sources,
                unproduced={Kind.ORPHAN: "kept readable"},
                export_only={Kind.ORPHAN: "kept for export"},
            ),
            [],
        )

    def test_a_stale_or_unexplained_listing_is_rejected(self) -> None:
        class Kind(StrEnum):
            USED = "used"

        sources = {
            "providers/mapper.py": "x = Kind.USED\n",
            "planning/reader.py": "y = Kind.USED\n",
        }
        self.assertEqual(
            accountability_problems(
                Kind,
                sources,
                unproduced={Kind.USED: "stale"},
                export_only={Kind.USED: " "},
            ),
            [
                "USED: listed as unproduced but produced",
                "USED: listed as export-only but read",
                "USED: listed without a reason",
            ],
        )

    def test_listed_members_stay_in_the_vocabulary(self) -> None:
        for listing in (
            UNPRODUCED_METRIC_KINDS,
            EXPORT_ONLY_METRIC_KINDS,
            UNPRODUCED_LOAD_MODELS,
        ):
            for member in listing:
                with self.subTest(member=member):
                    self.assertIs(type(member)(member.value), member)
                    self.assertIn(member, vars(vocabulary)[type(member).__name__])


class RetainedKindStorageTests(unittest.TestCase):
    def test_a_stored_unproduced_kind_is_still_read(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = sqlite3.connect(Path(folder) / "retained.db")
            try:
                db.row_factory = row_factory
                initialize_schema(db)
                observation = Observation(
                    kind=MetricKind.TRAINING_LOAD,
                    value=MetricValue(55.0, MetricKind.TRAINING_LOAD.unit),
                    observed_on=date(2026, 10, 10),
                    observed_at=None,
                    provenance=Provenance(
                        provider=ProviderId.GARMIN,
                        source_kind=SourceKind.PROVIDER_REPORTED,
                        source_record_id="legacy",
                        recorded_by=RecordingOrigin.GARMIN,
                        retrieved_at=datetime(2026, 10, 10, tzinfo=UTC),
                        label="Garmin Connect",
                    ),
                )
                canonical_store.upsert_observation(
                    db,
                    observation,
                    mapper_version=current_observation_mapper_versions()["garmin"],
                    now="2026-10-10T00:00:00+00:00",
                )
                (stored,) = CanonicalTableReader().observations(
                    db, MetricKind.TRAINING_LOAD
                )
            finally:
                db.close()
        self.assertEqual(stored.value.value, 55.0)


if __name__ == "__main__":
    unittest.main()
