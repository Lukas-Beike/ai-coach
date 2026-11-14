"""Readiness probe: bounded checks, no leaked details, the probe file always goes."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import temp_database

from backend.http_api import readiness as readiness_module
from backend.http_api.readiness import ReadinessService
from backend.runtime.maintenance import MaintenanceGate


class ReadinessServiceTests(unittest.TestCase):
    def setUp(self):
        manager = temp_database(self, "readiness.db", schema=True)
        self.data_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.service = ReadinessService(
            lambda: manager, self.data_dir, MaintenanceGate()
        )

    def probes(self):
        return list(self.data_dir.glob(".readiness-*.probe"))

    def test_a_ready_state_is_safe_and_leaves_no_probe_behind(self):
        readiness = self.service.state()

        self.assertEqual([], self.probes())
        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["ready"])
        self.assertEqual(
            set(readiness["checks"]),
            {"database", "schema", "data_directory", "maintenance"},
        )
        for word in ("path", "athlete", "password"):
            self.assertNotIn(word, json.dumps(readiness).casefold())

    def test_a_read_only_data_directory_is_not_ready(self):
        with patch.object(
            readiness_module.tempfile,
            "NamedTemporaryFile",
            side_effect=OSError("read-only"),
        ):
            readiness = self.service.state()

        self.assertEqual(readiness["status"], "not_ready")
        self.assertFalse(readiness["ready"])
        self.assertFalse(readiness["checks"]["data_directory"])

    def test_the_probe_is_removed_after_a_write_failure(self):
        named_temporary_file = readiness_module.tempfile.NamedTemporaryFile

        def broken_probe(**kwargs):
            handle = named_temporary_file(**kwargs)

            class BrokenWriter:
                name = handle.name

                def __enter__(self):
                    handle.__enter__()
                    return self

                def __exit__(self, *args):
                    return handle.__exit__(*args)

                def write(self, _content):
                    raise OSError("probe write failed")

            return BrokenWriter()

        with patch.object(
            readiness_module.tempfile, "NamedTemporaryFile", side_effect=broken_probe
        ):
            readiness = self.service.state()

        self.assertFalse(readiness["checks"]["data_directory"])
        self.assertEqual([], self.probes())


if __name__ == "__main__":
    unittest.main()
