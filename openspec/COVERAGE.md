# Application specification baseline

## Snapshot and meaning

The baseline describes the implemented Intervals Coach application at
`b8c911c9dda83a7920171916ace32681c0c38ba0` (APP_VERSION 1.13.22, database schema
v13). OpenSpec CLI/skill setup is the separate documentation/tooling checkpoint
`6f942515a`. The backfill changes documentation only. Subsequent application
changes must update affected requirements, scenarios and their evidence.

This is a capability baseline, not a claim that every source line was audited or
every scenario was executed. Requirement evidence names the current implementation
and inspected regression tests. Test execution is recorded separately below.
SHALL requirements describe behavior supported by the inspected implementation;
unverified desired changes and supported discrepancies do not become accepted
requirements merely because a document is format-valid.

The [surface inventory](coverage.json) maps tracked application/operational paths,
HTTP path literals/regular expressions (including provider registry routes), and
literal Coach tool declarations to capability owners. A mapped row establishes
ownership/discovery, not independent semantic validation of every helper. Dynamic
HTTP method/query/body validation remains in the cited route owners; the inventory
is not an OpenAPI document. Historical review documents, skills, test-fixture
corpora and generated/local state are evidence or development material rather
than additional athlete-facing capabilities.

The reviewed baseline contains 30 capabilities, 272 requirements and 757 scenarios.
The executable Coach catalog has 49 canonical schemas, 52 dialogue schemas,
53 union tool names and 17 read-only tools. The [complete tool map](COACH_TOOLS.md)
links each to specific requirement names and existing test evidence. The parent
reconstructed the catalog with checked-in constants without importing server
configuration or contacting providers.

## Domain coverage

| Surface / implementation owner | Capability contracts |
| --- | --- |
| `backend/coach/` | Conversation, context/provenance, tool authority, model/options/usage |
| `backend/athlete/` | Profile, check-ins, athlete-local dates, competitions |
| `backend/planning/` | Competitions/seasons, local training library, scheduled plans and adaptation |
| `backend/history/`, `backend/change_history.py` | Change history, receipts and guarded undo |
| `backend/sync/` | Jobs/scheduling/recovery, provider refreshes and export interfaces |
| `backend/providers/`, `backend/provider_credentials.py` | Connections, transport boundaries and normalization/provenance |
| `backend/canonical/` | Vocabulary, records, source rules and canonical activity storage |
| `backend/activities/` | Ingestion, reads, workout text and local feedback |
| `backend/performance/` | Activity analysis, training records, load, body, endurance and recovery projections |
| `backend/calendar/` | External calendar import, recurrence and public-event discovery |
| `backend/weather/` | Location, forecasts, freshness, cache/error behavior |
| `backend/nutrition/` | Diary/targets, foods/products/meal library, provider exports and photo analysis |
| `backend/db/` | Encrypted persistence, transactions, supported v9-v13 upgrades and domain repositories |
| `backend/backup/`, `backend/privacy.py` | Consistent export, validated restore, recovery and explicit erasure |
| `backend/runtime/`, `server.py`, `backend/config.py`, `backend/settings.py` | Composition, secure startup, runtime settings, maintenance, events and shutdown |
| `backend/diagnostics/`, `backend/observability.py` | Redacted technical reports/logs, captures and retention/cache boundaries |
| `backend/http_api/`, `backend/errors.py`, `backend/pagination.py` | Auth/session/CSRF/rate/body/error contracts; concrete routes map to domain specs |
| `public/` | Responsive shell, navigation/forms, PWA/offline/update, device state, scoped refresh, domain views, voice/notifications |
| `.github/`, `Dockerfile`, dependency manifests, `scripts/`, `tools/`, `site/` | Build/quality/source/release/publication contracts and separate static marketing deployment |

## Review and validation evidence

- Parent plus three isolated implementation workers use user-selected
  `codex / gpt-6.1-sol / reasoningEffort=xhigh / serviceTier=default`.
  The parent alone accepts and integrates worker patches. An independent L3
  critique of the frozen combined candidate `ef4c29edc` found two documentation
  errors: TL2 omitted the linked-template deletion refusal, and TL10 delegated
  remote calendar repair to capabilities that did not specify those effects.
  Parent source review confirmed both. The adopted two-file revision qualifies
  TL2 and adds TL11-TL15 for identity-bound calendar sync/removal, repair,
  verification, local-edit recovery and partial batch outcomes. A focused
  independent re-review checks their resolution before closure.
