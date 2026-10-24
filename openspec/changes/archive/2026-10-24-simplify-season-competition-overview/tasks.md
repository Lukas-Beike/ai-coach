# Tasks

## 1. Canonical competition overview

- [x] 1.1 Reconcile this plan with the current tree and scoped instructions, trace plan-state refresh/cache and season-loader callers, and record affected consumers; verify the chosen input exposes stable IDs and all existing saved event fields without live-data inspection.
- [x] 1.2 Render the competition overview from canonical local plan state through the plan-view owner and disconnect this segment's season-analysis request; add focused regression coverage proving events render without preparation/activity data and navigation remains valid at `#plan/season`.
- [x] 1.3 Implement initially collapsed event summaries, populated optional details, athlete-local upcoming/archive partitioning and undated fallback; add focused tests for today's event, equal-date ordering, missing/free-text/zero distance, unsupported sport detail, past-only and empty lists.

## 2. Interaction and presentation

- [x] 2.1 Rename visible and accessible Season labels to `Wettkämpfe`, remove analysis/scenario presentation and only verified obsolete UI helpers, and preserve expansion by event ID on refresh; verify absence of phase/weekly/scenario content and independence of event toggles with focused Node/browser tests.
- [x] 2.2 Preserve existing Coach access, compact provenance/local-change indications, safe text rendering and loading/stale/error/retry behavior; add synthetic browser coverage for untrusted text, failed refresh and a saved Coach edit appearing without implicit provider writes.
- [x] 2.3 Apply existing mobile layout tokens and native accessible disclosure controls, update README terminology, and bump index asset queries and service-worker cache/assets together; verify long names, keyboard focus, 200% text and dark/light layouts on small mobile and desktop fixture views.

## 3. Integration evidence

- [x] 3.1 Run affected Node regressions, `python -m unittest discover -s tests -v`, `python -m compileall -q server.py backend tests`, and rebuild with `docker build -t ai-coach:local .`; diagnose failures and record actual results without weakening guards.
- [x] 3.2 Run affected Playwright mobile-small and desktop projects against the disposable encrypted fixture and manually verify the changed event flow plus required login/PWA/offline/Markdown/chat-keyboard/microphone/notification checks where available; record limits and verify overview reads trigger neither scenario requests nor remote mutations.
- [x] 3.3 Inspect the complete final diff including additions/deletions, reconcile CS9–CS12 against evidence while preserving CS1–CS8, run `npm.cmd run openspec -- validate simplify-season-competition-overview --strict --no-interactive`, and complete the repository closing retro; verify no schema/live-data or out-of-scope status/CRUD changes entered the patch.
