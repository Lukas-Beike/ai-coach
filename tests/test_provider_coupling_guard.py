"""Ratchet provider coupling outside the adapters and test the scanner itself."""

import json
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

try:
    from .provider_coupling import (
        BASELINE_PATH,
        PROVIDER_LITERAL_ALLOWED_FILES,
        SOURCE_ROOT,
        CouplingEntry,
        compare_coupling,
        load_baseline,
        render_baseline,
        scan_provider_coupling,
        snapshot_refusals,
        write_baseline,
    )
except ImportError:
    from provider_coupling import (
        BASELINE_PATH,
        PROVIDER_LITERAL_ALLOWED_FILES,
        SOURCE_ROOT,
        CouplingEntry,
        compare_coupling,
        load_baseline,
        render_baseline,
        scan_provider_coupling,
        snapshot_refusals,
        write_baseline,
    )


def _entry(rule: str, path: str, token: str, count: int) -> CouplingEntry:
    return CouplingEntry(rule=rule, path=path, token=token, count=count)


def _summary(entries: list[CouplingEntry]) -> list[tuple[str, str, str, int]]:
    return [(entry.rule, entry.path, entry.token, entry.count) for entry in entries]


def _scan_files(files: Mapping[str, str]) -> list[CouplingEntry]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        # A scan root must contain the full source layout; empty files keep it so.
        (root / "backend").mkdir()
        (root / "public").mkdir()
        (root / "server.py").write_text("", encoding="utf-8")
        for relative_path, text in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return scan_provider_coupling(root)


class ProviderCouplingRatchetTests(unittest.TestCase):
    def test_source_root_resolves_native_and_container_layouts(self) -> None:
        # Container CI mounts tests at /review/tests while the image keeps the
        # sources under /app; the scanner must find the same layout in both.
        self.assertTrue((SOURCE_ROOT / "backend").is_dir())
        self.assertTrue((SOURCE_ROOT / "server.py").is_file())
        self.assertTrue((SOURCE_ROOT / "public").is_dir())

    def test_allowlisted_provider_literal_files_exist(self) -> None:
        # An allowlist entry for a missing file would silently exempt a future file.
        for relative_path in sorted(PROVIDER_LITERAL_ALLOWED_FILES):
            self.assertTrue((SOURCE_ROOT / relative_path).is_file(), relative_path)

    def test_provider_coupling_does_not_grow(self) -> None:
        comparison = compare_coupling(load_baseline(), scan_provider_coupling())
        self.assertEqual(
            [],
            [change.describe() for change in comparison.grown],
            "Provider coupling grew outside the adapters. Move the code behind a "
            "provider adapter or canonical model.",
        )

    def test_provider_coupling_baseline_shrinks_with_removed_coupling(self) -> None:
        comparison = compare_coupling(load_baseline(), scan_provider_coupling())
        self.assertEqual(
            [],
            [change.describe() for change in comparison.shrunk],
            "The provider coupling baseline must shrink. Regenerate it with "
            "`python tests/provider_coupling.py --snapshot`.",
        )

    def test_baseline_is_canonically_sorted_and_round_trips(self) -> None:
        entries = load_baseline()
        self.assertEqual(entries, sorted(entries))
        committed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed, json.loads(render_baseline(entries)))