- 128 existing platform regressions passed in the SQLCipher runtime image with
  `--network none`, a read-only tests mount and temporary `/tmp`/`/data`.
  Selected modules: `test_db_migrations`, `test_database_restore_validation`,
  `test_database_restore_service`, `test_database_backup`,
  `test_privacy_delete_confirmation`, `test_http_post_maintenance_reauth`,
  `test_http_auth_post`, `test_session_auth_read_path`, `test_runtime_maintenance`,
  `test_runtime_events`, `test_config`, `test_diagnostic_report`,
  `test_diagnostic_logs`, `test_http_database_busy`.
- 45 existing `test_ci_contracts.py` tests passed locally using synthetic source
  repositories and checked-in workflow contracts. They do not prove current
  hosted CI, ruleset state, signing or publication.
- Another 27 selected SQLCipher integration regressions passed with the same
  network-disabled temporary container boundary. They exercise JSON/body limits,
  CSRF/cookies, provider-auth versus session errors, state-event gaps, static path
  traversal/security headers, privacy ZIP/export bounds, deletion rollback and
  remote outcome reporting, session-scrubbing restore, nested redaction,
  diagnostic-cache invalidation and database transaction/resource behavior.
- The nutrition/frontend worker ran 114 Node regressions across view-refresh,
  nutrition history/lookup, Markdown tables, keyboard behavior, notifications,
  client startup/cache, provider forms, login errors, unknown write outcomes,
  reload coalescing and analysis-report caching. It also ran 22 mocked/temp-state
  Python cases for nutrition photos, audio/route validation, diary and component
  snapshots, nutrition export approval/races, mirror fallback and food lookups.
  All passed. The parent reviewed the frozen seven-file patch and verified 413
  cited path/symbol references before adopting it.
- The provider/sync worker ran 149 focused mocked Python tests across the daily
  scheduler, Wahoo mapping/connection, session analysis, weather cache, calendar
  parser/transport, canonical ingest, personal recovery, persisted automatic
  metric-export consent and stale Wahoo export selection. All passed. The parent
  reviewed all eight frozen deltas and verified 424 source/test references.
- The Coach/training worker recorded 180 passing Python executions and 33 Node
  tests for write gating, turn/replay/response preparation, check-ins, history
  undo, plan artifacts, settings/usage, seasons, proposals and client queue/action
  behavior. Its first package-style season invocation had one helper-import
  failure; the correct repository discovery invocation passed all 17 season
  tests. The parent reviewed all nine frozen deltas and verified 666 references.
- The parent reran 41 Node cases from the accepted frontend safety/refresh,
  notification and credential-form groups after adoption. These are subset
  repetitions, not additional unique test coverage. Counts above are execution
  evidence per batch; overlapping modules are not summed as unique tests.
- The isolated training-library revision worker passed 49 existing mocked
  tests: the planned-calendar and selected-sync modules, three library lifecycle
  cases and the executor repair-routing case. The parent independently reran
  the 34 planned-calendar and 11 selected-sync cases; all 45 passed. These are
  repeated executions, not additional unique coverage. Source-only branches and
  the lack of live remote compare-and-swap remain explicit in TL11-TL15.
- Strict OpenSpec validation checks syntax/structure. Source/test-reference
  checks verify cited paths and named symbols exist. These checks do not prove
  every assertion or substitute for product conformance tests.
- The frozen combined candidate passes strict validation for all 30 main specs
  and the active change. Main/delta content is identical after the documented
  heading transformation. Before the revision, the parent checked 1,770 evidence
  references, local links and requirement/scenario structure; no unresolved
  reference errors remained. The revision adds 59 checked named references.
  All seven existing AI documentation contract tests passed. Compile checks,
  the local CLI wrapper syntax check and whitespace checks also passed.

## Evidence limits and follow-up policy

- No real athlete accounts/data, credentials, database contents, token stores,
  recovery backups or production/browser sessions were inspected.
- No remote provider mutation, GitHub PR/push, release, image publication or
  deployment is part of this backfill.
- Live provider parity, all browser/viewport journeys, actual microphone/push
  permissions, all network failure modes, release publication and current hosted
  protection settings are not executed here. Relevant existing tests/source are
  cited; runtime coverage must not be inferred from their citations.
- No database schema or migration code changes. The focused encrypted migration
  checks above are supporting baseline evidence, not new migration delivery.
- Evidence is snapshot-specific. Exact models/providers, time windows, route
  lists and schema versions need rechecking when their owning code changes.
- Record a discovered implementation/intent discrepancy with its source and
  bounded reproducer or test evidence. Keep unresolved intent outside normative
  requirements; fix application defects only in a separately authorized change.

## Explicitly bounded or absent capabilities

- `nutrition-diary-and-targets`: no durable calorie/macro target or adaptive
  nutrition-target workflow was found. The running-day energy projection is a
  separately labelled derived expenditure estimate, not a prescribed target.
