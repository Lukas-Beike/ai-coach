# Tasks

## 1. Safe bot merge

- [x] 1.1 Implement trusted bot eligibility and head-bound direct squash attempts; exercise spoofed authors, branches, stale heads, closed PRs, and conflicts in regression tests.
- [x] 1.2 Add event-driven retries and bounded recovery without executing PR code; test duplicate events and concurrency.
- [x] 1.3 Preserve release test sequencing and verify version and promotion paths with focused tests.
- [x] 1.4 Verify the app cannot bypass non-Gitar rulesets and document the actual rulesets and recovery behavior.

## 2. Integration evidence

- [x] 2.1 Run focused and repository-required validation, and record unavailable checks as evidence gaps.
- [x] 2.2 Verify eligible and ineligible merges on GitHub where available, including pending checks and unresolved review threads; record unavailable checks as evidence gaps.
- [x] 2.3 Review the final changes and run strict OpenSpec validation before archive.

## Evidence gaps

- An approved no-checkout probe in Actions run 41124099781 directly squash-merged Dependabot PR #1502 as the release app at its checked head, with non-Gitar checks passing and no unresolved review threads. Rule suite 4824127971 shows the Default rules passing and Gitar skipped. PR #1501 remains open and must not be merged with failing required checks.
- Historical Default rule suite 4355093065 rejected a failing required check and an unresolved conversation, and 4355238064 rejected a pending required check. Those October 4 attempts used the repository owner, before the current ruleset configuration. GitHub enforcement of those negative cases has not been exercised directly with the release app after its Default exemption was removed.
- The Python 3.14 Windows full suite passed 7,753 tests with 41 platform-dependent skips at base 92cb690f; the run on the subsequently rebased base b8ffec4d is pending. Linux container checks covered the 12 release-event tests and 13 bot-merge tests, not the full SQLCipher suite.

## Workflow follow-up

- Archive only after all tasks are complete and acceptance criteria have evidence.
