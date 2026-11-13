# build-release-and-deployment Specification

## Purpose

Keep the private standalone application reproducible and its delivery tied to tested immutable source, versioned releases and verified images.

Documents checked-in delivery behavior and operational boundaries, not the current hosted ruleset/CI/deployment state. This backfill performs no remote GitHub, registry or Unraid action. LAN/VPN isolation and trusted HTTPS require deployment configuration outside the listener itself.

## Requirements

### Requirement: Reproducible encrypted standalone runtime image

The Docker build SHALL use the pinned Python 3.14 base, hash-locked binary Python dependencies and explicit application inputs, run as the non-root app user, and use writable persistent /data outside read-only application code.

#### Scenario: Container build
- **WHEN** the maintained Dockerfile builds the application
- **THEN** only explicit server/backend/public/runtime inputs and locked dependencies enter the runtime image

#### Scenario: Container execution
- **WHEN** the image starts with its persistent data mount
- **THEN** the application runs as non-root on configured port 8090 by default and uses /data for durable state

#### Scenario: Developer artifacts present
- **WHEN** the checkout contains local skills, OpenSpec state, worktrees or node_modules
- **THEN** development artifacts are excluded from the runtime build inputs/context policy

Evidence: `Dockerfile`; `requirements.in`; `requirements.txt`; `.dockerignore`. Tests: `tests/test_container_delivery.py::test_app_code_is_not_writable_by_the_app_user`; `tests/test_container_delivery.py::test_app_user_ids_match_the_documented_bind_mount_owner`; `tests/test_ci_contracts.py::test_container_job_runs_the_container_suite_with_matching_mounts`. Hosted deployment was not executed.

### Requirement: Container runtime contract

The image SHALL run `python /app/server.py` as user `app` (UID 100, GID 101) on port 8090 by default, keep durable state only under the volume `/data`, never write application code under `/app`, and report container health from the unauthenticated health endpoint. It SHALL work with a read-only root file system, no new privileges and all capabilities dropped.

