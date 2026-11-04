"""Changed-test selection: affected modules in, unrelated modules out."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import changed_tests

FILES = {
    "server.py": "import backend.app.wiring\n",
    "backend/__init__.py": "",
    "backend/app/__init__.py": "",
    "backend/app/wiring.py": "from . import engine\n",
    "backend/app/engine.py": "VALUE = 1\n",
    "backend/other.py": "VALUE = 2\n",
    "public/app.js": "",
    "tests/fake_support.py": "from backend.app.engine import VALUE\n",
    "tests/test_engine.py": "from backend.app.engine import VALUE\n",
    "tests/test_via_support.py": "import fake_support\n",
    "tests/test_other.py": "from backend import other\n",
    "tests/test_app_wide.py": "import server\n",
    "tests/test_patch.py": "PATCH = 'backend.other.VALUE'\n",
    "tests/test_frontend_text.py": "ASSET = 'public/app.js'\n",
    "tests/test_scan.py": "from pathlib import Path\n"
    "FILES = Path('backend').rglob('*.py')\n",
    "tests/test_named_dir.py": "NAME = 'backend'\n",
}


def _write_tree(root: Path) -> None:
    for relative, text in FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class SelectModulesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        _write_tree(self.root)

    def select(self, *paths):
        modules, _reason = changed_tests.select_modules(list(paths), self.root)
        return modules

    def test_transitive_imports_and_support_modules_select_importers(self):
        self.assertEqual(
            set(self.select("backend/app/engine.py")),
            {"test_engine", "test_via_support", "test_scan"},
        )

    def test_app_wide_tests_need_a_composition_root_change(self):
        self.assertNotIn("test_app_wide", self.select("backend/app/wiring.py"))
        self.assertIn("test_app_wide", self.select("server.py"))

    def test_literals_select_patch_targets_and_named_paths(self):
        self.assertEqual(
            set(self.select("backend/other.py")),
            {"test_other", "test_patch", "test_scan"},
        )
        self.assertEqual(set(self.select("public/app.js")), {"test_frontend_text"})

    def test_bare_directory_name_counts_only_in_a_scanning_module(self):
        selected = self.select("backend/app/engine.py")
        self.assertIn("test_scan", selected)
        self.assertNotIn("test_named_dir", selected)

    def test_changed_test_selects_itself_and_unrelated_paths_select_nothing(self):
        self.assertEqual(set(self.select("tests/test_other.py")), {"test_other"})
        self.assertEqual(self.select("docs/notes.md"), {})

    def test_full_suite_paths_and_unparsable_sources_select_everything(self):
        modules, reason = changed_tests.select_modules(
            ["backend/db/schema.py"], self.root
        )
        self.assertIsNone(modules)
        self.assertIn("backend/db/", reason)
        (self.root / "tests/test_broken.py").write_text("def (:\n", encoding="utf-8")
        self.assertIsNone(self.select("backend/other.py"))

    def test_full_suite_paths_name_existing_repository_paths(self):
        root = changed_tests.ROOT
        for prefix in changed_tests.FULL_SUITE_PATHS:
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    (root / prefix).exists() or list(root.glob(prefix + "*")), prefix
                )

    def test_repository_selection_is_narrower_than_the_suite(self):
        modules, _reason = changed_tests.select_modules(
            ["backend/nutrition/macro_ranges.py"]
        )
        self.assertIn("test_nutrition_macro_ranges", modules)
        self.assertNotIn("test_fixture_standard_data", modules)


class ChangedPathsTests(unittest.TestCase):
    def test_reports_committed_uncommitted_and_untracked_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git(root, "init", "-q", "-b", "base")
            _git(root, "config", "user.email", "test@example.invalid")
            _git(root, "config", "user.name", "Test")
            (root / "kept.py").write_text("", encoding="utf-8")
            (root / "edited.py").write_text("", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-q", "-m", "base")
            _git(root, "switch", "-q", "-c", "work")
            (root / "committed.py").write_text("", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-q", "-m", "work")
            (root / "edited.py").write_text("x = 1\n", encoding="utf-8")
            (root / "new.py").write_text("", encoding="utf-8")
            self.assertEqual(
                changed_tests.changed_paths("base", root),
                ["committed.py", "edited.py", "new.py"],
            )


if __name__ == "__main__":
    unittest.main()
