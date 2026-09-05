# Intervals Coach application review checklist

Use this as a coverage map, not as a request to manufacture one finding per section. Read the current code and instructions because filenames and behavior can evolve.

## 1. Product invariants and architecture

- Confirm the standalone, single-athlete, trusted-LAN/private-VPN threat model is consistent across code, Docker, README, and deployment examples; port 8090 must not be presented as a public edge.
- Map responsibilities across `server.py`, `backend/`, `public/`, persistence, background workers, providers, OpenAI, and CI. Look for split or duplicated business rules and obsolete compatibility paths.
- Verify that confirmed local profile and competition records are authoritative and OpenAI conversation state provides dialogue continuity only.
- Check that external provider/calendar text is always treated as data, never executable instructions.

## 2. Authentication, sessions, CSRF, and HTTP boundary

- Verify `APP_PASSWORD` is mandatory, at least 12 characters, compared safely, and remains the SQLCipher key without insecure development fallbacks.
- Trace login, logout, expiry, sliding activity, cache invalidation, restore invalidation, rate limiting, concurrent sessions, cookie flags, trusted HTTPS-proxy configuration, and authentication on every non-public route.
- Verify CSRF on every state-changing method and streaming/background mutation path; check session binding of Coach proposals, receipts, jobs, and action tokens.
- Review request body and upload bounds, content parsing, duplicate/unknown fields, numeric and date validation, response headers, error redaction, route normalization, and static-file traversal/symlink handling.
- Check maintenance/readiness/health endpoints expose no sensitive state and fail safely during restore or unavailable durable storage.

## 3. Secrets, privacy, and untrusted content

- Trace credentials and sensitive URLs from environment loading through clients and errors. They must not reach logs, diagnostics, coach context, frontend state, exports not intended to include them, notifications, test artifacts, or source control.
- Review structured logging and exception paths for raw upstream bodies, request headers, tokens, athlete content, SQL parameters, voice data, and calendar feed URLs.
- Verify diagnostics are useful but minimized/redacted and capture paths cannot leak or overwrite arbitrary files.
- Review privacy export/delete scope against every durable table and remote conversation state; make partial remote deletion failures visible without lying about local completion.
- Check retention, cleanup, temporary files, browser storage, caches, screenshots/traces, and backup handling. Voice audio must remain short-lived and unpersisted.
- Inspect all HTML/Markdown/URL rendering sinks for XSS, unsafe schemes, attribute injection, reverse tabnabbing, and untrusted CSS/markup.

## 4. SQLCipher persistence and durable athlete data

- Confirm startup fails closed without SQLCipher and never silently creates or opens plaintext SQLite. Review key use without revealing the key.
- Inventory all tables and durable records: profile/settings, competitions/tombstones, provider snapshots/cursors/status, workouts/plans/check-ins/feedback/adjustments, Coach commands/actions/conversation, sessions, usage, public calendars, change history, and backups.
- Review initialization and schema evolution for fresh and existing databases, transaction boundaries, foreign/uniqueness constraints, indexes, type/JSON validation, and crash consistency.
- Check multi-threaded connection ownership, writer serialization, lock scope, atomic read-modify-write operations, and rollback behavior.
- Verify updates preserve last-known-good snapshots and locally authoritative records on provider, parsing, or commit failure.
- Review deletion/tombstone semantics, idempotency, orphan cleanup, pagination state, and data retention without accidental loss.

## 5. Backup, restore, and recovery

- Verify backups are transactionally consistent, encrypted/sensitive, bounded, and never logged or placed in images.
- Trace restore validation: format, size, SQLCipher integrity, complete current schema, migration compatibility, path safety, atomic replacement, rollback/recovery backup, maintenance gate, worker quiescence, and session invalidation.
- Exercise or inspect failure points before, during, and after replacement. A failed restore must retain a recoverable valid database and must not let background writers use stale handles.
- Check recovery documentation matches the actual workflow and does not suggest deleting `/data` or bypassing encryption.

## 6. Provider clients and network security

- For Intervals.icu, Garmin, iCalendar, weather, GitHub, and OpenAI, inspect URL construction, TLS expectations, authentication placement, timeouts, size limits, content types, status handling, pagination, rate limiting, retries/backoff, cancellation, and error classification.
- Ensure redirects cannot bypass host/scheme checks or expose credentials. Fully review calendar SSRF and DNS-rebinding defenses, including IPv4/IPv6, encoded/local addresses, resolution changes, and redirect targets.
- Validate upstream schemas defensively. Partial, malformed, duplicated, out-of-order, or unexpectedly large data must not corrupt current state.
- Confirm provider error messages and freshness/status values are accurate, source-labelled, durable where needed, and do not erase the last good data.
- Review dependency APIs against pinned versions and make unsupported assumptions visible.

## 7. Synchronization and concurrency

