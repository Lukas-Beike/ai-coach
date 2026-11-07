"""Background runs of the automatic metric export (#1729)."""

from __future__ import annotations

import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from backend.sync.executor import chained_after_job
from backend.sync.metric_export_runner import MetricExportRunner


class _Gate:
    def __init__(self) -> None:
        self.operations = 0

    @contextmanager
    def operation(self):
        self.operations += 1
        yield


class _Service:
    def __init__(self, receipt=None, error=None) -> None:
        self.receipt = receipt
        self.error = error
        self.runs = 0
        self.statuses: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def sync_automatic(self):
        self.runs += 1
        self.entered.set()
        self.release.wait(5)
        if self.error is not None:
            raise self.error
        return self.receipt

    def record_status(self, message: str) -> None:
        self.statuses.append(message)


class MetricExportRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = _Gate()
        self.threads: list[threading.Thread] = []

    def _thread(self, **kwargs) -> threading.Thread:
        thread = threading.Thread(**kwargs)
        self.threads.append(thread)
        return thread

    def _runner(self, service, *, enabled=True) -> MetricExportRunner:
        return MetricExportRunner(
            lambda: service,
            enabled=lambda: enabled,
            maintenance_gate=lambda: self.gate,
            delay_seconds=0,
            thread_factory=self._thread,
        )

    def _join(self) -> None:
        for thread in list(self.threads):
            thread.join(5)

    def test_a_request_runs_once_and_records_the_status(self) -> None:
        service = _Service({"exported": 1, "failed": 0, "conflicts": 0})
        self._runner(service).request()
        self._join()
        self.assertEqual((service.runs, self.gate.operations), (1, 1))
        self.assertEqual(
            service.statuses,
            ["Intervals.icu: 1 Werte gesendet, 0 Konflikte, 0 fehlgeschlagen."],
        )

    def test_without_consent_or_configuration_nothing_is_recorded(self) -> None:
        service = _Service(None)
        self._runner(service).request()
        self._join()
        self.assertEqual((service.runs, service.statuses), (1, []))
        self.threads.clear()
        disabled = _Service({"exported": 0, "failed": 0, "conflicts": 0})
        self._runner(disabled, enabled=False).request()
        self._join()
        self.assertEqual(disabled.runs, 0)
        self.assertEqual(self.threads, [])

    def test_a_request_during_a_run_asks_for_one_more_run(self) -> None:
        service = _Service({"exported": 0, "failed": 0, "conflicts": 0})
        service.release.clear()
        runner = self._runner(service)
        runner.request()
        self.assertTrue(service.entered.wait(5))
        runner.request()
        runner.request()
        service.release.set()
        self._join()
        self.assertEqual(service.runs, 2)
        self.assertEqual(len(self.threads), 1)

    def test_a_failed_run_is_logged_safely_and_recorded(self) -> None:
        service = _Service(error=RuntimeError("RAW api_key=secret"))
        with self.assertLogs("intervals_coach", "WARNING") as logs:
            self._runner(service).request()
            self._join()
        self.assertNotIn("secret", "\n".join(logs.output))
        self.assertIn("fehlgeschlagen", service.statuses[0])

    def test_only_a_wahoo_job_requests_a_run(self) -> None:
        runner = self._runner(_Service())
        with patch.object(runner, "request") as request:
            runner.after_job({"provider": "garmin"})
            runner.after_job({"provider": "intervals"})
            request.assert_not_called()
            runner.after_job({"provider": "wahoo"})
            request.assert_called_once_with()

    def test_chained_hooks_each_see_the_job_in_order(self) -> None:
        seen: list[tuple[str, object]] = []
        hook = chained_after_job(
            lambda job: seen.append(("load", job["provider"])),
            lambda job: seen.append(("export", job["provider"])),
        )
        hook({"provider": "wahoo"})
        self.assertEqual(seen, [("load", "wahoo"), ("export", "wahoo")])


if __name__ == "__main__":
    unittest.main()
