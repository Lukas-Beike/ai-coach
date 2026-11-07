"""Background runs of the automatic metric export after local or Wahoo changes.

A Garmin sync runs the automatic export itself, inside its job. A local zone
change and a successful Wahoo sync request a run here instead, off the request
thread (#1729). A request waits ``delay_seconds`` first, so the change that asked
for it has committed and quick successive edits share one run; a request while a
run is active asks for one more run. Each run holds the maintenance gate, so a
restore never overlaps it, and records its status line for the provider card.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any, Final, Protocol

from backend.canonical.vocabulary import ProviderId
from backend.sync.metric_export import automatic_export_message

_LOGGER = logging.getLogger("intervals_coach")
DEFAULT_DELAY_SECONDS: Final = 5.0


class AutomaticMetricExport(Protocol):
    def sync_automatic(self) -> dict[str, Any] | None: ...

    def record_status(self, message: str) -> None: ...


class OperationGate(Protocol):
    """The maintenance gate: a restore waits for an open operation."""

    def operation(self) -> AbstractContextManager[Any]: ...


class MetricExportRunner:
    def __init__(
        self,
        service: Callable[[], AutomaticMetricExport],
        *,
        enabled: Callable[[], bool],
        maintenance_gate: Callable[[], OperationGate],
        delay_seconds: float = DEFAULT_DELAY_SECONDS,
        thread_factory: Callable[..., threading.Thread] | None = None,
    ) -> None:
        self._service = service
        self._enabled = enabled
        self._maintenance_gate = maintenance_gate
        self._delay_seconds = delay_seconds
        self._thread_factory = thread_factory or threading.Thread
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        # Guarded by _lock: True from start until the thread decided to exit.
        self._active = False
        self._rerun = False

    def request(self) -> None:
        """Start a delayed run, or ask the active thread for one more."""
        if not self._enabled():
            return
        with self._lock:
            if self._active:
                self._rerun = True
                return
            self._active = True
            self._rerun = False
            self._stop_event.clear()
            self._thread_factory(
                target=self._run_loop, name="metric-export", daemon=True
            ).start()

    def after_job(self, job: Mapping[str, Any]) -> None:
        """A sync-job hook: a successful Wahoo job can change the resolved FTP."""
        if job.get("provider") == ProviderId.WAHOO.value:
            self.request()

    def stop(self) -> None:
        """Cancel a pending run; an active run finishes its current write."""
        self._stop_event.set()

    @staticmethod
    def _log_failure(exc: Exception) -> None:
        _LOGGER.warning(
            "Automatic metric export failed",
            extra={
                "event": "metric_export_automatic_failed",
                "error_class": type(exc).__name__,
            },
        )

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.wait(self._delay_seconds):
                with self._lock:
                    self._rerun = False
                self._run_once()
                with self._lock:
                    if not self._rerun:
                        return
        finally:
            with self._lock:
                self._active = False

    def _run_once(self) -> None:
        try:
            service = self._service()
        except Exception as exc:  # noqa: BLE001 - a background run never raises
            self._log_failure(exc)
            return
        try:
            with self._maintenance_gate().operation():
                receipt = service.sync_automatic()
        except Exception as exc:  # noqa: BLE001 - a background run never raises
            self._log_failure(exc)
            message = (
                "Automatischer Abgleich mit Intervals.icu fehlgeschlagen; "
                "erneuter Versuch beim nächsten Sync."
            )
        else:
            if receipt is None:
                return
            message = automatic_export_message(receipt)
        try:
            service.record_status(message)
        except Exception as exc:  # noqa: BLE001 - logging only, no content
            _LOGGER.warning(
                "Automatic metric export status could not be recorded",
                extra={
                    "event": "metric_export_status_failed",
                    "error_class": type(exc).__name__,
                },
            )
