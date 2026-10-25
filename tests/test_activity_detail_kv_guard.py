"""Only the backfill and retirement modules may touch the retired kv detail records."""

import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = frozenset(
    {
        "backend/activities/detail_store.py",
        "backend/sync/activity_detail_backfill.py",
        "backend/sync/activity_detail_retirement.py",
        "backend/sync/activity_detail_canonical.py",
        "backend/providers/intervals_activity_detail_mapping.py",
    }
)
# Failure notes use `activity_detail_failure`, so only the colon-terminated prefix
# counts. The lookbehind keeps `provider_records_after` out of the match.
FORBIDDEN = re.compile(
    r"activity_detail:|(?<!\w)records_after\b|\bmap_legacy_activity_detail\b"
    r"|\bwrite_legacy\b"
)


def violations(root: Path) -> list[str]:
    paths = [root / "server.py", *sorted((root / "backend").rglob("*.py"))]
    found = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if relative in ALLOWED or not path.is_file():
            continue
        match = FORBIDDEN.search(path.read_text(encoding="utf-8"))
        if match:
            found.append(f"{relative}: {match.group()}")
    return found


class ActivityDetailKvGuardTests(unittest.TestCase):
    def test_production_code_does_not_touch_kv_detail_records(self):
        self.assertEqual([], violations(ROOT))

    def test_allowlisted_modules_exist(self):
        self.assertEqual([], [item for item in sorted(ALLOWED) if not (ROOT / item).is_file()])

    def test_probe_modules_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend" / "sync").mkdir(parents=True)
            (root / "server.py").write_text("APP_VERSION = '1'\n", encoding="utf-8")
            (root / "backend" / "failure_note.py").write_text(
                "KEY = 'activity_detail_failure:abc'\n"
                "def f(db):\n    provider_records_after(db)\n",
                encoding="utf-8",
            )
            (root / "backend" / "sync" / "activity_detail_retirement.py").write_text(
                "KEY = 'activity_detail:abc'\n", encoding="utf-8"
            )
            self.assertEqual([], violations(root))
            probes = {
                "prefix": "KEY = 'activity_detail:abc'\n",
                "reader": "rows = ActivityDetailStore.records_after(db, '', 1)\n",
                "mapper": "map_legacy_activity_detail(record)\n",
                "writer": "writer.write_legacy(db, record=record, now=now)\n",
            }
            for name, source in probes.items():
                with self.subTest(name):
                    probe = root / "backend" / "probe.py"
                    probe.write_text(source, encoding="utf-8")
                    self.assertEqual(1, len(violations(root)))
                    probe.unlink()
            (root / "server.py").write_text("KEY = 'activity_detail:x'\n", encoding="utf-8")
            self.assertEqual(["server.py: activity_detail:"], violations(root))


if __name__ == "__main__":
    unittest.main()