class ProviderCouplingScannerTests(unittest.TestCase):
    def test_icu_identifier_rule_detects_identifiers_outside_adapters(self) -> None:
        entries = _scan_files(
            {
                "backend/planning/sample.py": (
                    'icu_eftp = 1\nvalue = {"icu_training_load": icu_eftp}\n'
                )
            }
        )
        self.assertEqual(
            [
                ("icu_identifier", "backend/planning/sample.py", "icu_eftp", 2),
                (
                    "icu_identifier",
                    "backend/planning/sample.py",
                    "icu_training_load",
                    1,
                ),
            ],
            _summary(entries),
        )

    def test_garmin_wire_keys_are_detected_only_as_quoted_strings(self) -> None:
        entries = _scan_files(
            {
                "backend/performance/sample.py": (
                    'row.get("calendarDate")\n'
                    "# calendarDate is documented here without quotes\n"
                    "name = 'weeklyAvg'\n"
                    'other = "intervalsOnly"\n'
                )
            }
        )
        self.assertEqual(
            [
                ("garmin_wire_key", "backend/performance/sample.py", "calendarDate", 1),
                ("garmin_wire_key", "backend/performance/sample.py", "weeklyAvg", 1),
            ],
            _summary(entries),
        )

    def test_provider_literals_match_exact_values_case_insensitively(self) -> None:
        entries = _scan_files(
            {
                "backend/sync/sample.py": (
                    'source = "Intervals"\n'
                    "other = 'garmin'\n"
                    'same = "GARMIN"\n'
                    'not_exact = "garmin-sync"\n'
                )
            }
        )
        self.assertEqual(
            [
                ("provider_literal", "backend/sync/sample.py", "garmin", 2),
                ("provider_literal", "backend/sync/sample.py", "intervals", 1),
            ],
            _summary(entries),
        )

    def test_adapters_and_canonical_model_are_allowlisted_for_every_rule(self) -> None:
        provider_source = (
            'icu_eftp = 1\nkey = "calendarDate"\nsource = "garmin"\n'
            'other = "intervals"\n'
        )
        entries = _scan_files(
            {
                "backend/providers/sample.py": provider_source,
                "backend/canonical/sample.py": provider_source,
            }
        )
        self.assertEqual([], entries)

    def test_provider_literal_allowlist_is_rule_specific(self) -> None:
        mixed_source = 'icu_eftp = 1\nkey = "calendarDate"\nsource = "garmin"\n'
        entries = _scan_files(
            {
                "backend/db/migrations.py": mixed_source,
                "backend/sync/provider_registry.py": 'source = "intervals"\n',
            }
        )
        self.assertEqual(
            [
                ("garmin_wire_key", "backend/db/migrations.py", "calendarDate", 1),
                ("icu_identifier", "backend/db/migrations.py", "icu_eftp", 1),
                (
                    "provider_literal",
                    "backend/sync/provider_registry.py",
                    "intervals",
                    1,
                ),
            ],
            _summary(entries),
        )

    def test_only_backend_server_and_top_level_javascript_are_scanned(self) -> None:
        entries = _scan_files(
            {
                "tests/sample.py": 'source = "garmin"\n',
                "docs/sample.py": "icu_eftp = 1\n",
                "public/nested/sample.js": "const label = 'garmin';\n",
                "public/app.js": "const label = 'garmin';\n",
                "server.py": 'source = "intervals"\n',
            }
        )
        self.assertEqual(
            [
                ("provider_literal", "public/app.js", "garmin", 1),
                ("provider_literal", "server.py", "intervals", 1),
            ],
            _summary(entries),
        )

    def test_javascript_string_forms_and_identifiers_are_counted(self) -> None:
        entries = _scan_files(
            {
                "public/app.js": (
                    'const a = "garmin";\nconst b = `intervals`;\n'
                    "const c = 'icu_ftp';\n"
                )
            }
        )
        self.assertEqual(
            [
                ("icu_identifier", "public/app.js", "icu_ftp", 1),
                ("provider_literal", "public/app.js", "garmin", 1),
                ("provider_literal", "public/app.js", "intervals", 1),
            ],
            _summary(entries),
        )

    def test_python_f_strings_and_implicit_concatenation_are_scanned(self) -> None:
        entries = _scan_files(
            {
                "backend/sync/evasion.py": (
                    'source = f"garmin"\n'
                    'other = "gar" "min"\n'
                    "# 'intervals' is only mentioned in a comment\n"
                )
            }
        )
        self.assertEqual(
            [("provider_literal", "backend/sync/evasion.py", "garmin", 2)],
            _summary(entries),
        )

    def test_javascript_comments_do_not_hide_later_literals(self) -> None:
        entries = _scan_files(
            {
                "public/app.js": (
                    "// use ` for code and 'garmin' is mentioned here\n"
                    'const label = "garmin";\n'
                    "const tmpl = `tmpl`;\n"
                    "/* garmin in a block comment */\n"
                )
            }
        )
        self.assertEqual(
            [("provider_literal", "public/app.js", "garmin", 1)],
            _summary(entries),
        )

    def test_javascript_template_interpolations_are_scanned(self) -> None:
        entries = _scan_files(
            {"public/app.js": "const t = `${flag ? \"garmin\" : ''}`;\n"}
        )
        self.assertEqual(
            [("provider_literal", "public/app.js", "garmin", 1)],
            _summary(entries),
        )

    def test_missing_source_layout_is_rejected_instead_of_scanning_nothing(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(FileNotFoundError),
        ):
            scan_provider_coupling(Path(directory))

    def test_snapshot_refuses_growth_and_empty_scans(self) -> None:
        baseline = [_entry("provider_literal", "backend/a.py", "garmin", 1)]
        grown = [_entry("provider_literal", "backend/a.py", "garmin", 2)]
        growth_message = (
            "refusing to record growth: provider_literal backend/a.py "
            "'garmin': baseline 1, current 2"
        )
        self.assertEqual([growth_message], snapshot_refusals(baseline, grown))
        unchanged = [_entry("provider_literal", "backend/a.py", "garmin", 1)]
        self.assertEqual([], snapshot_refusals(baseline, unchanged))
        empty_message = (
            "the scan found no provider sources; refusing to record an empty baseline"
        )
        self.assertEqual([empty_message], snapshot_refusals(baseline, []))

    def test_snapshot_allows_bootstrap_without_a_committed_baseline(self) -> None:
        current = [_entry("provider_literal", "backend/a.py", "garmin", 1)]
        self.assertEqual([], snapshot_refusals(None, current))

    def test_counts_aggregate_per_file_and_token(self) -> None:
        entries = _scan_files(
            {
                "backend/planning/aggregate.py": (
                    'a = "garmin"\nb = "garmin"\nc = "garmin"\nd = "intervals"\n'
                ),
                "public/app.js": "const label = 'garmin';\n",
            }
        )
        self.assertEqual(
            [
                ("provider_literal", "backend/planning/aggregate.py", "garmin", 3),
                ("provider_literal", "backend/planning/aggregate.py", "intervals", 1),
                ("provider_literal", "public/app.js", "garmin", 1),
            ],
            _summary(entries),
        )

    def test_comparison_reports_new_increased_decreased_and_obsolete(self) -> None:
        baseline = [
            _entry("icu_identifier", "backend/a.py", "icu_a", 2),
            _entry("icu_identifier", "backend/b.py", "icu_b", 1),
            _entry("garmin_wire_key", "backend/c.py", "calendarDate", 3),
            _entry("provider_literal", "backend/d.py", "garmin", 1),
        ]
        current = [
            _entry("icu_identifier", "backend/a.py", "icu_a", 2),
            _entry("icu_identifier", "backend/b.py", "icu_b", 4),
            _entry("garmin_wire_key", "backend/c.py", "calendarDate", 1),
            _entry("provider_literal", "backend/e.py", "intervals", 1),
        ]
        comparison = compare_coupling(baseline, current)
        self.assertEqual(
            [("provider_literal", "backend/e.py", "intervals", 0, 1)],
            [(c.rule, c.path, c.token, c.baseline, c.current) for c in comparison.new],
        )
        self.assertEqual(
            [("icu_identifier", "backend/b.py", "icu_b", 1, 4)],
            [
                (c.rule, c.path, c.token, c.baseline, c.current)
                for c in comparison.increased
            ],
        )
        self.assertEqual(
            [("garmin_wire_key", "backend/c.py", "calendarDate", 3, 1)],
            [
                (c.rule, c.path, c.token, c.baseline, c.current)
                for c in comparison.decreased
            ],
        )
        self.assertEqual(
            [("provider_literal", "backend/d.py", "garmin", 1, 0)],
            [
                (c.rule, c.path, c.token, c.baseline, c.current)
                for c in comparison.obsolete
            ],
        )

    def test_unchanged_coupling_produces_no_comparison_changes(self) -> None:
        entries = [_entry("icu_identifier", "backend/a.py", "icu_a", 2)]
        comparison = compare_coupling(entries, entries)
        self.assertEqual((), comparison.grown)
        self.assertEqual((), comparison.shrunk)

    def test_snapshot_writes_sorted_lf_json_that_loads_back(self) -> None:
        entries = [
            _entry("provider_literal", "public/app.js", "garmin", 1),
            _entry("icu_identifier", "backend/a.py", "icu_a", 2),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            write_baseline(entries, path)
            raw = path.read_bytes()
            self.assertNotIn(b"\r", raw)
            self.assertEqual(
                [
                    _entry("icu_identifier", "backend/a.py", "icu_a", 2),
                    _entry("provider_literal", "public/app.js", "garmin", 1),
                ],
                load_baseline(path),
            )

    def test_loading_rejects_duplicate_entries(self) -> None:
        duplicate = {"rule": "icu_identifier", "path": "backend/a.py"}
        document = {
            "description": "test",
            "regeneration": "test",
            "entries": [
                {**duplicate, "token": "icu_a", "count": 1},
                {**duplicate, "token": "icu_a", "count": 2},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_baseline(path)


if __name__ == "__main__":
    unittest.main()