- Trace startup sync, daily automatic sync, named/manual sync, full resync, status polling/events, and restart recovery.
- Check single-flight behavior, lock ordering, queue bounds, worker lifetime, SQLite interaction, duplicate requests, cancellation, stale jobs, and process restarts.
- Validate cursor/window advancement only after durable success. Review partial pages, reconciliation, tombstones, `remote_missing`, duplicate identities, and conflict resolution.
- Prove retries and repeated jobs are idempotent. Remote creates/updates/deletes must not duplicate or silently lose local changes.
- Ensure a refresh requested by an explicit current-data prompt uses the supported sync path, while ordinary chat does not refresh every provider unconditionally.
- Check polling and status state machines cannot report success early, remain permanently busy, or hide partial/provider-specific failure.

## 8. Coach context, provenance, and training correctness

- Trace every context field to its source and freshness. Preserve labels for Intervals, Garmin, derived metrics, local feedback, and AI estimates; do not present estimates or stale values as measured/current.
- Verify confirmed local profile/competitions and current planning state override dialogue memory or conflicting provider prose.
- Review sanitization and delimiting of external text against prompt injection. Provider content, calendar entries, stored chat, and workout descriptions must not gain tool authority.
- Check context projection for token bounds, deterministic ordering, deduplication, and incremental value. Compact only the Coach projection: full Garmin data and the Intervals snapshot remain intact; recent activity projection keeps the five newest per sport when that is the current requirement.
- Verify training dates, recent load, readiness, sleep, fatigue, illness/pain, availability, weather, and competition priorities are interpreted with freshness and uncertainty. Flag unsafe certainty or internally inconsistent advice paths, not mere stylistic preferences.
- Review token/cost accounting, model and thinking-level selection, configured-model exposure, output limits, and daily timezone boundaries.

## 9. OpenAI Responses lifecycle and Coach tools

- Trace conversation creation/resume/reset/recovery, background responses, streaming parsing, polling, cancellation, timeouts, size bounds, incomplete/error states, and interrupted browser requests.
- Check malformed or repeated tool calls, unknown tools, invalid JSON/schema values, hallucinated identifiers, stale conversation state, retries, and partial multi-tool execution.
- Verify authorization comes from the athlete's current explicit request, not model output or external content. Hypothetical, explanatory, status-only, and automatic check-in flows must remain read-only.
- Apply the current product boundary precisely: unambiguous authorized local planning/change actions and named sync requests should execute as designed, while adaptive replanning still requires its explicit preview/apply boundary and remote workout synchronization remains explicit.
- Ensure local and remote mutations are distinguishable, scoped, idempotent, auditable, bound to the initiating session/turn, and recoverable after follow-up failure.
- Review every declared tool against its dispatcher, validator, implementation, response synthesis, and tests; also find callable operations missing from schemas or dead schemas missing implementations.

## 10. Planning, workouts, competitions, and calendars

- Verify Coach-created workouts first become local training-library/planned records and are never implicitly written to Intervals.icu.
- Trace create/edit/move/archive/delete, bulk actions, sync/reconciliation, duplicate handling, IDs, ownership, source and sync status through the canonical read model and UI.
- Check explicit remote sync, remote deletion protections, retry reconciliation, partial batches, and preservation of races, competitions, foreign events, and past events.
- Review adaptive preview hashes/versions, stale-target detection, atomic apply, repeat apply, missing targets, and concurrent user/provider changes.
- Verify local competitions and tombstones are not silently overwritten by provider refresh; review identity matches, merge/adopt conflicts, time windows, priority, and race-goal use.
- Review public/external calendar ingestion, recurrence expansion bounds, timezone handling, last-good state, scheduling constraints, and non-training-event treatment.

## 11. Dates, timezones, units, and numeric edge cases

- Trace date-only values separately from timestamps through Python, SQLite, JSON, and JavaScript. Test profile timezone, UTC conversion, DST transitions, midnight, month/year boundaries, and unavailable/invalid timezone data.
- Verify daily sync, check-ins, usage budgets, retention, "today", training horizon, competition windows, and weather windows share intentional timezone semantics.
- Review duration, distance, pace, speed, power, heart rate, load, scores, sentinel values, nulls, zero, negatives, rounding, and unit conversion. Guard division by zero and nonsensical-but-parseable provider values.

## 12. Frontend state and API contracts

- Map every UI action to its API method, authentication/CSRF handling, loading/error/success state, retry behavior, and durable result. Compare request/response shapes with backend validators.
- Review overlapping bootstrap, polling, navigation, streaming, sync, cancel, edit, and save operations for stale response overwrite, duplicate handlers, lost edits, and misleading optimistic state.
- Verify safe Markdown/text rendering and all DOM sinks. No secrets or durable authority may live in browser storage or URLs.
- Check mobile-first layouts at supported viewports, focus/keyboard order, dialogs, reduced motion, touch targets, contrast, semantic names, live regions, and axe findings. Preserve Enter-to-send, Shift+Enter newline, and editable voice transcripts.
- Review unsupported microphone/notification/browser paths, permission denial, secure-context requirements, cancellation, and cleanup.
- Ensure user-visible status distinguishes local vs remote, fresh vs stale/partial/error, and pending vs completed mutations.

