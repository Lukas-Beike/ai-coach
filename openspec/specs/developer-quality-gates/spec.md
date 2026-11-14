# developer-quality-gates Specification

## Purpose

Keep what reaches the shared repository safe and architecturally sound: nothing secret leaves the clone, the Ruff and mypy debt cannot grow, the coverage floor cannot fall, the Python test suite is partitioned completely and selected honestly, the backend keeps its import directions and composition root, and documented versions follow the code.

This capability covers only the gates that protect the repository and its releases. Graphify, worktree preparation and pruning, agent guard hooks, browser and SQLCipher runners (see `isolated-test-execution`) and CI workflow policy (see `build-release-and-deployment`) are outside it. Each requirement states the protection; the tests cited as evidence are today's way of enforcing it and may be reshaped without changing the requirement. Inspected at `develop` 3cb05c53f.

## Requirements

### Requirement: Pre-push hook blocks secrets before quality findings
The repository pre-push hook SHALL run the outgoing secret scan first and stop with its exit status on failure. Only after a clean scan SHALL it run the quality ratchet on a clean export of `HEAD`, so uncommitted edits neither hide nor add findings, and a ratchet failure SHALL block the push.

#### Scenario: Clean push
- **WHEN** a push passes the secret scan and the ratchet
- **THEN** the hook runs the scan, then the ratchet, and exits 0

#### Scenario: Secret scan fails
- **WHEN** the secret scan exits non-zero
- **THEN** the hook exits with that status and the ratchet does not run

#### Scenario: Ratchet fails or the tree is dirty
- **WHEN** the ratchet reports new or obsolete findings in `HEAD`
- **THEN** the push is blocked with a message; uncommitted working-tree changes do not change the result

Evidence: `.githooks/pre-push`. Tests: `tests/test_pre_push_hook.py::PrePushHookTests.test_clean_push_runs_both_checks_in_order`, `tests/test_pre_push_hook.py::PrePushHookTests.test_secret_scan_failure_stops_before_quality`, `tests/test_pre_push_hook.py::PrePushHookTests.test_quality_regression_blocks_the_push`, `tests/test_pre_push_hook.py::PrePushHookTests.test_quality_runs_on_committed_head_not_the_working_tree`.

### Requirement: Outgoing secret scan fails closed
`scripts/check_push_secrets.py` SHALL scan only content the push would add: commit and tag messages, whole new or binary files, and the lines added by edited files, including intermediate commits and merge resolutions. Lines already on the remote base SHALL NOT be rescanned and scanner output SHALL NOT be printed. A finding, scanner error, timeout, missing `sonar` command or malformed object id SHALL refuse the push. The refusal SHALL name its cause.

#### Scenario: Intermediate commit content
- **WHEN** a secret appears in a middle commit and is removed in the tip
- **THEN** the scanner still receives it and the push is refused

#### Scenario: Lines already on the base
- **WHEN** an edited file contains untouched lines or lines merged in from the remote base
- **THEN** those lines are not rescanned, while merge-resolution lines are

#### Scenario: Refusal names its cause
- **WHEN** the `sonar` command is missing, or the scanner flags added lines of one file
- **THEN** the refusal says the CLI was not found, or names the flagged file, without printing the flagged value

#### Scenario: Scanner failure or object id malformed
- **WHEN** the scanner fails on every source, or a pushed id is not 40 or 64 hex characters
- **THEN** the push is refused with one fixed message that carries no repository or scanner content

#### Scenario: Deletion or no outgoing object
- **WHEN** only deleted refs are pushed or nothing is outgoing
- **THEN** the scan passes without a scanner

