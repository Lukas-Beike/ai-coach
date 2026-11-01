"""Ratchet provider coupling outside the adapters and test the scanner itself."""

import json
import tempfile
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path

try:
    from .provider_coupling import (
        BASELINE_PATH,
        OWNER_READ_ALLOWLIST,
        PROVIDER_LITERAL_ALLOWED_FILES,
        SOURCE_ROOT,
        CouplingEntry,
        compare_coupling,
        load_baseline,
        render_baseline,
        scan_owner_reads,
        scan_provider_coupling,
        snapshot_refusals,
        stale_owner_allowlist,
        unallowed_owner_reads,
        write_baseline,
    )
except ImportError:
    from provider_coupling import (
        BASELINE_PATH,
        OWNER_READ_ALLOWLIST,
        PROVIDER_LITERAL_ALLOWED_FILES,
        SOURCE_ROOT,
        CouplingEntry,
        compare_coupling,
        load_baseline,
        render_baseline,
        scan_owner_reads,
        scan_provider_coupling,
        snapshot_refusals,
        stale_owner_allowlist,
        unallowed_owner_reads,
        write_baseline,
    )


def _entry(rule: str, path: str, token: str, count: int) -> CouplingEntry:
    return CouplingEntry(rule=rule, path=path, token=token, count=count)


def _summary(entries: list[CouplingEntry]) -> list[tuple[str, str, str, int]]:
    return [(entry.rule, entry.path, entry.token, entry.count) for entry in entries]


def _scan_files(
    files: Mapping[str, str],
    scan: Callable[[Path], list[CouplingEntry]] = scan_provider_coupling,
) -> list[CouplingEntry]:
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
        return scan(root)


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
        self.assertEqual(
            [empty_message], snapshot_refusals(None, [], sources_scanned=True)
        )

    def test_snapshot_records_removal_of_the_last_entry_after_a_scan(self) -> None:
        baseline = [_entry("provider_literal", "backend/a.py", "garmin", 1)]
        self.assertEqual([], snapshot_refusals(baseline, [], sources_scanned=True))

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


def _owner_reads(files: Mapping[str, str]) -> list[tuple[str, str, str, int]]:
    return _summary(_scan_files(files, scan_owner_reads))


