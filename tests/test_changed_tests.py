"""Changed-test selection: affected modules in, unrelated modules out."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import changed_tests

FILES = {
    "server.py": "import backend.app.wiring\nimport backend.http_api.routes\n",
    "README.md": "",
    "backend/__init__.py": "",
    "backend/app/__init__.py": "",
    "backend/app/wiring.py": "from . import engine\n",
    "backend/app/engine.py": "DATA = 'data.json'\n",
    "backend/app/data.json": "{}",
    "backend/http_api/__init__.py": "",
    "backend/http_api/routes.py": "",
    "backend/other.py": "VALUE = 2\n",
    "public/app.js": "",
    "tools/__init__.py": "",
    "tools/helper.py": "",
    "tests/fake_support.py": "from backend.app.engine import DATA\n",
    "tests/test_engine.py": "from backend.app.engine import DATA\n",
    "tests/test_via_support.py": "import fake_support\n",
    "tests/test_other.py": "from backend import other\n",
    "tests/test_app_wide.py": "import server\n",
    "tests/test_patch.py": "PATCH = 'backend.other.VALUE'\n",
    "tests/test_frontend_text.py": "ASSET = 'public/app.js'\n",
    "tests/test_scan.py": "from pathlib import Path\n"
    "FILES = Path('backend').rglob('*.py')\n",
    "tests/test_named_dir.py": "NAME = 'backend'\n",
    "tests/test_docs.py": "DOC = 'README.md'\n",
    "tests/test_tool.py": "from tools import helper\n",
    "tests/test_lazy.py": "def load():\n    from backend.app import old\n",
    "tests/fixtures/providers/demo/day.json": "{}",
    "tests/fixtures/other.json": "{}",
    "tests/fixture_loader.py": "from pathlib import Path\n"
    "ROOT = Path(__file__).parent / 'fixtures' / 'providers'\n",
    "tests/test_fixture_reader.py": "import fixture_loader\n",
    "tests/test_baseline.py": "BASELINE = 'tests/fixtures/other.json'\n",
    "tests/test_prose.py": "NOTE = 'Shared fixtures for this test.'\n",
    "tests/test_line_endings.py": "",
    "tests/test_ai_docs_contract.py": "",
}
# Repository-wide checks every changed path selects (#2502).
REPOSITORY_WIDE = {"test_line_endings", "test_ai_docs_contract"}


def _write_tree(root: Path) -> None:
    for relative, text in FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _isolate_git_config(case: unittest.TestCase) -> None:
    """Keep global signing, hooks, and templates out of temporary repositories."""
    patcher = mock.patch.dict(
        os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    )
    patcher.start()
    case.addCleanup(patcher.stop)


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
            {"test_engine", "test_via_support", "test_scan"} | REPOSITORY_WIDE,
        )

    def test_app_wide_tests_need_a_composition_root_change(self):
        self.assertNotIn("test_app_wide", self.select("backend/app/wiring.py"))
        self.assertIn("test_app_wide", self.select("server.py"))
        self.assertIn("test_app_wide", self.select("backend/http_api/routes.py"))

    def test_package_init_runs_for_every_submodule_import(self):
        self.assertIn("test_engine", self.select("backend/app/__init__.py"))

    def test_data_file_selects_tests_of_the_module_that_names_it(self):
        self.assertIn("test_engine", self.select("backend/app/data.json"))

    def test_deleted_module_selects_its_lazy_importers(self):
        self.assertEqual(
            set(self.select("backend/app/old.py")),
            {"test_lazy", "test_scan"} | REPOSITORY_WIDE,
        )

    def test_root_documents_and_tool_modules_select_their_tests(self):
        self.assertEqual(set(self.select("README.md")), {"test_docs"} | REPOSITORY_WIDE)
        self.assertEqual(
            set(self.select("tools/helper.py")), {"test_tool"} | REPOSITORY_WIDE
        )

    def test_literals_select_patch_targets_and_named_paths(self):
        self.assertEqual(
            set(self.select("backend/other.py")),
            {"test_other", "test_patch", "test_scan"} | REPOSITORY_WIDE,
        )
        self.assertEqual(
            set(self.select("public/app.js")), {"test_frontend_text"} | REPOSITORY_WIDE
        )

    def test_bare_directory_name_counts_only_in_a_scanning_module(self):
        selected = self.select("backend/app/engine.py")
        self.assertIn("test_scan", selected)
        self.assertNotIn("test_named_dir", selected)

    def test_changed_test_selects_itself_and_unrelated_paths_only_repo_checks(self):
        self.assertEqual(
            set(self.select("tests/test_other.py")), {"test_other"} | REPOSITORY_WIDE
        )
        # A CRLF line or a renamed link target can fail them from any path.
        self.assertEqual(set(self.select("docs/notes.md")), REPOSITORY_WIDE)
        self.assertEqual(self.select(), {})

    def test_heavy_tooling_modules_run_only_when_their_inputs_change(self):
        skips = changed_tests.heavy_skips(["backend/sync/garmin.py"])
        self.assertEqual(set(skips), set(changed_tests.HEAVY_MODULES))
        self.assertIn("CI runs it", skips["test_ci_contracts"])
        self.assertNotIn(
            "test_ci_contracts",
            changed_tests.heavy_skips([".github/workflows/publish-container.yml"]),
        )
        self.assertNotIn(
            "test_fixture_standard_data",
            changed_tests.heavy_skips(["e2e/fixture_runtime.py"]),
        )

    def test_fixture_selects_modules_naming_the_fixtures_directory(self):
        # Loaders build fixture paths from parts, so the directory segment counts
        # wherever it appears; prose does not, and the repository-wide check runs.
        for fixture in (
            "tests/fixtures/providers/demo/day.json",
            "tests/fixtures/other.json",
        ):
            with self.subTest(fixture=fixture):
                self.assertEqual(
                    set(self.select(fixture)),
                    {"test_fixture_reader", "test_baseline"} | REPOSITORY_WIDE,
                )

    def test_full_suite_paths_and_unparsable_sources_select_everything(self):
        modules, reason = changed_tests.select_modules(
            ["backend/db/migrations.py"], self.root
        )
        self.assertIsNone(modules)
        self.assertIn("backend/db/migrations.py", reason)
        (self.root / "tests/test_broken.py").write_text("def (:\n", encoding="utf-8")
        self.assertIsNone(self.select("backend/other.py"))

    def test_full_suite_paths_name_existing_repository_paths(self):
        root = changed_tests.ROOT
        for prefix in changed_tests.FULL_SUITE_PATHS:
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    (root / prefix).exists() or list(root.glob(prefix + "*")), prefix
                )

    def test_a_selection_covering_most_modules_falls_back_with_a_reason(self):
        with mock.patch.object(changed_tests, "FULL_SUITE_SHARE", 0.01):
            modules, reason = changed_tests.select_modules(
                ["backend/other.py"], self.root
            )
        self.assertIsNone(modules)
        self.assertRegex(reason, r"^\d+ of \d+ test modules affected; full suite$")

    def test_canonical_and_store_changes_select_focused_modules(self):
        for path in (
            "backend/db/activity_detail_store.py",
            "backend/canonical/activity_detail.py",
        ):
            with self.subTest(path=path):
                modules, _reason = changed_tests.select_modules([path])
                self.assertIsNotNone(modules)
                self.assertIn("test_activity_detail_store", modules)

    def test_repository_selection_is_narrower_than_the_suite(self):
        modules, _reason = changed_tests.select_modules(
            ["backend/nutrition/macro_ranges.py"]
        )
        self.assertIn("test_nutrition_macro_ranges", modules)
        self.assertNotIn("test_fixture_standard_data", modules)


class ChangedPathsTests(unittest.TestCase):
    def setUp(self):
        _isolate_git_config(self)

    def test_runner_reports_an_unknown_base_instead_of_a_traceback(self):
        runner = Path(changed_tests.__file__).with_name("run_tests.py")
        result = subprocess.run(
            [sys.executable, str(runner), "--changed", "--base", "refs/missing"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--changed cannot diff against refs/missing", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_runner_treats_a_suite_without_affected_tests_as_empty(self):
        import run_tests

        selection = ({"test_changed_tests": "changed"}, "1 module")
        with (
            mock.patch.object(
                sys, "argv", ["run_tests.py", "--changed", "--suite", "container"]
            ),
            mock.patch.object(changed_tests, "changed_paths", return_value=["x.py"]),
            mock.patch.object(changed_tests, "select_modules", return_value=selection),
            mock.patch("sys.stdout"),
        ):
            self.assertEqual(run_tests.main(), 0)

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