Evidence: `scripts/check_push_secrets.py`; `docs/development.md` (secret checks before Git pushes). Tests: `tests/test_push_secrets.py::PushSecretTests.test_intermediate_deleted_content_is_checked`, `tests/test_push_secrets.py::PushSecretTests.test_merged_base_lines_are_not_rescanned`, `tests/test_push_secrets.py::PushSecretTests.test_merge_resolution_content_is_scanned`, `tests/test_push_secrets.py::PushSecretTests.test_new_and_binary_files_are_scanned_whole`, `tests/test_push_secrets.py::PushSecretTests.test_untouched_lines_of_an_edited_file_are_not_rescanned`, `tests/test_push_secrets.py::PushSecretTests.test_missing_scanner_blocks_push`, `tests/test_push_secrets.py::PushSecretTests.test_refusal_names_the_cause_and_flagged_source_without_its_value`, `tests/test_push_secrets.py::PushSecretTests.test_malformed_object_ids_are_rejected_before_any_git_call`, `tests/test_push_secrets.py::PushSecretTests.test_deleted_ref_and_noop_do_not_require_scanner`.

### Requirement: Quality ratchet allows no new Ruff, mypy, cognitive complexity or ESLint debt
`tools/quality_baseline.py` SHALL run Ruff, mypy and a Python cognitive-complexity check (`python:S3776`, limit 15), plus Sonar's ESLint complexity and nested-ternary rules on `public/*.js` when installed, and compare the findings with `tests/fixtures/quality_baseline.json`. A new finding SHALL fail; a baseline entry that no longer occurs SHALL also fail until removed. A tool crash or version mismatch SHALL be fatal and never recorded as debt.

#### Scenario: Finding identity
- **WHEN** an unrelated edit moves a known finding to another line
- **THEN** the ratchet still passes, because a finding is identified by tool, path, code and message hash, and duplicates are counted

#### Scenario: New finding replaces a fixed one
- **WHEN** one baseline finding is fixed and a different one is added
- **THEN** the ratchet fails with a NEW and an OBSOLETE line

#### Scenario: Tool failure or version drift
- **WHEN** Ruff or mypy exits abnormally, produces no diagnostics on failure, or the installed versions differ from the recorded ones
- **THEN** the command exits with status 2; `--align-versions` rewrites only the recorded versions from `requirements-dev.txt`

#### Scenario: Cognitive complexity
- **WHEN** a function scores 16 or more and is not a baseline entry
- **THEN** the ratchet reports a NEW `cognitive` `S3776` finding named by the qualified function, not the score, while a function scoring exactly 15 passes

#### Scenario: Scope
- **WHEN** the ratchet collects findings
- **THEN** only Ruff, mypy, cognitive complexity and ESLint diagnostics are accepted, formatter diagnostics are rejected, and new files outside the excluded runtime directories are discovered

#### Scenario: JavaScript complexity or nested ternary
- **WHEN** a `public/*.js` function exceeds cognitive complexity 15 or contains a nested ternary
- **THEN** the ratchet reports it as NEW with file, line and rule and exits 1; the score is not part of the finding identity and a `NOSONAR` comment on the reported line suppresses it, as in Sonar

#### Scenario: ESLint not installed
- **WHEN** `node_modules` has no ESLint, as in CI's `quality` job
- **THEN** the JavaScript step prints that it was skipped and baseline entries of the ESLint tool are ignored, except under the pre-push hook (`PACECRAFT_NODE_MODULES` set), where it fails and asks for `npm ci`

