# Spec Delta

## ADDED Requirements

### Requirement: Protected bot merges

Eligible Dependabot and release pull requests SHALL be eligible for direct squash merge without Gitar, while all other applicable protections remain enforced. Human pull requests SHALL remain subject to Gitar.

#### Scenario: Eligible dependency update
- **WHEN** a same-repository Dependabot pull request targets develop with auto-merge enabled and all applicable non-Gitar protections pass
- **THEN** the automation can request a squash merge without a Gitar check

#### Scenario: Release pull request
- **WHEN** the release app opens an expected version or promotion branch for its protected target and release testing is satisfied
- **THEN** the automation can request a squash merge without Gitar

#### Scenario: Untrusted metadata
- **WHEN** a human pull request imitates a bot branch, title, label, or commit author
- **THEN** it is ineligible for this automation

#### Scenario: Unsatisfied protection
- **WHEN** a required non-Gitar check is missing, failing, pending, or stale, or a review thread is unresolved
- **THEN** the pull request remains unmerged

#### Scenario: Changed head
- **WHEN** the pull request head changes after evaluation
- **THEN** the attempted merge cannot merge the new revision

#### Scenario: Missed event
- **WHEN** an eligible pull request becomes mergeable without an observed event
- **THEN** a bounded recovery run can retry it

#### Scenario: Deployment gate
- **WHEN** the deployment gate is disabled
- **THEN** the automation remains disabled

Evidence: `.github/workflows/bot-merge.yml`; `tools/bot_merge.py`; `tests/test_bot_merge.py`. On 2026-10-30 the release app was removed from the Default ruleset bypass list; the isolated Gitar exemption and normal checks were verified by reading the live rulesets. The app directly squash-merged Dependabot PR #1502 at its checked head in Actions run 41124099781 with non-Gitar checks passing and no unresolved threads. Rule suite 4824127971 recorded Default status checks, pull-request rules and code scanning passing and Gitar skipped. Earlier rule suites 4355093065 and 4355238064 rejected unresolved conversation and failing or pending check cases for the repository owner; equivalent negative attempts by the release app remain unverified.