class OwnerReadGuardTests(unittest.TestCase):
    def test_consumers_cannot_import_provider_field_name_modules(self) -> None:
        importer = (
            "from backend.providers.intervals_activity_fields import ACTIVITY_FIELDS\n"
            "from backend.providers import garmin_fields as fields\n"
            "import backend.providers.intervals_performance_fields\n"
            "from backend.providers.source_labels import provider_label\n"
        )
        entries = _owner_reads(
            {
                "backend/performance/consumer.py": importer,
                "backend/sync/ingest.py": importer,
                "backend/providers/mapper.py": importer,
                "backend/canonical/mapping.py": importer,
            }
        )
        self.assertEqual(
            [
                (
                    "field_module_import",
                    "backend/performance/consumer.py",
                    module,
                    1,
                )
                for module in (
                    "garmin_fields",
                    "intervals_activity_fields",
                    "intervals_performance_fields",
                )
            ],
            entries,
        )

    def test_relative_field_module_imports_are_resolved(self) -> None:
        entries = _owner_reads(
            {
                "backend/performance/consumer.py": (
                    "from ..providers import garmin_fields\n"
                    "from ..providers.intervals_activity_fields import ACTIVITY_FIELDS\n"
                    "from . import load\n"
                ),
            }
        )
        self.assertEqual(
            [
                (
                    "field_module_import",
                    "backend/performance/consumer.py",
                    "garmin_fields",
                    1,
                ),
                (
                    "field_module_import",
                    "backend/performance/consumer.py",
                    "intervals_activity_fields",
                    1,
                ),
            ],
            entries,
        )

    def test_an_allowlisted_file_cannot_import_another_field_module(self) -> None:
        path = "backend/performance/consumer.py"
        allowlist = {("field_module_import", path): "owner"}
        allowed = frozenset({(path, "garmin_fields")})
        entries = [
            _entry("field_module_import", path, "garmin_fields", 1),
            _entry("field_module_import", path, "intervals_activity_fields", 1),
        ]
        self.assertEqual(
            [("field_module_import", path, "intervals_activity_fields")],
            [
                (entry.rule, entry.path, entry.token)
                for entry in unallowed_owner_reads(entries, allowlist, allowed)
            ],
        )
        self.assertEqual(
            [("field_module_import", f"{path}: intervals_activity_fields")],
            stale_owner_allowlist(
                entries[:1],
                allowlist,
                frozenset({*allowed, (path, "intervals_activity_fields")}),
            ),
        )

    def test_consumers_cannot_read_raw_snapshots(self) -> None:
        entries = _owner_reads(
            {
                "backend/performance/consumer.py": (
                    'raw = kv.get(db, "garmin_snapshot")\n'
                    'other = {"intervals_snapshot": 1}\n'
                    "snapshot = self._sync_state.latest_snapshot()\n"
                    "again = latest_snapshot(db)\n"
                    "# garmin_snapshot in a comment is ignored\n"
                ),
                "server.py": 'key = "garmin_snapshot"\n',
            }
        )
        self.assertEqual(
            [
                (
                    "snapshot_key",
                    "backend/performance/consumer.py",
                    "garmin_snapshot",
                    1,
                ),
                (
                    "snapshot_key",
                    "backend/performance/consumer.py",
                    "intervals_snapshot",
                    1,
                ),
                (
                    "snapshot_key",
                    "backend/performance/consumer.py",
                    "latest_snapshot",
                    2,
                ),
                ("snapshot_key", "server.py", "garmin_snapshot", 1),
            ],
            entries,
        )

    def test_aliased_and_quoted_snapshot_reader_references_are_flagged(self) -> None:
        entries = _owner_reads(
            {
                "backend/performance/consumer.py": (
                    "from backend.sync.state import latest_snapshot as read_raw\n"
                    'reader = getattr(state, "latest_snapshot")\n'
                    "raw = read_raw(db)\n"
                ),
            }
        )
        self.assertEqual(
            [
                (
                    "snapshot_key",
                    "backend/performance/consumer.py",
                    "latest_snapshot",
                    2,
                )
            ],
            entries,
        )

    def test_snapshot_keys_embedded_in_strings_are_flagged_but_not_docstrings(
        self,
    ) -> None:
        entries = _owner_reads(
            {
                "backend/athlete/consumer.py": (
                    '"""Formerly read garmin_snapshot directly."""\n'
                    "row = db.execute(\n"
                    "    \"SELECT value FROM kv WHERE key='garmin_snapshot'\"\n"
                    ").fetchone()\n"
                    'note = f"intervals_snapshot:{day}"\n'
                    'unrelated = "garmin_snapshots_total"\n'
                ),
            }
        )
        self.assertEqual(
            [
                ("snapshot_key", "backend/athlete/consumer.py", "garmin_snapshot", 1),
                (
                    "snapshot_key",
                    "backend/athlete/consumer.py",
                    "intervals_snapshot",
                    1,
                ),
            ],
            entries,
        )

    def test_consumers_cannot_read_raw_provider_views(self) -> None:
        entries = _owner_reads(
            {
                "backend/coach/consumer.py": (
                    'rows = snapshot.get("recent_wellness")\n'
                    'raw = snapshot["raw_provider_data"]\n'
                    "view = self._garmin_payload.recent_view(7)\n"
                    "inner = payload.recent_view_in(db, 7)\n"
                    "from backend.db.garmin_store import read_view\n"
                    'gear = read_view(db, ("gear",))\n'
                    'KEY = f"activity_detail:{activity_id}"\n'
                    "# recent_wellness in a comment is ignored\n"
                ),
                "backend/planning/consumer.py": (
                    "sql = \"SELECT key FROM kv WHERE key LIKE 'activity_detail:%'\"\n"
                ),
            }
        )
        self.assertEqual(
            [
                ("legacy_read", "backend/coach/consumer.py", "activity_detail:", 1),
                ("legacy_read", "backend/coach/consumer.py", "raw_provider_data", 1),
                ("legacy_read", "backend/coach/consumer.py", "read_view", 2),
                ("legacy_read", "backend/coach/consumer.py", "recent_view", 1),
                ("legacy_read", "backend/coach/consumer.py", "recent_view_in", 1),
                ("legacy_read", "backend/coach/consumer.py", "recent_wellness", 1),
                ("legacy_read", "backend/planning/consumer.py", "activity_detail:", 1),
            ],
            entries,
        )

    def test_raw_view_docstrings_owners_and_lookalikes_are_not_flagged(self) -> None:
        read = "view = garmin_store.read_view(db, None)\n"
        entries = _owner_reads(
            {
                "backend/performance/consumer.py": (
                    '"""Formerly read recent_wellness and raw_provider_data."""\n'
                    "def f():\n"
                    '    """Was recent_view; see activity_detail: records."""\n'
                    'failure = "activity_detail_failure"\n'
                    'unrelated = "recent_wellness_days"\n'
                    "spread = reader.read_views(db)\n"
                ),
                # Ingestion and persistence owners are out of the rule's scope.
                "backend/sync/garmin.py": read,
                "backend/db/garmin_store.py": read,
                "backend/backup/export.py": read,
            }
        )
        self.assertEqual([], entries)

    def test_allowlisted_raw_view_owner_passes_and_a_stale_entry_fails(self) -> None:
        entries = _scan_files(
            {
                "backend/nutrition/status.py": "state = garmin_store.read_view(db, ())\n",
                "backend/athlete/consumer.py": "rows = snapshot['recent_wellness']\n",
            },
            scan_owner_reads,
        )
        allowlist = {
            ("legacy_read", "backend/nutrition/status.py"): "sync-status",
            ("legacy_read", "backend/nutrition/gone.py"): "sync-status",
        }
        self.assertEqual(
            [("legacy_read", "backend/athlete/consumer.py", "recent_wellness")],
            [
                (entry.rule, entry.path, entry.token)
                for entry in unallowed_owner_reads(entries, allowlist)
            ],
        )
        self.assertEqual(
            [("legacy_read", "backend/nutrition/gone.py")],
            stale_owner_allowlist(entries, allowlist),
        )

    def test_athlete_views_are_in_the_source_label_scope(self) -> None:
        entries = _owner_reads(
            {"backend/athlete/consumer.py": 'item = {"source": "Garmin Connect"}\n'}
        )
        self.assertEqual(
            [("source_label", "backend/athlete/consumer.py", "Garmin Connect", 1)],
            entries,
        )

    def test_provider_display_names_are_flagged_only_as_exact_labels(self) -> None:
        entries = _owner_reads(
            {
                "backend/coach/consumer.py": (
                    'source = "Garmin Connect"\n'
                    'prose = "Garmin Connect Radaktivitäten"\n'
                    'also = "Intervals.icu"\n'
                ),
                "public/analysis.js": 'const s = "Garmin Connect";\n',
            }
        )
        self.assertEqual(
            [
                ("source_label", "backend/coach/consumer.py", "Garmin Connect", 1),
                ("source_label", "backend/coach/consumer.py", "Intervals.icu", 1),
                ("source_label", "public/analysis.js", "Garmin Connect", 1),
            ],
            entries,
        )

    def test_label_owners_and_connection_copy_are_out_of_scope(self) -> None:
        label = 'source = "Garmin Connect"\n'
        entries = _owner_reads(
            {
                "backend/providers/source_labels.py": label,
                "backend/sync/commands.py": label,
                "backend/sync/garmin.py": label,
                "public/sync-status.js": "const s = 'Garmin Connect';\n",
                "public/nutrition.js": "const s = 'Garmin Connect';\n",
            }
        )
        self.assertEqual([], entries)

    def test_allowlisted_owners_pass_and_other_files_fail(self) -> None:
        entries = _scan_files(
            {
                "backend/sync/garmin_snapshot_writer.py": 'KEY = "garmin_snapshot"\n',
                "backend/performance/consumer.py": 'KEY = "garmin_snapshot"\n',
                "public/performance-view.js": "const s = 'Intervals.icu';\n",
                "public/analysis.js": "const s = 'x';\n",
            },
            scan_owner_reads,
        )
        allowlist = {
            ("snapshot_key", "backend/sync/garmin_snapshot_writer.py"): "writer"
        }
        self.assertEqual(
            [
                ("snapshot_key", "backend/performance/consumer.py"),
                ("source_label", "public/performance-view.js"),
            ],
            [
                (entry.rule, entry.path)
                for entry in unallowed_owner_reads(entries, allowlist)
            ],
        )

    def test_stale_allowlist_entries_are_reported(self) -> None:
        entries = [
            _entry("snapshot_key", "backend/sync/garmin.py", "latest_snapshot", 1)
        ]
        allowlist = {
            ("snapshot_key", "backend/sync/garmin.py"): "writer",
            ("snapshot_key", "backend/sync/gone.py"): "writer",
        }
        self.assertEqual(
            [("snapshot_key", "backend/sync/gone.py")],
            stale_owner_allowlist(entries, allowlist),
        )

    def test_source_tree_reads_only_through_allowlisted_owners(self) -> None:
        self.assertEqual(
            [],
            [
                (entry.rule, entry.path, entry.token)
                for entry in unallowed_owner_reads(scan_owner_reads())
            ],
            "A consumer reads a raw provider snapshot or hardcodes a provider "
            "label. Read canonical observations and take labels from "
            "backend/providers/source_labels.py.",
        )

    def test_owner_allowlist_has_no_stale_entries(self) -> None:
        self.assertEqual([], stale_owner_allowlist(scan_owner_reads()))

    def test_owner_allowlist_is_explained_and_the_baseline_stays_empty(self) -> None:
        for (_rule, relative_path), reason in OWNER_READ_ALLOWLIST.items():
            self.assertTrue((SOURCE_ROOT / relative_path).is_file(), relative_path)
            self.assertTrue(reason.strip(), relative_path)
        self.assertEqual([], load_baseline())


if __name__ == "__main__":
    unittest.main()
