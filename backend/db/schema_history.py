"""Frozen signatures of the schema shapes written by released versions.

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

SchemaSignature = tuple[tuple[str, str, str, str], ...]

# Release 1.12.19: no nutrition products, no no_training, no logged_time_known.
SHAPE_RELEASE_1_12_19: Final = "release-1.12.19"
# Schema version 2: adds nutrition products.
SHAPE_SCHEMA_V2: Final = "schema-v2"
# Schema versions 3 and 4: adds no_training.
SHAPE_SCHEMA_V3_V4: Final = "schema-v3-v4"
# The live schema of this build, derived from code rather than frozen.
SHAPE_CURRENT: Final = "current"

RELEASED_SHAPE_DIGESTS: Final[Mapping[str, str]] = {
    SHAPE_RELEASE_1_12_19: (
        "560a43d7d511cdbdaac97a82e0396b798517ba32a634ea01ad3b6e93f48d58fd"
    ),
    SHAPE_SCHEMA_V2: "e78102ce0f7a708a0ae916133d25d25c51ff4beac8568675b1fa184ded7f7cfb",
    SHAPE_SCHEMA_V3_V4: (
        "d894e341a01bf1a255c277d7a35a53b789a3626fa8d4a3f3d0335e6c45bac3b0"
    ),
}

# Stored PRAGMA user_version -> schema shapes that version is allowed to hold.
# Version 0 is the unversioned state left by early releases. When
# CURRENT_SCHEMA_VERSION is bumped, first freeze the outgoing live shape here
# (digest, fixture, lookup entry and upgrade step) so its databases stay
# recognizable.
ACCEPTED_SHAPES_BY_VERSION: Final[Mapping[int, frozenset[str]]] = {
    0: frozenset(
        {SHAPE_RELEASE_1_12_19, SHAPE_SCHEMA_V2, SHAPE_SCHEMA_V3_V4, SHAPE_CURRENT}
    ),
    1: frozenset({SHAPE_RELEASE_1_12_19}),
    2: frozenset({SHAPE_SCHEMA_V2}),
    3: frozenset({SHAPE_SCHEMA_V3_V4}),
    4: frozenset({SHAPE_SCHEMA_V3_V4}),
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
