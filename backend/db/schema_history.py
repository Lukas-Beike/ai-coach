"""Frozen signatures of the schema shapes written by supported releases.

Each digest is the SHA-256 of the normalized schema signature (object type,
name, table and whitespace-normalized SQL) of one released shape. The digests
were computed once from the frozen fixtures in tests/fixtures and are
hard-coded here, so the runtime never reads fixture files. The current shape is
deliberately not frozen: it is derived from the live schema in
backend.db.schema.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final

from backend.db.schema import CURRENT_SCHEMA_VERSION

type SchemaSignature = tuple[tuple[str, str, str, str], ...]

# Schema version 21, releases 1.13.41 to 1.13.44: the observation lifecycle and
# the oldest supported schema.
SHAPE_SCHEMA_V21: Final = "schema-v21"
# Schema version 22: executed strength sets.
SHAPE_SCHEMA_V22: Final = "schema-v22"
# Schema version 23: the athlete's session purpose marking.
SHAPE_SCHEMA_V23: Final = "schema-v23"
# The live schema of this build, derived from code rather than frozen.
SHAPE_CURRENT: Final = "current"

RELEASED_SHAPE_DIGESTS: Final[Mapping[str, str]] = {
    SHAPE_SCHEMA_V21: "2d81edf3d70d6b81e3eb9b048fc9fefb0c9c4a70885c14cd9848fd18b0cd2052",
    SHAPE_SCHEMA_V22: "cfb3171eb12a18c5eaa91f1bd71458d00f4b60a17da28f5a0d674b2a49691faf",
    SHAPE_SCHEMA_V23: "86b67a1f09a92430e6cc939fe710cb38b04dba715d4e35d8edb7284a758d7082",
}

# Releases before 1.13.41 wrote lower versions; they are rejected unchanged.
OLDEST_SUPPORTED_SCHEMA_VERSION: Final = 21

# Stored PRAGMA user_version -> schema shapes that version is allowed to hold.
# When CURRENT_SCHEMA_VERSION is bumped, first freeze the outgoing live shape
# here (digest, fixture, lookup entry and upgrade step) so its databases stay
# recognizable.
ACCEPTED_SHAPES_BY_VERSION: Final[Mapping[int, frozenset[str]]] = {
    21: frozenset({SHAPE_SCHEMA_V21}),
    22: frozenset({SHAPE_SCHEMA_V22}),
    23: frozenset({SHAPE_SCHEMA_V23}),
    CURRENT_SCHEMA_VERSION: frozenset({SHAPE_CURRENT}),
}


def signature_digest(signature: SchemaSignature) -> str:
    """Return the canonical SHA-256 digest of a normalized schema signature."""
    payload = json.dumps(
        [list(entry) for entry in signature], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def released_shape(signature: SchemaSignature) -> str | None:
    """Return the frozen released shape that matches a signature, if any."""
    digest = signature_digest(signature)
    for shape, expected in RELEASED_SHAPE_DIGESTS.items():
        if digest == expected:
            return shape
    return None