- `nutrition-provider-sync`: approval validates the local selected dates,
  revisions, totals and digests, and an in-flight local edit remains pending.
  The implementation does not read/compare independently edited Intervals
  wellness values before its PUT. This baseline does not promise remote
  compare-and-swap protection (`backend/nutrition/sync.py::sync_day`).
- `voice-and-notifications`: notifications come from eligible state loaded by
  the current client. There is no server push-subscription route, guaranteed
  closed-app delivery or cross-tab/restart delivery deduplication. Microphone,
  permission-denial and notificationclick branches include source-only evidence.
- Photo candidates and labels are not saved meals/products until their explicit
  durable action. Some size/signature/permission branches are source-inspected;
  cited adjacent tests do not mean every boundary was executed here.
- Direct training connections are Intervals.icu, Garmin and Wahoo. Polar, COROS,
  Suunto, Strava and Zwift recording-origin text does not establish a direct
  connection/adapter. Wahoo imports FIT details automatically after summaries;
  its descriptor does not offer on-demand activity-details or historical-backfill
  jobs. Stored public-event candidate/source readers do not establish a current
  candidate-import API. See provider/ingestion/calendar capability evidence.
- Canonical and compatibility normalization/current consumers differ in some
  FTP-selection, maximum-HR (canonical 250 versus legacy 260), unit/alias and
  unset-zero branches. Examples are `tests/test_source_policy.py::test_garmin_ftp_history_is_observed_but_legacy_ignores_it`,
  `tests/test_garmin_health_parity.py::test_max_hr_above_the_canonical_bound_is_legacy_only`,
  and `tests/test_intervals_mapping_parity.py::test_zero_athlete_lthr_is_unset_where_legacy_reads_zero`.
  Source priority, current composition and preferred display are separate
  contracts; this baseline does not promise universal legacy/canonical parity.
- Wahoo canonical ingest, markers and coverage share one transaction. Garmin
  payload/canonical state commits before some equipment/metadata/cursor writes.
  Distributed remote writes cannot be rolled back by a later failed local
  transaction. No lifecycle-wide or cross-provider atomicity is promised.
- Weather base completeness is structural and can accept empty sections; archived
  forecast history is not observed weather. Canonical detail recomputation and
  compatibility cached-analysis suppression have distinct stale-data behavior.
- Background Coach turns freeze model/thinking, while service tier is currently
  resolved again from settings. Approval payload hashes are checked when supplied;
  the browser supplies them, but the low-level execution API does not require
  every caller to provide one. Usage records daily request/token totals, not a
  per-model monetary ledger or globally exactly-once billing accounting.

## Confirmed discrepancies and unresolved intent

These observations are kept outside accepted SHALL behavior; this documentation
change does not fix them or decide their product intent.

| ID | Evidence and observed boundary | Bounded follow-up |
| --- | --- | --- |
| G1 | `backend/coach/capabilities.py` classifies `resolve_training_sync_conflict` conditionally, but `backend/coach/write_gate.py::TOOL_DOMAIN` places it unconditionally in remote Intervals scope. A worker's synthetic local keep-local probe returned `remote_not_requested`; parent source review confirmed the gate. | Check local keep-local/adopt-remote and actual read-retry/push variants separately before changing authorization. Specs promise only paths that reach the authorized conflict service. |
| G2 | `backend/planning/library_plan_service.py::WorkoutLibraryPlanService._library_plan_conflicts` remembers only the last template per date. A worker's synthetic A/B/A selection returned no duplicate conflict; the existing test covers adjacent identical selections. Full apply consequences were not rerun. | Reproduce A/B/A through the complete apply transaction and retain all relevant template/date pairs if duplicate selection is prohibited. The baseline only asserts the supported two-identical-selection rejection. |
| G3 | `backend/coach/dialogue.py::INSTRUCTIONS` says one workout per date, while `tests/test_planning_change_validation.py::test_duplicate_final_dates_are_allowed_for_untimed_or_non_overlapping_workouts` and planning code allow valid same-day sessions. | Reconcile prompt wording against the implemented overlap policy; the specs describe that policy. |
| G4 | Existing `docs/coach-tool-coverage.md` prose has older tool/count figures, and the `read_coach_context` schema describes unlocking tools while current structured turns offer their permitted catalog initially. The executable catalog and new tool map are current for this snapshot. | Update the older prose/schema descriptions in a focused maintenance change; do not invent an unlock behavior in the baseline. |
| G5 | `CoachIntervalsContextService.project` labels an activity aggregate Intervals while input ports can carry canonical rows. A complete mixed-origin label audit was not performed. | Trace mixed-provider aggregate source labels through context consumers; no blanket all-labels-correct claim is made here. |

These are described implementation boundaries and evidence gaps, not features
added by the backfill or automatically classified defects. Their future product
intent must be decided separately before changing application behavior.
