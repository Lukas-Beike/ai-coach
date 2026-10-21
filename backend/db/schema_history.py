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

# Schema version 9, release 1.13.6: the oldest supported schema.
SHAPE_SCHEMA_V9: Final = "schema-v9"
# Schema version 10, release 1.13.16: canonical activity detail tables.
SHAPE_SCHEMA_V10: Final = "schema-v10"
# The live schema of this build, derived from code rather than frozen.
SHAPE_CURRENT: Final = "current"

RELEASED_SHAPE_DIGESTS: Final[Mapping[str, str]] = {
    SHAPE_SCHEMA_V9: "03a0a15ad8afb0a2f44d10e20211cbf8ae01fccae263cbf22edf15c16486cf6a",
    SHAPE_SCHEMA_V10: "42782c891c389a2a65d20fa9b984cf10a054ea258a77a44ee3d817ced86cbaa4",
}

# Stored PRAGMA user_version -> schema shapes that version is allowed to hold.
# When CURRENT_SCHEMA_VERSION is bumped, first freeze the outgoing live shape
# here (digest, fixture, lookup entry and upgrade step) so its databases stay
# recognizable.
ACCEPTED_SHAPES_BY_VERSION: Final[Mapping[int, frozenset[str]]] = {
    9: frozenset({SHAPE_SCHEMA_V9}),
    10: frozenset({SHAPE_SCHEMA_V10}),
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
