# Tasks

## 1. Typed canonical contracts and schema foundation

- [x] 1.1 Implement optional observation metadata, categorical/provider-domain carriers and explicit unknown measurement context with validated store/reader round trips, derived-write rejection, stable keys and context-change tests.
- [x] 1.2 Freeze outgoing v13 and implement one additive v14 migration (renumbered to v15 after develop released v14) plus sleep/zone/domain stores, lossless feedback session backfill and export updates; verify populated v9–v13 upgrades, rollback, restart, fresh-schema equality, unknown/newer rejection and backup compatibility with focused tests and compatibility documentation.

## 2. Ingestion and reprojection

- [x] 2.1 Populate provider-fixed method/context metadata and canonical sleep periods, zones and retained #1422 domains through the existing ingest/backfill flow; include daily-summary physiological stress, main-sleep NIGHT semantics and overnight RMSSD metadata with unknown unsupported hardware; verify idempotent reprojection, correction/retirement, partial failures, privacy and no provider refetch for stored-record reprojection with synthetic mapper and store tests.
- [x] 2.2 Make the metric vocabulary accountable to actual producers and consumers or documented export-only retention; verify the consistency check rejects an orphan and preserves stored observations and provider load-model semantics.

## 3. Performance, planning and equipment consumers

- [x] 3.1 Switch sleep regularity to canonical periods and verify exact sleep-regularity-v1 parity for equivalent midnight/DST/timezone/missing-night/provider-overlap cases, documenting method and coverage limits.
- [x] 3.2 Switch every retained provider-domain consumer in performance/history/recovery/nutrition/Coach to canonical inputs and gear links to session identity; verify canonical-only operation without provider views, source labels, date/zero/missing parity and no duplicate equipment usage.
- [x] 3.3 Switch calendar/plan/affected zone calculations to canonical configuration with parity tests; implement usable local zone editing, authentication, receipt/undo and persistence, update README and frontend cache versions together, and verify local authority and provider alternatives.

## 4. Canonical session feedback and history

- [x] 4.1 Implement one effective feedback per canonical session with conflict visibility and retained originals; verify existing API/Coach partial-edit behavior, two-provider deduplication, ambiguous references and no local/provider RPE conflation.
- [x] 4.2 Implement lossless merge (athlete-triggered unmerge deferred, decision 2026-10-25), alias/provider/survivor deletion, save/clear receipts and undo; verify full-length notes, exactly-once effective feedback, restart and encrypted backup/restore preserve every original and association.

## 5. Integrated acceptance and review

- [x] 5.1 Inspect the complete final diff and run required native unittest, compileall, repo-wide Ruff/mypy and JS checks plus affected Playwright/manual fixture flows; reconcile each issue criterion and strict OpenSpec validation against actual evidence.
- [x] 5.2 Build the final Docker image and prove the SQLCipher upgrade/rollback/restart matrix from v9–v13 and encrypted backup/restore with isolated temporary fixtures; record exact commands and any limits.
- [x] 5.3 Create task-only commits and independently review the complete pinned base/head range at maximum depth, resolve actionable findings and verify repairs before sync/archive.

## Workflow follow-up

- Synchronize deltas to main specs, inspect semantic agreement, archive only the completed change and verify strict OpenSpec/documentation checks.
- Execute the authorized PR workflow, including final rebased-range review, squash auto-merge and verified merge, preserving T3 linking/watch state.
- Run the mandatory closing retro and report behavior, validation, archive and actual merge state.
