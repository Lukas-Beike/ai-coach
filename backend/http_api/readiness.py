"""Safe infrastructure readiness checks for the public HTTP probe."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.schema import database_schema_is_current
from backend.runtime.maintenance import MaintenanceGate


class ReadinessService:
    """Report only bounded database, schema, storage, and maintenance state."""

    def __init__(
        self,
        manager: DatabaseManager,
        db_lock: Any,
        data_dir: Path,
        maintenance_gate: MaintenanceGate,
    ) -> None:
        self._manager = manager
        self._db_lock = db_lock
        self._data_dir = data_dir
        self._maintenance_gate = maintenance_gate

    def state(self) -> dict[str, Any]:
        checks = {
            "database": False,
            "schema": False,
            "data_directory": False,
            "maintenance": False,
        }
        try:
            with self._db_lock, self._manager.reader() as db:
                checks["database"] = bool(db.execute("SELECT 1").fetchone())
                checks["schema"] = database_schema_is_current(db)
        except Exception:  # noqa: BLE001, S110 - an infrastructure probe must fail closed.
            pass

        probe: Path | None = None
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".readiness-", suffix=".probe",
                dir=self._data_dir, delete=False,
            ) as handle:
                probe = Path(handle.name)
                handle.write(b"ok")
            checks["data_directory"] = True
        except OSError:
            pass
        finally:
            if probe is not None:
                try:
                    probe.unlink(missing_ok=True)
                except OSError:
                    pass

        maintenance = self._maintenance_gate.state()
        checks["maintenance"] = not bool(maintenance.get("active"))
        ready = all(checks.values())
        return {
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "checks": checks,
            "maintenance": {"active": bool(maintenance.get("active"))},
        }
