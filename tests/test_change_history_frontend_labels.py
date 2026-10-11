"""The history remains a backend capability without a browser history panel."""

import unittest
from pathlib import Path


class ChangeHistoryFrontendTests(unittest.TestCase):
    def test_browser_does_not_expose_or_load_the_removed_history_panel(self):
        public = Path(__file__).resolve().parents[1] / "public"
        for name in ("index.html", "app.js", "shared.js", "diagnostics.js"):
            source = (public / name).read_text(encoding="utf-8")
            self.assertNotIn("changeHistory", source, name)
            self.assertNotIn("/api/change-history", source, name)
        self.assertIn("downloadDiagnostics", (public / "diagnostics.js").read_text(encoding="utf-8"))
