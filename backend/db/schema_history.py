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
# Schema version 11: the local food database mirror.
SHAPE_SCHEMA_V11: Final = "schema-v11"
# Schema version 12: Garmin payload elements in the raw layer.
SHAPE_SCHEMA_V12: Final = "schema-v12"
# Schema version 13: the maximum speed of a lap.
SHAPE_SCHEMA_V13: Final = "schema-v13"
# Schema version 14: Yazio food sources in the mirror and saved products.
SHAPE_SCHEMA_V14: Final = "schema-v14"
# The live schema of this build, derived from code rather than frozen.
SHAPE_CURRENT: Final = "current"

RELEASED_SHAPE_DIGESTS: Final[Mapping[str, str]] = {
    SHAPE_SCHEMA_V9: "03a0a15ad8afb0a2f44d10e20211cbf8ae01fccae263cbf22edf15c16486cf6a",
    SHAPE_SCHEMA_V10: "42782c891c389a2a65d20fa9b984cf10a054ea258a77a44ee3d817ced86cbaa4",
    SHAPE_SCHEMA_V11: "98d365e334aac2fd771ec625cf61a7925e61fed39c249335a18eaff69d15bd60",
    SHAPE_SCHEMA_V12: "7c953ad5b939077d4c4bcaef85bbce9600ec5d698ea503ee82af2848b99287d7",
    SHAPE_SCHEMA_V13: "f1fc5172dc01f2dec8a0f1a73387a7b1916652355e684d9b7d5d0ff277fef5c1",
    SHAPE_SCHEMA_V14: "36b275450a46830a245d882bc18b621104413d1f2f6b84fd721befdcd903746e",
}

# Stored PRAGMA user_version -> schema shapes that version is allowed to hold.
# When CURRENT_SCHEMA_VERSION is bumped, first freeze the outgoing live shape
# here (digest, fixture, lookup entry and upgrade step) so its databases stay
# recognizable.
ACCEPTED_SHAPES_BY_VERSION: Final[Mapping[int, frozenset[str]]] = {
    9: frozenset({SHAPE_SCHEMA_V9}),
    10: frozenset({SHAPE_SCHEMA_V10}),
    11: frozenset({SHAPE_SCHEMA_V11}),
    12: frozenset({SHAPE_SCHEMA_V12}),
    13: frozenset({SHAPE_SCHEMA_V13}),
    14: frozenset({SHAPE_SCHEMA_V14}),
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
