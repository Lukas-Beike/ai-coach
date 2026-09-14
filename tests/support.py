"""Reusable test setup; deliberately independent of any test case class."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


@contextmanager
def isolated_server(server, root: Path, *, app_password: str = ""):
    """Run application setup against temporary state and restore globals."""
    patches = (
        patch.object(server, "CONFIG", replace(server.CONFIG, app_password=app_password)),
        patch.object(server, "DATA_DIR", root),
        patch.object(server, "DB_PATH", root / "test.db"),
        patch.object(server, "LOG_PATH", root / "test.log"),
    )
    for item in patches:
        item.start()
    try:
        server.initialise_database()
        yield
    finally:
        if server.DATABASE_MANAGER:
            server.DATABASE_MANAGER.close()
        server.DATABASE_MANAGER = None
        server.DATABASE_MANAGER_SIGNATURE = None
        for item in reversed(patches):
            item.stop()