Evidence:
- `pyproject.toml`
- `tests/fixtures/quality_baseline.json`
- `tests/test_quality_baseline.py::CognitiveComplexityTests.test_existing_over_limit_function_is_baseline_debt_and_new_ones_fail`
- `tests/test_quality_baseline.py::CognitiveComplexityTests.test_limit_is_exclusive_at_fifteen`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_alignment_records_only_the_pinned_tool_versions`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_all_source_boundaries_and_new_files_are_discovered`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_complex_function_and_nested_ternary_in_public_js_are_found`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_complexity_score_is_not_part_of_the_identity_and_nosonar_suppresses`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_duplicate_diagnostics_are_not_collapsed`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_formatter_is_not_collected_by_the_quality_gate`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_line_and_column_shifts_do_not_change_debt`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_new_violation_cannot_replace_one_fixed_violation`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_obsolete_diagnostic_requires_baseline_cleanup`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_skipped_eslint_ignores_its_baseline_entries`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_tool_failure_cannot_become_baseline_debt`
- `tests/test_quality_baseline.py::QualityBaselineTests.test_tool_version_drift_is_fatal`
- `tools/eslint.sonar.config.mjs`
- `tools/quality_baseline.py`

The pre-push hook points `PACECRAFT_NODE_MODULES` at the clone because its export of `HEAD` has no `node_modules`. CI runs the same command in the `quality` job of `.github/workflows/publish-container.yml`.

### Requirement: Merged branch coverage has a floor
CI SHALL combine exactly one coverage file from every Python test shard and fail when the combined branch coverage of `server` and `backend` is below `fail_under` in `pyproject.toml`. The floor SHALL equal the coverage recorded in the quality baseline, rounded down to the configured precision.

#### Scenario: Shard coverage missing or duplicated
- **WHEN** a shard uploads no coverage file or more than one
- **THEN** the quality job fails before reporting

#### Scenario: Floor and recorded coverage disagree
- **WHEN** `fail_under` differs from the recorded coverage evidence
- **THEN** the CI contract test fails

Evidence: `pyproject.toml` (`[tool.coverage.run]` with `branch` and `source = ["server", "backend"]`, `[tool.coverage.report]` with `fail_under`), the `Enforce merged coverage ratchet` step of `.github/workflows/publish-container.yml`, `coverage_evidence` in `tests/fixtures/quality_baseline.json`. Tests: `tests/test_ci_contracts.py::WorkflowSourceTests.test_quality_checks_all_sources_and_merges_every_shard`, `tests/test_local_test_execution.py::SupervisorTests.test_coverage_requires_exactly_one_nonempty_file_for_every_shard`.

### Requirement: Test shards partition the suite completely and deterministically
`tests/run_tests.py` SHALL discover every Python test and assign each `TestCase` class whole to exactly one shard, heaviest first to the least-loaded shard, independent of discovery order. A shard that selects no test SHALL fail. Weights SHALL come from recorded class seconds, and an unrecorded class SHALL weigh its test count times the median recorded seconds per test.

#### Scenario: Complete partition
- **WHEN** the suite is split into any number of shards
- **THEN** every test runs exactly once, no class is split, and reordering the input does not change a shard's content

#### Scenario: Empty selection
- **WHEN** a shard or a listing selects no test
- **THEN** the runner exits non-zero and its result file records the status `empty`

#### Scenario: Duration recording
- **WHEN** `--record-durations` is combined with a shard, the container suite, `--list` or `--changed`
- **THEN** argument parsing rejects it and an existing recording is untouched; a failed full run does not write one

#### Scenario: Container-sensitive subset
- **WHEN** `--suite container` runs
- **THEN** only modules matching the declared container patterns run, every pattern must match a discovered module, and the subset is non-empty and narrower than the suite

Evidence: `tests/run_tests.py` (`select_shard`, `assign_classes`, `class_weights`, `CONTAINER_SUITE_PATTERNS`, `parse_args`). Tests: `tests/test_ci_contracts.py::ShardingContractTests.test_every_test_runs_exactly_once_across_shards`, `tests/test_ci_contracts.py::ShardingContractTests.test_no_test_class_is_split_across_shards`, `tests/test_ci_contracts.py::ShardingContractTests.test_shards_are_deterministic_and_independent_of_input_order`, `tests/test_ci_contracts.py::ShardingContractTests.test_recorded_durations_outweigh_test_counts`, `tests/test_local_test_execution.py::RunnerEvidenceTests.test_empty_list_fails_with_evidence`, `tests/test_local_test_execution.py::RunnerEvidenceTests.test_partial_and_list_recording_rejected_without_overwrite`, `tests/test_ci_contracts.py::ContainerSuiteContractTests.test_every_container_pattern_matches_a_discovered_module`, `tests/test_ci_contracts.py::ContainerSuiteContractTests.test_container_suite_is_non_empty_and_narrower_than_the_full_suite`.

### Requirement: Changed-test selection never under-selects silently
`python tests/run_tests.py --changed` SHALL compare the merge base with `--base` (default `origin/develop`), including staged, unstaged and untracked files, and run only the test modules the change can affect. Where the selector cannot bound the effect it SHALL run the whole suite and print the reason.

#### Scenario: Selection rule
- **WHEN** a path changes
- **THEN** a test module is selected if its own file changed, it transitively imports a changed module, or a string literal in it or in a test support module it imports names the changed path, a parent directory, the file name or the dotted module; `test_line_endings` and `test_ai_docs_contract`, which check tracked files across the repository, are selected for every change (#2502)

#### Scenario: Reach through the composition root
- **WHEN** a module is reached only through `server.py`
- **THEN** it selects tests only if `server.py`, `backend/http_api/` or `backend/runtime/` changed

#### Scenario: Changed fixture
- **WHEN** only files under `tests/fixtures/` changed
- **THEN** the selection holds every test module whose sources or imported modules name `fixtures` as a path segment, plus the repository-wide checks, instead of the whole suite
- **AND** a fixture in a subdirectory selects such a module only when the module or a module it imports also names that subdirectory as a path segment, or one of them scans directories

#### Scenario: Full-suite fallback
- **WHEN** a changed path is under `FULL_SUITE_PATHS` (database manager, bootstrap and migrations, the test runner, selector and shared support modules, dependency, `Dockerfile` or `pyproject.toml` files), a source cannot be parsed, or at least 80 % of the test modules are selected
- **THEN** the whole suite runs and the reason is printed

#### Scenario: Heavy tooling modules
- **WHEN** no input of `test_fixture_standard_data` or `test_ci_contracts` changed
- **THEN** a local `--changed` run skips them and prints why; any other run executes them

#### Scenario: Nothing affected or base unknown
- **WHEN** no test module is affected (an empty change, or a suite filter that excludes the selected modules), or the base ref cannot be diffed
- **THEN** the runner prints "No Python tests are affected." and exits 0, or exits non-zero with a message and no traceback

Evidence:
- `docs/testing.md` (Changed-Test Selection)
- `tests/AGENTS.md`
- `tests/changed_tests.py` (`FULL_SUITE_PATHS`, `HEAVY_MODULES`, `FIXTURES`, `REPOSITORY_WIDE`, `FULL_SUITE_SHARE`, `SERVER_WIRED_PATHS`, `select_modules`, `heavy_skips`)
- `tests/run_tests.py`
- `tests/test_changed_tests.py::ChangedPathsTests.test_reports_committed_uncommitted_and_untracked_paths`
- `tests/test_changed_tests.py::ChangedPathsTests.test_runner_reports_an_unknown_base_instead_of_a_traceback`
- `tests/test_changed_tests.py::ChangedPathsTests.test_runner_treats_a_suite_without_affected_tests_as_empty`
- `tests/test_changed_tests.py::SelectModulesTests.test_a_selection_covering_most_modules_falls_back_with_a_reason`
- `tests/test_changed_tests.py::SelectModulesTests.test_app_wide_tests_need_a_composition_root_change`
- `tests/test_changed_tests.py::SelectModulesTests.test_fixture_selects_modules_naming_the_fixtures_directory`
- `tests/test_changed_tests.py::SelectModulesTests.test_full_suite_paths_and_unparsable_sources_select_everything`
- `tests/test_changed_tests.py::SelectModulesTests.test_full_suite_paths_name_existing_repository_paths`
- `tests/test_changed_tests.py::SelectModulesTests.test_heavy_tooling_modules_run_only_when_their_inputs_change`
- `tests/test_changed_tests.py::SelectModulesTests.test_literals_select_patch_targets_and_named_paths`
- `tests/test_changed_tests.py::SelectModulesTests.test_transitive_imports_and_support_modules_select_importers`

### Requirement: CI runs the complete sharded suite unless only documentation changed
The CI Python test jobs SHALL run every test through `tests/run_tests.py --shard N --total T`, covering the whole suite across the shards. They SHALL use `--changed` only on a pull request that changes documentation alone (#2747). Changed-test selection is never evidence of complete validation.

#### Scenario: Pull-request validation
- **WHEN** CI validates a pull request that changes any path other than documentation
- **THEN** each shard job runs its share of the whole suite and the container job runs the container suite in the built image

#### Scenario: Documentation-only pull request
- **WHEN** every changed path of a pull request is Markdown or text under `docs/`, `.agents/skills/` (outside `scripts/`) or `openspec/`, or is `README.md`, `REVIEW.md`, `AGENTS.md` or a first-level `AGENTS.md` outside `public/`
- **THEN** shard 1 runs `tests/run_tests.py --changed --base HEAD^1 --with-heavy` and the Node unit tests, the other shards report without running tests, and the container, browser and quality jobs are skipped

#### Scenario: Shard count declared once
- **WHEN** the shard count changes
- **THEN** the workflow variable and its matrix stay equal

Evidence: the `test_shards` and container jobs of `.github/workflows/publish-container.yml`; `docs/testing.md` (Parallel Sharded CI Runner). Tests: `tests/test_ci_contracts.py::ShardingContractTests.test_native_shard_count_is_declared_once_and_matched_by_the_matrix`, `tests/test_ci_contracts.py::ContainerSuiteContractTests.test_container_job_runs_the_container_suite_with_matching_mounts`, `tests/test_ci_contracts.py::WorkflowSourceTests.test_quality_checks_all_sources_and_merges_every_shard`, `tests/test_ci_contracts.py::ChangedFileClassifierTests.test_only_documentation_paths_are_docs`, `tests/test_ci_contracts.py::ChangedFileClassifierTests.test_workflow_skips_suites_only_on_classified_or_reused_runs`, `tests/test_changed_tests.py::ChangedPathsTests.test_with_heavy_keeps_the_selected_slow_modules_for_ci`.

### Requirement: Backend never reaches the composition root
No backend module SHALL import `server`, or reach it through a dynamic import or `sys.modules`, and `server.py` SHALL NOT define a class or a top-level symbol that a backend module defines. Functions in `server.py` SHALL compose explicit dependencies or run lifecycle entry points, without nested behavior or domain, database or network calls.

#### Scenario: Backend imports the entry point
- **WHEN** a backend module imports `server` by any import form or resolves it dynamically
- **THEN** the architecture test fails naming the module and line

#### Scenario: Backend symbol redefined in server
- **WHEN** `server.py` defines a function or constant that a backend module already defines, or an application class
- **THEN** the architecture test fails; a module logger is not a redefinition

#### Scenario: Behavior added to a composition function
- **WHEN** a `server.py` function gains nested definitions, branching outside the lifecycle entry points, or database or network calls
- **THEN** the architecture test fails

Evidence: `server.py`, `backend/AGENTS.md`, `AGENTS.md` (Architecture and durable state). Tests: `tests/test_server_module_architecture.py::ServerModuleArchitectureTests.test_backend_does_not_import_or_reach_server_namespace`, `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_nested_layers_and_dynamic_server_access_are_detected`, `tests/test_server_ownership_architecture.py::ServerOwnershipArchitectureTests.test_server_does_not_redefine_backend_symbols`, `tests/test_server_ownership_architecture.py::ServerOwnershipArchitectureTests.test_server_definitions_are_composition_factories_or_lifecycle`, `tests/test_server_composition_architecture.py::ServerCompositionArchitectureTests.test_server_composition_bodies_do_not_own_domain_or_io_logic`.

### Requirement: Backend packages keep their import directions
Backend imports SHALL follow the permitted map by layer: `backend.canonical` imports only the standard library and itself, `backend.athlete` imports no other domain package, and providers, persistence, runtime and HTTP layers import only the packages their layer permits. A new edge outside the map SHALL fail; only a recorded, shrinking debt list may hold exceptions.

#### Scenario: Provider layer
- **WHEN** a module in `backend/providers` imports application code
- **THEN** only providers, canonical, config, errors, observability and the runtime clock, ports and socket-deadline modules are permitted

#### Scenario: Persistence and runtime layers
- **WHEN** `backend/db` or `backend/runtime` imports application code
- **THEN** only the shared modules, its own package and, for `db`, `backend.runtime` are permitted

#### Scenario: HTTP layer
- **WHEN** `backend/http_api` imports application code
- **THEN** domain packages, shared modules and `backend.runtime` are permitted, `backend.providers` is not, and `backend.db` only for the recorded debt entries; handlers hold no SQL

#### Scenario: Debt list
- **WHEN** a recorded exception is removed from the code, or a new one is added
- **THEN** the architecture test fails until the debt list matches

Evidence: `backend/AGENTS.md`, `AGENTS.md` (domain owners). Tests: `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_backend_import_directions_match_pending_baseline`, `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_relative_absolute_package_and_lazy_imports`, `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_canonical_package_imports_only_stdlib_and_itself`, `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_canonical_import_direction_is_enforced_for_sample_layers`, `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_athlete_has_no_domain_package_dependencies`, `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_http_sql_execute_sites_match_pending_baseline`.

### Requirement: Backend packages are cycle-free
Backend packages SHALL NOT import each other in a cycle, counting lazy, relative and function-local imports at package level, and modules SHALL NOT form an eager runtime import cycle. The recorded cycle baseline SHALL stay empty.

#### Scenario: New package cycle
- **WHEN** a change makes two packages import each other, including through a function-local or type-only import
- **THEN** the architecture test fails against the empty baseline

#### Scenario: Eager module cycle
- **WHEN** two backend modules import each other at module load
- **THEN** the architecture test fails; imports under `TYPE_CHECKING` or inside functions do not count at module level

Evidence: `tests/fixtures/package_import_cycles.json` (empty for the module and all-imports modes), `tests/architecture_analysis.py`. Tests: `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_package_import_cycles_match_shrinking_baseline`, `tests/test_backend_layer_contracts.py::BackendLayerContractTests.test_cycle_detection_includes_lazy_relative_and_type_only_imports`, `tests/test_server_module_architecture.py::ServerModuleArchitectureTests.test_backend_has_no_eager_runtime_import_cycles`, `tests/test_server_module_architecture.py::ServerModuleArchitectureTests.test_import_cycle_guard_ignores_type_only_and_function_local_imports`.

### Requirement: Documented versions are guarded against the code
A test SHALL fail when the current schema version stated in `README.md`, `docs/schema-history.md` or `docs/operations.md`, or the privacy export format version stated in `docs/operations.md`, differs from the code, or when `docs/schema-history.md` lacks a description of any schema version from 22 to the current one.

#### Scenario: Schema bump without documentation
- **WHEN** `CURRENT_SCHEMA_VERSION` changes and one of the three documents still names the old version or no version
- **THEN** the suite fails naming the document

#### Scenario: Missing history entry
- **WHEN** `docs/schema-history.md` has no entry for a version between 22 and the current one
- **THEN** the suite fails naming that version

Evidence: `backend/db/schema.py` (`CURRENT_SCHEMA_VERSION`), `backend/backup/export.py` (`PRIVACY_EXPORT_FORMAT_VERSION`). Tests: `tests/test_docs_version_drift.py::DocsVersionDriftTest.test_documented_schema_version_matches_code`, `tests/test_docs_version_drift.py::DocsVersionDriftTest.test_documented_export_format_version_matches_code`, `tests/test_docs_version_drift.py::DocsVersionDriftTest.test_schema_history_describes_every_version_from_the_baseline`.
