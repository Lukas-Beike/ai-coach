"""Fixture helper for tests that build a partial schema by hand."""

from __future__ import annotations

from typing import Any

from backend.db.schema import REMOTE_LINKS_DDL


def create_remote_links_table(db: Any) -> None:
    """Create the live remote_links table on a hand-built test schema."""
    for statement in REMOTE_LINKS_DDL.split(";"):
        if statement.strip():
            db.execute(statement)