#### Scenario: Image defaults
- **WHEN** the image starts without overrides
- **THEN** `PORT=8090`, `DATA_DIR=/data`, `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1` and `MALLOC_ARENA_MAX=2` (bounded malloc arenas for the thread-per-request server, #2526) are set, port 8090 is exposed, `/data` is a declared volume owned by `app`, and `/app` is not writable

#### Scenario: Health check
- **WHEN** the container runtime probes the container
- **THEN** it requests `GET http://127.0.0.1:$PORT/api/health` every 30 s with a 3 s limit, a 5 s start period and 3 retries, and a non-2xx answer or a timeout marks the probe failed

#### Scenario: Hardened start
- **WHEN** the container runs with `--read-only`, `--security-opt no-new-privileges:true` and `--cap-drop=ALL`
- **THEN** startup, the database under `/data` and the container test suite work, because application code under `/app` is never written

#### Scenario: Host directory ownership
- **WHEN** a host directory is bind-mounted to `/data`
- **THEN** it must be writable by UID 100 / GID 101

Evidence: `Dockerfile` (`ENV`, `USER`, `VOLUME`, `HEALTHCHECK`); `.github/workflows/publish-container.yml` job `container_tests`. Tests: `tests/test_container_delivery.py::test_app_code_is_not_writable_by_the_app_user`; `tests/test_container_delivery.py::test_app_user_ids_match_the_documented_bind_mount_owner`; `tests/test_ci_contracts.py::test_container_job_runs_the_container_suite_with_matching_mounts`. No test pins the health check parameters.

### Requirement: Hash-locked dependency inputs

Direct Python requirements SHALL live in `requirements.in`, `requirements-dev.in` and `requirements-graphify.in` with exact pins, and their `.txt` files SHALL be pip-compile outputs with hashes. The image and CI SHALL install only the application and development locks, with `--only-binary=:all: --require-hashes`.

#### Scenario: Runtime dependencies
- **WHEN** the image is built
- **THEN** it installs exactly the lock of the four direct runtime requirements (`garminconnect`, `curl_cffi`, `sqlcipher3-binary`, `tzdata`) and their hashed dependencies

#### Scenario: Development and Graphify locks
- **WHEN** CI installs development tools
- **THEN** it uses the development lock, which adds `coverage`, `mypy` and `ruff` to the runtime requirements; the Graphify lock is used only by the local Graphify environment, and a Ruff or mypy pin change also needs the recorded tool versions of the quality baseline (see `developer-quality-gates`)

Evidence: `requirements.in`; `requirements-dev.in`; `requirements-graphify.in`; `Dockerfile`; `docs/dependencies.md`. Tests: `tests/test_ci_contracts.py::test_dependabot_pip_compile_updates_the_hash_locked_docker_inputs`.

### Requirement: Private deployment and transport prerequisites

The supported application deployment SHALL remain a standalone single-athlete service on a trusted LAN/private VPN, with APP_PASSWORD-protected UI/API and trusted HTTPS where browser secure-context features are required.

#### Scenario: Private service deployment
- **WHEN** the application is deployed using the maintained runtime instructions
- **THEN** persistent athlete storage is retained and access is restricted by the operator's LAN/VPN/reverse-proxy boundary

#### Scenario: Browser microphone used remotely
- **WHEN** the athlete uses secure-context browser functionality outside localhost
- **THEN** the deployment supplies trusted HTTPS

#### Scenario: Listener binding inspected
- **WHEN** the server binds 0.0.0.0 at the configured port
- **THEN** this is not interpreted as an implemented network allowlist or permission for direct internet exposure

Evidence: `README.md`; `AGENTS.md`; `Dockerfile`; `server.py::main`; `backend/config.py::security_configuration_error`. Tests: `tests/test_config.py::test_security_error_order_and_success`; `tests/test_container_delivery.py`.

### Requirement: Read-only source validation and fail-closed check aggregation

The checked-in CI validation SHALL check the event source with read-only checkout permissions, run Python shards/syntax/container/browser/quality evidence, and fail required aggregate jobs when any required component is not successful.

#### Scenario: Pull-request source validation
- **WHEN** an ordinary pull request runs validation
- **THEN** its code is checked without persisted checkout credentials or privileged publication credentials

#### Scenario: A required check fails or is missing
- **WHEN** a required shard, container/syntax/SBOM or browser component does not succeed
- **THEN** the aggregate validation job fails rather than reporting completion

#### Scenario: AI documentation missing
- **WHEN** the documentation workflow cannot find required guidance or validator files
- **THEN** its explicit existence checks fail instead of silently skipping validation

Evidence: `.github/workflows/publish-container.yml`; `.github/workflows/validate-ai-docs.yml`; `tests/run_tests.py`. Tests: `tests/test_ci_contracts.py::test_workflow_actions_are_immutable_and_ci_does_not_persist_credentials`; `tests/test_ci_contracts.py::test_browser_results_are_aggregated_before_publishing`; `tests/test_ci_contracts.py::test_ai_docs_requires_guidance_before_discovery`.

### Requirement: Validation job topology

The test workflow SHALL run on pushes and pull requests to `develop` and `main`, on published releases and on manual dispatch. It SHALL run four native Python shards, a syntax check, the container suite in the shared image, an image SBOM, the browser matrix and, once the aggregate `test` job succeeded, the quality job. A newer push to a pull request SHALL cancel only that pull request's older run.

#### Scenario: Native shards
- **WHEN** the workflow runs
- **THEN** shards 1 to 4 run `coverage run tests/run_tests.py --shard N --total 4` on Python 3.14 with hash-locked dependencies, each uploads exactly one coverage file, and the job names are `Test shard N/4`

#### Scenario: Container suite
- **WHEN** the shared image is available
- **THEN** `tests/run_tests.py --suite container` runs inside it with a read-only root, no new privileges, all capabilities dropped, 256 processes, 512 MiB, one CPU and read-only mounts of the test inputs

#### Scenario: Quality job
- **WHEN** the aggregate `test` job succeeded
- **THEN** the quality job fails unless every shard delivered exactly one coverage file, then enforces the coverage floor and the quality ratchet that `developer-quality-gates` specifies

#### Scenario: Browser matrix
- **WHEN** the shared image is available
- **THEN** `mobile` and `tablet-landscape` run in one shard each and `desktop` in two, on Node 22 with `npm ci --ignore-scripts` and the pinned prepared browser image; the Node unit tests (`node --test tests/*.cjs`) run once, in desktop shard 1

#### Scenario: Browser evidence
- **WHEN** the browser matrix finishes
- **THEN** the `Browser checks` job fails unless the matrix succeeded and every expected project shard delivered a summary; a partial rerun is valid because each shard counts with its latest attempt, and failure artifacts never contain traces or authentication state

#### Scenario: SBOM
- **WHEN** SBOM generation fails once
- **THEN** it is retried once after 30 seconds, and a second failure fails the required aggregate

#### Scenario: Run cancellation
- **WHEN** a push, release or dispatch run is in progress
- **THEN** no other run cancels it; only a newer push to the same pull request does

Evidence: `.github/workflows/publish-container.yml` (`on`, `concurrency`, `test_shards`, `container_tests`, `test`, `quality`, `image_sbom`, `e2e`, `browser`); `.github/scripts/aggregate_browser_results.py`; `pyproject.toml` (`[tool.coverage]`). Tests: `tests/test_ci_contracts.py::test_native_shard_count_is_declared_once_and_matched_by_the_matrix`; `tests/test_ci_contracts.py::test_quality_checks_all_sources_and_merges_every_shard`; `tests/test_ci_contracts.py::test_container_job_runs_the_container_suite_with_matching_mounts`; `tests/test_ci_contracts.py::test_e2e_runs_beside_unit_tests_and_shards_desktop_completely`; `tests/test_ci_contracts.py::test_ci_failure_artifacts_exclude_traces_and_auth_state`; `tests/test_ci_contracts.py::test_pull_request_runs_cancel_only_their_own_older_run`; `tests/test_browser_aggregation.py::test_partial_rerun_uses_each_shards_latest_attempt`. No test pins the SBOM retry.

### Requirement: Immutable release source and version agreement

Release publication SHALL resolve immutable tested source, require a release tag matching APP_VERSION on protected-main ancestry, and verify the source/version contract again before pushing the tested image. The published image SHALL be the image the test, browser and SBOM jobs used, never a rebuild.

#### Scenario: Version or tag mismatch
- **WHEN** a requested release tag, tested source and APP_VERSION do not identify the required release
- **THEN** publication validation fails before publishing

#### Scenario: Stale successful test
- **WHEN** an older successful test result arrives after main has moved incompatibly
- **THEN** it cannot reset main or create a release for unverified current source

#### Scenario: Matching tested source
- **WHEN** the intended protected source/version contract is verified
- **THEN** the publish job can proceed only after its required tests and gates succeed

Evidence: `.github/scripts/release_source.py::resolve`; `.github/scripts/release_source.py::verify`; `.github/workflows/publish-container.yml`. Tests: `tests/test_ci_contracts.py::test_source_and_tag_must_identify_same_commit`; `tests/test_ci_contracts.py::test_tag_version_must_match_application`; `tests/test_ci_contracts.py::test_release_rejects_commit_outside_main`; `tests/test_release_events.py::test_stale_test_result_cannot_reset_main_or_create_a_release`.

### Requirement: The published image is the tested image

The workflow SHALL build the application image once per run from the event commit, label it with the OCI source and revision, and share that one image with the container suite, the SBOM job, every browser job and the publish job. Publication SHALL push this image and SHALL NOT rebuild it.

#### Scenario: Release publication
- **WHEN** the publish job runs
- **THEN** it loads the shared image artifact, tags it `<registry>/<repository>:<release tag>` and `:sha-<full commit sha>`, pushes both and reads the pushed digest; a digest that is not `sha256:` plus 64 hex characters fails the job

#### Scenario: Shared artifact missing
- **WHEN** the image artifact cannot be downloaded
- **THEN** the consuming job fails instead of building its own image

#### Scenario: Publication paths
- **WHEN** a release is published, or a manual dispatch on `main` sets `publish_container`
- **THEN** the publish job runs after the source, test, browser, quality and SBOM jobs; a dispatch on another ref or with `publish_container` false never publishes

Evidence: `.github/workflows/publish-container.yml` (`image`, `build-and-push`). Tests: `tests/test_ci_contracts.py::test_ci_image_is_built_once_and_shared_by_consumers`; `tests/test_ci_contracts.py::test_release_pushes_the_tested_image_instead_of_rebuilding`; `tests/test_ci_contracts.py::test_e2e_runs_beside_unit_tests_and_shards_desktop_completely` (publish dependencies).

### Requirement: Release source reference rules

The source resolver SHALL accept only safe reference names, resolve them to a commit, and for a release require that the tag is `MAJOR.MINOR.PATCH`, the source is that tag or a 40-character commit id, both name the same commit, the commit is an ancestor of `origin/main`, and `APP_VERSION` at that commit equals the tag.

#### Scenario: Mutable release source
- **WHEN** a release names a branch as its source
- **THEN** resolution fails with "Release source must be its tag or an immutable commit SHA"

#### Scenario: Read-only preflight before the tag exists
- **WHEN** a version pull request is tested by dispatch with `publish_container=false`
- **THEN** no tag is required and the run fails unless `APP_VERSION` at the event commit equals the requested `release_tag`

#### Scenario: Build checkout differs
- **WHEN** the publish job's checkout is not the commit the `source` job resolved
- **THEN** verification fails with "Build checkout differs from the tested source SHA"

Evidence: `.github/scripts/release_source.py` (`resolve`, `verify`, `_validate_source_ref`, `_verify_release_integrity`); `.github/workflows/publish-container.yml` (`source`, `build-and-push`). Tests: `tests/test_ci_contracts.py::test_release_rejects_mutable_branch_source`; `tests/test_ci_contracts.py::test_read_only_release_pr_can_resolve_before_its_tag_exists`; `tests/test_ci_contracts.py::test_read_only_release_pr_version_must_match_application`; `tests/test_ci_contracts.py::test_resolve_rejects_invalid_source_reference`; `tests/test_ci_contracts.py::test_verify_rejects_invalid_sha`; `tests/test_ci_contracts.py::test_executed_source_is_bound_to_the_workflow_event`.

### Requirement: Protected version promotion

The daily-release workflow SHALL prepare version changes through release-version pull requests and continue promotion from verified merged/tested state; it SHALL avoid duplicate release-test dispatch when the relevant test is already present.

#### Scenario: New releasable changes
- **WHEN** the scheduled/manual release process needs a new version
- **THEN** it prepares a Conventional Commit version PR rather than directly editing protected main

#### Scenario: Version PR still open
- **WHEN** the release-version PR has not merged
- **THEN** promotion is deferred and no merged-state claim is made

#### Scenario: Test already queued or successful
- **WHEN** the relevant source has an existing release-test run
- **THEN** the workflow does not dispatch a duplicate test solely because a check context is absent

#### Scenario: Version choice
- **WHEN** the process computes the next version
- **THEN** it increments the patch of APP_VERSION unless a manual dispatch names a MAJOR.MINOR.PATCH version, which must be greater than the latest release and cannot be chosen while a different APP_VERSION still awaits promotion
- **AND** a merged version branch must match the merged APP_VERSION, and commits that only set the application version do not count as releasable changes

Evidence: `.github/workflows/daily-release.yml` (`prepare-version`: `version_is_greater`, `count_releaseable_commits`). Tests: `tests/test_release_events.py::test_open_pr_dispatches_release_test`; `tests/test_release_events.py::test_existing_tests_do_not_dispatch_again`; `tests/test_release_events.py::test_unmerged_version_test_defers_without_waiting_or_mutating`; `tests/test_release_events.py::test_pending_promotion_has_a_same_tree_duplicate_guard`.

### Requirement: Scheduled release start and release blockers

The release workflow SHALL start daily at 03:00 UTC and on manual dispatch, run one at a time without cancelling a queued run, and act through the release GitHub App. A scheduled run SHALL do nothing while any open issue or pull request carries the label `release-blocker`.

#### Scenario: Open blocker
- **WHEN** the schedule fires and an open issue or pull request has the label `release-blocker`
- **THEN** no version or promotion pull request is created and the job summary names the blocking numbers

#### Scenario: Blocker query fails
- **WHEN** the label query fails
- **THEN** the run fails without releasing

#### Scenario: Manual dispatch
- **WHEN** the workflow is dispatched manually
- **THEN** the blocker check is skipped

#### Scenario: Version pull request
- **WHEN** releasable commits exist and no promotion is pending
- **THEN** branch `chore/release-version-<version>` changes only the `APP_VERSION` line, the commit and title are `chore(release): set application version to <version>`, the base is `develop`, and squash auto-merge is enabled

#### Scenario: Nothing to release
- **WHEN** no releasable commit exists since the latest release and no version was requested
- **THEN** the run ends without changes

#### Scenario: Continuation events
- **WHEN** a version pull request into `develop` is merged, or the dispatched test run of a `chore/release-version-*` branch succeeds
- **THEN** the same job continues with promotion; neither event is gated by the blocker label

Evidence: `.github/workflows/daily-release.yml` (`on`, `concurrency`, `prepare-version`). Tests: `tests/test_release_events.py::test_only_the_schedule_is_gated_and_every_release_step_honors_it`; `tests/test_release_events.py::test_open_blockers_hold_the_release_with_a_summary`; `tests/test_release_events.py::test_failed_query_fails_without_releasing`; `tests/test_release_events.py::test_no_blockers_release_as_before`; `tests/test_ci_contracts.py::test_daily_release_limits_default_token_permissions`; `tests/test_ci_contracts.py::test_daily_release_uses_release_tree_to_count_new_commits`; `tests/test_release_events.py::test_already_merged_version_test_refreshes_develop_without_waiting`.

### Requirement: Promotion to main and release creation

After the version change is on `develop`, the workflow SHALL open a promotion pull request from `develop` to protected `main`. A GitHub release SHALL be created only after the push-triggered tests of `main` succeeded and the tested tree is still the tree of `main`. The release tag SHALL be the `APP_VERSION` read from `server.py`.

#### Scenario: Promotion pull request
- **WHEN** `APP_VERSION` differs from the latest release tag and `main` does not yet hold the tree of `develop`
- **THEN** branch `chore/release-promotion-<version>` is created from `develop` (merging `main` with strategy `ours` when `main` is not an ancestor), a pull request to `main` titled `chore(release): promote <version> to main` is opened and squash auto-merge is enabled

#### Scenario: Main already holds the tree
- **WHEN** the tree of `main` equals the tree of `develop`
- **THEN** no second promotion pull request is created

#### Scenario: Leftover branch or tag
- **WHEN** the version or promotion branch exists remotely without an open pull request, or the tag exists without a release
- **THEN** the run fails instead of overwriting it

#### Scenario: Release creation
- **WHEN** the test workflow succeeded for a push to `main` of this repository and the tested tree equals the current tree of `main`
- **THEN** a release named after `APP_VERSION` is created on the current `main` commit, provided the version is greater than the latest full release and no release of that version exists, with notes listing the commit subjects since the previous release as found on `develop` and a comparison link

#### Scenario: Release starts publication
- **WHEN** the release is created with the release App token
- **THEN** its `release` event starts the publish path, which is the only automatic path to the container registry

#### Scenario: Version line format
- **WHEN** tooling reads or writes the version
- **THEN** it uses the single source line `APP_VERSION = "MAJOR.MINOR.PATCH"` in `server.py`; a missing or differently formatted line fails the run

Evidence: `.github/workflows/daily-release.yml` (`prepare-version`, `create-release`); `.github/scripts/release_source.py` (`APP_VERSION_PATTERN`). Tests: `tests/test_release_events.py::test_only_successful_main_push_tests_can_create_a_release`; `tests/test_release_events.py::test_same_tree_on_a_new_main_commit_can_create_a_release`; `tests/test_release_events.py::test_matching_tested_main_can_continue_without_querying_a_promotion_pr`; `tests/test_release_events.py::test_pending_promotion_has_a_same_tree_duplicate_guard`; `tests/test_ci_contracts.py::test_main_push_test_can_create_the_release_after_promotion_merge`.

### Requirement: Signed digest publication

The publication workflow SHALL sign and verify the built image digest, attach the SPDX SBOM as a signed attestation (the image carries OCI source and revision labels), promote latest only for the current latest release, and verify release/latest tag digest parity.

#### Scenario: Verified image published
- **WHEN** all required source/tests/quality/browser conditions succeed
- **THEN** the publication job pushes version/SHA tags, signs the resulting digest and verifies the signing identity

#### Scenario: Image name follows the repository
- **WHEN** the image metadata is extracted
- **THEN** the image is `ghcr.io/<repository>`, which is `ghcr.io/lukas-beike/pacecraft` since the repository rename (#1796), tagged with the release version and the full source SHA

#### Scenario: Older release publication races
- **WHEN** the requested tag is no longer the repository's latest release
- **THEN** the workflow refuses to replace latest with that older tag

#### Scenario: Digest parity fails
- **WHEN** a published release or latest tag resolves to a different digest
- **THEN** publication verification fails rather than reporting a successful verified image

Evidence: `.github/workflows/publish-container.yml`. Tests: `tests/test_ci_contracts.py::test_published_tags_are_verified_against_the_signed_digest`. Hosted signing/publication was not executed in this documentation backfill.

### Requirement: Safe privileged automation and metadata checks

Privileged PR automation SHALL execute trusted workflow/branch code, treat PR data as untrusted input, validate Conventional Commit title/subjects fail-closed, and preserve protected review/merge gates.

#### Scenario: Commit API fails or returns no subjects
- **WHEN** the conventions workflow cannot obtain the expected commit list
- **THEN** validation fails rather than accepting an empty result

#### Scenario: Invalid commit/title
- **WHEN** a supplied PR title or commit subject does not match the permitted Conventional Commit form
- **THEN** metadata validation fails

#### Scenario: Dependabot tool-version alignment
- **WHEN** automation aligns a dependency PR's quality baseline
- **THEN** trusted develop code reads proposed files as data and head-identity protection rejects a moved-head write

Evidence: `.github/workflows/validate-conventions.yml`; `.github/workflows/dependabot-automerge.yml`; `.github/workflows/auto-rebase-squash.yml`; `.github/AGENTS.md`. Tests: `tests/test_ci_contracts.py::test_dependabot_tool_bumps_align_the_baseline_without_running_pr_code`; `tests/test_validate_conventions_workflow.py::test_failing_gh_api_fails_the_step`; `tests/test_validate_conventions_workflow.py::test_empty_commit_listing_fails_the_step`; `tests/test_validate_conventions_workflow.py::test_invalid_commit_subject_fails_the_step`.

### Requirement: Issue link and workflow lint checks

Pull requests by non-bot authors SHALL name their issue in the body, and every pull request and every push to `develop` or `main` SHALL lint the workflow files with a pinned linter.

#### Scenario: Missing issue link
- **WHEN** the body of a pull request whose author is not a bot contains none of `Closes #N`, `Fixes #N`, `Resolves #N` or `Part of #N`
- **THEN** the conventions check fails

#### Scenario: Bot pull request
- **WHEN** the author type is `Bot`
- **THEN** the issue-link step is skipped; title and commit subjects are still checked

#### Scenario: Permitted types
- **WHEN** a title or commit subject is checked
- **THEN** it must match `<type>(<optional scope>)!?: <text>` with type `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style` or `test`

#### Scenario: Workflow lint
- **WHEN** workflow files are linted
- **THEN** actionlint 1.7.12, pinned by image digest, runs without shellcheck and pyflakes and ignores only the unknown `queue` concurrency key

Evidence: `.github/workflows/validate-conventions.yml`; `.github/workflows/workflow-lint.yml`. Tests: `tests/test_validate_conventions_workflow.py::test_closes_and_part_of_pass`; `tests/test_validate_conventions_workflow.py::test_body_without_issue_link_fails`; `tests/test_validate_conventions_workflow.py::test_bot_pull_requests_are_exempt`. No test pins the linter configuration.

### Requirement: Dependency updates, auto-merge and auto-rebase

Dependabot SHALL propose npm, pip, Docker and GitHub Actions updates against `develop` after a 3-day cooldown. Squash auto-merge SHALL be enabled only for Dependabot pull requests from this repository against `develop`. After each push to `develop`, open same-repository pull requests with squash auto-merge SHALL be rebased onto `develop`.

#### Scenario: Update cadence
- **WHEN** Dependabot runs
- **THEN** npm, pip and Docker are checked daily and GitHub Actions weekly, commit prefixes are `build` (`ci` for Actions), and at most 10 pip pull requests are open

#### Scenario: Auto-merge scope
- **WHEN** a pull request is opened, reopened or updated
- **THEN** squash auto-merge is enabled only if the author is `dependabot[bot]`, the base is `develop` and the head is in this repository; the workflow never checks out pull-request code

#### Scenario: Rebase after a develop push
- **WHEN** `develop` receives a push
- **THEN** every open same-repository pull request to `develop` with squash auto-merge that is not conflicting is rebased; a conflict is reported as a notice and skipped, any other failure fails the job after all pull requests were tried

#### Scenario: Hourly run
- **WHEN** the hourly schedule fires
- **THEN** only the Dependabot quality-baseline alignment runs; no pull request is rebased

Evidence: `.github/dependabot.yml`; `.github/workflows/dependabot-automerge.yml`; `.github/workflows/auto-rebase-squash.yml`. Tests: `tests/test_ci_contracts.py::test_dependabot_covers_all_manifests_on_develop`; `tests/test_ci_contracts.py::test_dependabot_updates_wait_three_days`; `tests/test_ci_contracts.py::test_dependabot_automerge_is_limited_to_develop`; `tests/test_ci_contracts.py::test_dependabot_automerge_security_and_major_updates`. No test pins the rebase eligibility or the hourly schedule.

### Requirement: Generated OpenSpec skills are refreshed without privileged generation

A daily workflow (04:30 UTC, or manual) SHALL run `openspec update` with the locked CLI on `develop` in a job without write credentials, and a second job SHALL publish the resulting patch as a pull request only when every changed path is a generated OpenSpec skill.

#### Scenario: Patch touches other files
- **WHEN** the patch changes a path other than `.agents/skills/.openspec-target` or `.agents/skills/openspec-<name>/SKILL.md`, changes a file mode or adds a symbolic link
- **THEN** the publish job fails and nothing is pushed

#### Scenario: Skills changed
- **WHEN** the patch is acceptable
- **THEN** branch `chore/openspec-update` is replaced with one commit titled `chore(openspec): regenerate skills with OpenSpec <version>`, a pull request to `develop` is opened or reused, and squash auto-merge is enabled

#### Scenario: Earlier pull request was rejected
- **WHEN** a pull request with the same title was closed without merging
- **THEN** no new pull request is opened for that version

#### Scenario: Nothing changed
- **WHEN** regeneration produces no difference
- **THEN** the publish job does not run

Evidence: `.github/workflows/openspec-update.yml` (`regenerate`, `publish`). Tests: `tests/test_ci_contracts.py::test_openspec_update_runs_pinned_cli_before_any_write_token`.

### Requirement: Disposable demo and fixture containers cannot replace the athlete's container

The fixture runtime SHALL start only when `AI_COACH_DISPOSABLE_FIXTURE` is exactly `1`. The demo script SHALL accept only container names that start with `demo` or `fixture`, optionally after `pacecraft-` or `ai-coach-`, and SHALL refuse every other name before it builds, stops or removes anything.

#### Scenario: Production name
- **WHEN** the demo script is called with `pacecraft`, `ai-coach` or any non-demo name
- **THEN** it stops before any Docker command

#### Scenario: Replacing an existing demo container
- **WHEN** a container with the demo name exists
- **THEN** it is stopped and removed without `-v`; a failed build, listing, stop or removal stops the script before a new container starts

#### Scenario: Demo start
- **WHEN** the demo container starts
- **THEN** it is published only on `127.0.0.1:<port>` (default 8091), seeds synthetic data itself (`FIXTURE_AUTO_SEED=1`), keeps data in a named volume only with `-Persist`, and is reported ready after at most 60 health probes

Evidence: `scripts/demo-container.ps1`; `e2e/fixture_runtime.py::require_disposable_fixture_marker`. Tests: `tests/test_container_delivery.py::test_fixture_refuses_any_marker_value_other_than_exact_one`; `tests/test_container_delivery.py::test_refused_names_stop_before_any_docker_call`; `tests/test_container_delivery.py::test_existing_container_is_stopped_then_removed_without_volumes`; `tests/test_container_delivery.py::test_run_arguments_keep_the_demo_on_loopback_and_disposable`.

### Requirement: Public marketing deployment is separated from athlete runtime

The Pages workflow SHALL publish only the checked-in site directory through its GitHub Pages environment; the public marketing artifact SHALL not be treated as the authenticated athlete application.

#### Scenario: Site deployment triggered
- **WHEN** a push to `main` changes `site/**` or the Pages workflow, or a manual dispatch runs
- **THEN** the Pages artifact is built from site/ and deployed through github-pages; a push to `develop` does not deploy

#### Scenario: Athlete runtime compared with site
- **WHEN** the public site is inspected alongside the private runtime
- **THEN** the athlete API/data remains part of the private standalone runtime rather than the static Pages artifact

Evidence: `.github/workflows/pages.yml`; `site/index.html`; `Dockerfile`. Tests: `tests/test_ci_contracts.py::test_pages_deploy_only_from_main`. Hosted deployment was not executed.
