# Proposal

## Why

Intervals Coach has implemented behavior and regression tests across many domains,
but no consolidated OpenSpec baseline. Backfill that baseline from the current
implementation so later changes can identify the contracts they affect.

## What Changes

- Add capability specifications for existing behavior, with observable scenarios
  and implementation/test evidence.
- Add a coverage ledger linking domains, HTTP routes, Coach tools and browser
  modules to the baseline, with explicit evidence limits and unresolved gaps.
- Preserve application behavior and all existing data; newly `ADDED` requirements
  mean newly documented contracts, not new features.
- Validate the specifications, review their evidence, sync the baseline into
  `openspec/specs/` and archive the completed change under `openspec/changes/archive/`.

## Capabilities

### New Capabilities

- `coach-conversation`: stored messages, asynchronous turns, streaming and recovery.
- `coach-context-and-provenance`: authoritative local context and source labels.
- `coach-tool-authority`: tool capabilities, write gates and durable receipts.
- `athlete-profile-and-checkins`: profile, local dates and athlete check-ins.
- `competitions-and-seasons`: competition records, priorities and season context.
- `training-library`: reusable local workouts, explicit exports and guarded calendar repair.
- `training-plans-and-adaptation`: plans, scheduled units and approved adaptation.
- `change-history-and-undo`: local change records and guarded reversal.
- `model-selection-and-usage`: Responses configuration, selected options and usage.
- `sync-jobs-and-scheduling`: queued refreshes, scheduling, progress and recovery.
- `provider-connections`: provider configuration, connection lifecycle and status.
- `provider-normalization-and-provenance`: canonical vocabulary, units and sources.
- `activity-ingestion-and-storage`: provider identity, canonical activity persistence.
- `activity-analysis-and-feedback`: activity details, analysis and local feedback.
- `performance-and-readiness`: derived training, body and recovery projections.
- `external-calendars`: imported availability and public-event discovery.
- `weather-and-location`: location-scoped forecasts, freshness and failure states.
- `nutrition-diary-and-targets`: dated intake, nutrients and derived expenditure; no saved target workflow.
- `food-catalog-and-meal-library`: foods, products, reusable meals and portions.
- `nutrition-provider-sync`: explicit nutrition exports and conflict handling.
- `nutrition-photo-analysis`: bounded photo interpretation and provenance.
- `web-pwa-and-accessibility`: mobile shell, installation, offline assets and access.
- `view-refresh-and-client-state`: view reads, device snapshots and refresh races.
- `voice-and-notifications`: opt-in recording, transcription and notifications.
- `authentication-and-http`: sessions, CSRF, rate limits and HTTP error contracts.
- `encrypted-storage-and-migrations`: SQLCipher, transactions and supported upgrades.
- `backup-restore-and-privacy`: consistent exports, validated restores and erasure.
- `runtime-and-configuration`: secure startup, maintenance and bounded state events.
- `diagnostics-and-observability`: redacted logs, reports and technical captures.
- `build-release-and-deployment`: reproducible builds, protected delivery and runtime.

### Modified Capabilities

None. The initial OpenSpec inventory is empty.

## Impact

Documentation only: OpenSpec Markdown/YAML, coverage artifacts and README routing.
The inspected application snapshot is `b8c911c9dda83a7920171916ace32681c0c38ba0`
(version 1.13.22, schema v13); local OpenSpec setup is checkpointed separately at
`6f942515a`. Each capability is a cohesive backfill slice with its own exclusions
and evidence. No application code, schema, provider account, athlete data, remote
calendar/workout, release, deployment or protected branch is changed.
