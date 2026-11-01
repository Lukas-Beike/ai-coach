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

# Schema version 16, release 1.13.32: the oldest supported schema.
SHAPE_SCHEMA_V16: Final = "schema-v16"
# Schema version 17: the canonical power curve.
SHAPE_SCHEMA_V17: Final = "schema-v17"
# Schema version 18: feedback rating time.
SHAPE_SCHEMA_V18: Final = "schema-v18"
# The live schema of this build, derived from code rather than frozen.
SHAPE_CURRENT: Final = "current"

RELEASED_SHAPE_DIGESTS: Final[Mapping[str, str]] = {
    SHAPE_SCHEMA_V16: "3f68b3c7b91a0882c930e93acab9e560ebf9d53ae3fa9befe118fa8b4a633131",
    SHAPE_SCHEMA_V17: "68d69b318f579be15d6bf15eeebccbffac66480296ffc46b876ac0858043c9ee",
    SHAPE_SCHEMA_V18: "ad1f1d68b73dfc400e281bd5aed00798dfee0dfb11e2a177d8bdc1f3c1563bda",
}

# Stored PRAGMA user_version -> schema shapes that version is allowed to hold.
# When CURRENT_SCHEMA_VERSION is bumped, first freeze the outgoing live shape
# here (digest, fixture, lookup entry and upgrade step) so its databases stay
# recognizable.
ACCEPTED_SHAPES_BY_VERSION: Final[Mapping[int, frozenset[str]]] = {
    16: frozenset({SHAPE_SCHEMA_V16}),
    17: frozenset({SHAPE_SCHEMA_V17}),
    18: frozenset({SHAPE_SCHEMA_V18}),
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
