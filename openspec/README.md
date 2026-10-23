# Intervals Coach behavior specifications

This baseline backfills the existing application at
`b8c911c9dda83a7920171916ace32681c0c38ba0` (version 1.13.22, schema v13).
The 30 capabilities contain 272 observable requirements and 757 scenarios.
Each requirement cites current code and existing tests; citations alone do not
mean every scenario was executed. Read the [coverage and evidence ledger](COVERAGE.md)
for executed checks, boundaries, discrepancies and source identity.

Use these contracts alongside current source, tests and repository instructions.
When behavior changes, update the affected requirement/scenarios and evidence in
the same change. Specifications do not authorize athlete-data mutations or remote
writes. [Local CLI and maintenance instructions](../README.md#optional-local-openspec)
remain in the repository README.

## Capability index

| Capability | Contract |
| --- | --- |
| [coach-conversation](specs/coach-conversation/spec.md) | Stored dialogue, asynchronous turns, streaming, recovery and cancellation |
| [coach-context-and-provenance](specs/coach-context-and-provenance/spec.md) | Local authority, bounded context, source labels and current-data reads |
| [coach-tool-authority](specs/coach-tool-authority/spec.md) | Tool catalog, athlete-message authority, impact checks, approvals and receipts |
| [athlete-profile-and-checkins](specs/athlete-profile-and-checkins/spec.md) | Profile, athlete-local days, check-ins, feedback and equipment |
| [competitions-and-seasons](specs/competitions-and-seasons/spec.md) | Target events, competition sync, phases and observed preparation |
| [training-library](specs/training-library/spec.md) | Reusable workouts, scheduled copies, guarded explicit calendar exports and repair |
| [training-plans-and-adaptation](specs/training-plans-and-adaptation/spec.md) | Drafts, local plan transactions, patches and approved adaptation |
| [change-history-and-undo](specs/change-history-and-undo/spec.md) | Bounded local history, optimistic restore and complete-turn undo |
| [model-selection-and-usage](specs/model-selection-and-usage/spec.md) | Selected model/thinking/speed, Responses lifecycle and daily token counts |
| [sync-jobs-and-scheduling](specs/sync-jobs-and-scheduling/spec.md) | Queue, provider cadence/windows, retries and historical work |
| [provider-connections](specs/provider-connections/spec.md) | Intervals, Garmin, Wahoo, credential lifecycle and explicit metric/library export |
| [provider-normalization-and-provenance](specs/provider-normalization-and-provenance/spec.md) | Canonical fields/units/dates, per-metric source rules and reprojection |
| [activity-ingestion-and-storage](specs/activity-ingestion-and-storage/spec.md) | Provider identity, session copies, detail acquisition and deletion |
| [activity-analysis-and-feedback](specs/activity-analysis-and-feedback/spec.md) | Measured streams/laps/zones, conservative analysis and local feedback |
| [performance-and-readiness](specs/performance-and-readiness/spec.md) | Load/reports/history, recovery baselines, body and local scenarios |
| [external-calendars](specs/external-calendars/spec.md) | Safe iCalendar import, recurrence/constraints and read-only projections |
| [weather-and-location](specs/weather-and-location/spec.md) | Forecast/air/pollen sources, query-keyed caches and advisory windows |
| [nutrition-diary-and-targets](specs/nutrition-diary-and-targets/spec.md) | Local consumption, nutrient completeness, energy and body history |
| [food-catalog-and-meal-library](specs/food-catalog-and-meal-library/spec.md) | Food lookup/mirrors, products, portions and frozen reusable meals |
| [nutrition-provider-sync](specs/nutrition-provider-sync/spec.md) | Explicit dated export, local revision safety and scoped read refresh |
| [nutrition-photo-analysis](specs/nutrition-photo-analysis/spec.md) | Transient label candidates, bounded images and barcode capture |
| [web-pwa-and-accessibility](specs/web-pwa-and-accessibility/spec.md) | Mobile shell, safe content, offline assets and accessible interactions |
| [view-refresh-and-client-state](specs/view-refresh-and-client-state/spec.md) | Device reads, session epochs, scoped refresh and background updates |
| [voice-and-notifications](specs/voice-and-notifications/spec.md) | Optional transient audio and privacy-conscious client notifications |
| [authentication-and-http](specs/authentication-and-http/spec.md) | Sessions, CSRF, rate/body limits and safe HTTP contracts |
| [encrypted-storage-and-migrations](specs/encrypted-storage-and-migrations/spec.md) | SQLCipher, atomic transactions and supported v9-v13 upgrades |
| [backup-restore-and-privacy](specs/backup-restore-and-privacy/spec.md) | Consistent exports, validated restore, recovery and explicit erasure |
| [runtime-and-configuration](specs/runtime-and-configuration/spec.md) | Secure composition/startup, maintenance, readiness/events and shutdown |
| [diagnostics-and-observability](specs/diagnostics-and-observability/spec.md) | Redacted bounded capture, local reports, logs and safe correlation |
| [build-release-and-deployment](specs/build-release-and-deployment/spec.md) | Pinned standalone runtime, protected immutable delivery and signed digests |

## Coverage and changes

- [Coverage, executed checks and explicit gaps](COVERAGE.md)
- [Complete Coach tool-to-requirement map](COACH_TOOLS.md)
- [Machine-readable source/HTTP/tool ownership inventory](coverage.json)
- Change artifacts live under `changes/`; completed changes move to
  `changes/archive/` after reviewed specs are synchronized. The archived baseline
  retains its proposal, design, task/evidence state and deltas.

The baseline is comprehensive at capability/surface level. It is not a line-by-line
application audit, a guarantee of live provider behavior or an executed full
browser/permission matrix. Known implementation differences and uncertain intent
are kept in the coverage ledger rather than invented as desired requirements.
