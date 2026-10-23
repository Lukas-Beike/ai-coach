# Build, release and deployment Specification Delta

## Purpose

Keep the private standalone application reproducible and its delivery tied to tested immutable source, versioned releases and verified images.

Documents checked-in delivery behavior and operational boundaries, not the current hosted ruleset/CI/deployment state. This backfill performs no remote GitHub, registry or Unraid action. LAN/VPN isolation and trusted HTTPS require deployment configuration outside the listener itself.

## ADDED Requirements

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

Evidence: `Dockerfile`; `requirements.in`; `requirements.txt`; `.dockerignore`. Tests: `tests/test_container_delivery.py`. See source inspection of `Dockerfile`/`.github/workflows/pages.yml`; the fixture module is related operational evidence and does not test Pages deployment. Hosted deployment was not executed.

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

### Requirement: Immutable release source and version agreement

Release publication SHALL resolve immutable tested source, require a release tag matching APP_VERSION on protected-main ancestry, and verify the source/version contract again before building the published image.


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

Evidence: `.github/workflows/daily-release.yml`. Tests: `tests/test_release_events.py::test_open_pr_dispatches_release_test`; `tests/test_release_events.py::test_existing_tests_do_not_dispatch_again`; `tests/test_release_events.py::test_unmerged_version_test_defers_without_waiting_or_mutating`; `tests/test_release_events.py::test_pending_promotion_has_a_same_tree_duplicate_guard`.

### Requirement: Signed digest publication

The publication workflow SHALL sign and verify the built image digest, attach configured provenance/SBOM, promote latest only for the current latest release, and verify release/latest tag digest parity.


#### Scenario: Verified image built
- **WHEN** all required source/tests/quality/browser conditions succeed
- **THEN** the publication job pushes version/SHA tags, signs the resulting digest and verifies the signing identity

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

### Requirement: Public marketing deployment is separated from athlete runtime

The Pages workflow SHALL publish only the checked-in site directory through its GitHub Pages environment; the public marketing artifact SHALL not be treated as the authenticated athlete application.


#### Scenario: Site deployment triggered
- **WHEN** a matching site/workflow change on develop/main or manual dispatch runs Pages
- **THEN** the Pages artifact is built from site/ and deployed through github-pages

#### Scenario: Athlete runtime compared with site
- **WHEN** the public site is inspected alongside the private runtime
- **THEN** the athlete API/data remains part of the private standalone runtime rather than the static Pages artifact

Evidence: `.github/workflows/pages.yml`; `site/index.html`; `Dockerfile`. Tests: `tests/test_container_delivery.py`. See source inspection of `Dockerfile`/`.github/workflows/pages.yml`; the fixture module is related operational evidence and does not test Pages deployment. Hosted deployment was not executed.
