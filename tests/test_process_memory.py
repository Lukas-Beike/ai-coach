import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.runtime.memory import process_memory


class ProcessMemoryTests(unittest.TestCase):
    def test_projects_only_numeric_memory_counters(self):
        with tempfile.TemporaryDirectory() as root:
            proc = Path(root)
            (proc / "self").mkdir()
            (proc / "sys/vm").mkdir(parents=True)
            (proc / "self/status").write_text(
                "Name: synthetic-private-process\nVmRSS: 123 kB\n"
                "VmHWM: 456 kB\nVmLck: 78 kB\nVmSize: 789 kB\n"
                "RssAnon: 100 kB\nRssFile: 23 kB\nThreads: 5\n",
                encoding="ascii",
            )
            (proc / "self/maps").write_text(
                "synthetic-private-mapping-path\nsecond-mapping\n", encoding="ascii"
            )
            (proc / "sys/vm/max_map_count").write_text("65530\n", encoding="ascii")
            result = process_memory(proc)
        self.assertEqual(
            result,
            {
                "rss_bytes": 123 * 1024,
                "peak_rss_bytes": 456 * 1024,
                "locked_bytes": 78 * 1024,
                "virtual_bytes": 789 * 1024,
                "anonymous_rss_bytes": 100 * 1024,
                "file_rss_bytes": 23 * 1024,
                "threads": 5,
                "mapping_count": 2,
                "mapping_limit": 65530,
            },
        )
        self.assertNotIn("private", str(result))

    def test_unavailable_proc_files_are_nonfatal(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(process_memory(Path(root)), {})

    def test_malformed_status_keeps_independent_mapping_counters(self):
        with tempfile.TemporaryDirectory() as root:
            proc = Path(root)
            (proc / "self").mkdir()
            (proc / "sys/vm").mkdir(parents=True)
            (proc / "self/status").write_text("VmRSS: invalid kB\n", encoding="ascii")
            (proc / "self/maps").write_text("mapping\n", encoding="ascii")
            (proc / "sys/vm/max_map_count").write_text("invalid", encoding="ascii")
            self.assertEqual(process_memory(proc), {"mapping_count": 1})

    def test_memory_pressure_does_not_break_the_observed_operation(self):
        with patch.object(Path, "open", side_effect=MemoryError):
            self.assertEqual(process_memory(), {})
