"""Frozen signatures of the schema shapes written by supported releases.

Only the schema production runs is frozen: the baseline. Its digest is the
SHA-256 of the normalized schema signature (object type, name, table and
whitespace-normalized SQL), computed once from the frozen fixture in
tests/fixtures and hard-coded here, so the runtime never reads fixture files.
The current shape is deliberately not frozen: it is derived from the live
schema in backend.db.schema.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Final

from backend.db.schema import CURRENT_SCHEMA_VERSION

type SchemaSignature = tuple[tuple[str, str, str, str], ...]

# Schema version 26, release 2.0.5: the schema production runs and the only
# supported baseline; the digest freezes it for its upgrade step.
SHAPE_SCHEMA_V26: Final = "schema-v26"
# Schema version 27, releases 2.1.2 to 2.1.9: the result of the baseline's
# product step. Its digest lets a v27 database take the later steps.
SHAPE_SCHEMA_V27: Final = "schema-v27"
# The live schema of this build, derived from code rather than frozen.
SHAPE_CURRENT: Final = "current"

RELEASED_SHAPE_DIGESTS: Final[Mapping[str, str]] = {
    SHAPE_SCHEMA_V26: "edbf1d3aa11f13e3bad44e233d9605d173c1370e6fc3ac67ad3abeda9bd0ea03",
    SHAPE_SCHEMA_V27: "203082d2a81ca06ab66307e37edbcbfe83e9a9c4e7b442124e360124175f193c",
}

# Releases before 2.0.5 wrote lower versions; they are rejected unchanged.
OLDEST_SUPPORTED_SCHEMA_VERSION: Final = 26

# Stored PRAGMA user_version -> schema shapes that version is allowed to hold.
# When CURRENT_SCHEMA_VERSION is bumped, accept the baseline shape for its
# version here and add one upgrade step from it; a schema that never reached
# production gets no frozen shape of its own.
ACCEPTED_SHAPES_BY_VERSION: Final[Mapping[int, frozenset[str]]] = {
    26: frozenset({SHAPE_SCHEMA_V26}),
    27: frozenset({SHAPE_SCHEMA_V27}),
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