## 13. PWA, service worker, and offline behavior

- Compare every referenced frontend asset, query version, cache name, and precache entry. Installed clients must receive changed assets without a mixed-version shell.
- Verify API/auth/private responses are not cached; inspect cache keys, scope, update activation, offline fallback, failed fetches, navigation, and old-cache cleanup.
- Check manifest metadata, icons, start URL, display mode, install/update UX, notification click handling, and HTTPS expectations.
- Review failure modes when an old tab, new service worker, and changed API contract coexist.

## 14. Reliability, performance, and observability

- Inspect broad exceptions, silent fallbacks, partial commits, unbounded collections, payload copies, large JSON serialization, recursive/repeated work, N+1 queries, and blocking provider/OpenAI calls on request threads.
- Review global locks and conditions for deadlocks, starvation, long critical sections, inconsistent order, lost wakeups, and shared mutable caches. Confirm queue, stream, history, response, and thread counts are bounded.
- Check shutdown/restart behavior, abandoned jobs, stale in-memory state, and health/readiness accuracy.
- Evaluate Coach context size and end-to-end request latency with measurement before claiming a performance gain. Do not shrink authoritative source snapshots as an optimization.
- Verify logs/status/diagnostics support root-cause analysis without exposing private content; error states should retain safe reason codes and actionable timing/freshness data.

## 15. Tests and verification quality

- Map tests to every critical flow and negative boundary, not just functions. Inspect assertions for false positives, excessive mocking, shared state, order dependence, timing flakes, and skipped branches.
- Ensure all tests use temporary databases/data directories and fake provider/OpenAI inputs and cannot load the root `.env` or real tokens.
- Review security regression coverage for password/session/CSRF, SQLCipher fail-closed, body/path bounds, calendar SSRF, log redaction, backup/restore, prompt injection/tool authorization, and explicit remote writes.
- Review state-machine and concurrency tests for sync, background Coach jobs, streaming/cancel, retries, partial failures, idempotency, adaptive apply, and restore maintenance.
- Compare backend API and frontend behavior coverage. Inspect Playwright login, PWA update, viewports, accessibility, input behavior, notifications/microphone fallbacks, and meaningful failure artifacts.
- Run syntax/unit checks and, where feasible, isolated Docker and Playwright suites. Record unexecuted suites; do not infer they pass.

## 16. Dependencies, container, and runtime hardening

- Review pinned Python/npm dependencies and lock consistency, necessity, supported Python 3.13/3.14 behavior, vulnerability exposure, license compatibility, and update automation.
- Inspect Docker build context, `.dockerignore`, base-image digest, non-root user, writable paths, read-only compatibility, capabilities, resource bounds, healthcheck, `/data` ownership, and absence of runtime data/secrets in layers.
- Confirm Garmin login uses the persistent token mount safely and documentation never encourages embedding credentials or tokens in images/commands that leak them.
- Review local/Unraid examples for persistent bind mounts, safe container recreation, trusted network exposure, reverse-proxy HTTPS, and voice secure-context behavior.

## 17. CI/CD, GitHub Actions, and releases

- Inspect all triggers, expressions, permissions, concurrency, fork/bot handling, checkout refs, credential persistence, shell injection, artifact contents/retention, cache poisoning, and third-party action pinning.
- Verify protected `main` is changed through PRs, release automation cannot overwrite existing refs, target/source commits are validated, and bot loops/races are bounded.
- Trace `APP_VERSION` from source through version PR, tests, tag, release, image labels/tags, SBOM, provenance, signing, and publication. Reject mismatched or stale source.
- Confirm required jobs aggregate failures correctly and cannot be skipped into success. Review native shards, SQLCipher container tests, quality baselines, browser matrices, and review-gate fail-closed behavior.
- Check Dependabot auto-merge and release-bot authority follow least privilege and cannot execute untrusted fork code with secrets.

## 18. Documentation and maintainability

- Compare README, `.env.example`, commands, defaults, API behavior, privacy promises, provider capabilities, PWA behavior, deployment guidance, and release process with implementation.
- Review naming, module boundaries, duplicated constants/schemas, dead code, unreachable UI, stale docs/handover artifacts, and the large `server.py`/frontend orchestration hotspots for concrete change risk.
- Note missing comments only where a non-obvious invariant or concurrency/security contract would otherwise be easy to violate.
- Separate refactoring opportunities from defects and give them lower priority unless they already create a concrete correctness or security failure.
