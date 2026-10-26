# Design

## Context

See proposal.md for motivation and the five capability deltas for observable requirements. Inspected base: `eed88ccef264501697e3c5e5d83bf173963b16ea`, schema v13. An independent L3 source review confirmed unused observation method/aggregation/details columns, provider-keyed feedback, snapshot zone readers and raw sleep-period traversal. The existing v13 fixture is already present and must be verified and frozen, never rewritten to fit a changed schema.

## Goals / Non-Goals

**Goals:** extend cohesive canonical owners, preserve every durable row, switch all consumers affected by Epic B, and prove encrypted upgrades from each supported schema. Keep a single additive v15 transition with stable observation natural keys and existing API compatibility.

**Non-Goals:** new scientific metrics, broad unrelated Epic A refactors, proprietary score recreation, implicit remote writes, live provider probes, releases or deployment. No local resting-energy derivation: the user's latest decision explicitly retains all domains as provider values.

## Decisions

### Typed metadata and compatibility

Reuse observation method/aggregation and validated JSON details for optional method version, fingerprint, period and bounded reference-range metadata where possible. Add columns only where a typed separate value requires them. Preserve natural keys because remote export links use them. Derived writes must have method/version/fingerprint; upgrade existing derived FORM through a deterministic local backfill or compatible read decoding so old rows remain readable during reprojection. Construction of new derived records still fails without complete metadata. Keep a single statistic per numeric kind/source series to avoid arbitrary daily selection.

Measurement context belongs in typed, validated provenance with explicit unknown model, firmware, algorithm, sensor, window and protocol; persist it in existing details JSON. Compute a deterministic context identity from allowlisted non-identifying fields. Never infer model/sensor from brand; never copy serials, owner ids or device-map keys. Preserve defaults for existing callers.

Numeric metric values remain numeric. Categorical provider status uses a separately validated categorical record/carrier instead of making arbitrary codes look like measurements. Any required categorical storage is part of the same v15 DDL. Retain structured, allowlisted provider-domain details needed by existing consumers without promoting arbitrary free text or unknown numeric scalars into scientific metrics. Explicit provider-estimate units and unknown semantics remain visible where no physical unit exists.

### Shared extension persistence

Add canonical sleep periods and zone configurations, plus categorical/provider-domain storage only as needed to represent existing retained domains faithfully. Use narrowly typed records and store functions; no general plugin registry or opaque snapshot substitute. New records retain provider/source identity, source record, retrieval timestamp and mapper version. Reprojection must be tied to the source record, retire stale outputs, preserve values while batches run and remain retry-safe. Extend the existing ingest plan/backfill machinery and registry, serializing mapper-version edits.

Sleep periods retain UTC bounds, ingest timezone and wake date, kind, reported duration and field-pair method for parity. Keep overlapping providers separate. Existing regularity keeps its grouping, ordering and current-profile-timezone interpretation; existing v1 inclusion/selection stays unchanged for equivalent inputs. No new SRI or silent longest-night heuristic.

The athlete's 2026-10-25 decision defines Garmin `NIGHT` as the provider's main daily sleep episode, including daytime main sleep for shift workers, rather than an assertion about clock time. Do not classify arbitrary periods by hour or duration. Naps are out of scope (athlete decision 2026-10-25): the canonical model has no nap kind and no nap collector.

Zone configurations retain sport/metric/environment, source, validity, threshold and normalized absolute boundaries where a threshold is available. Preserve provider percent-basis information for lossless conversion and missing-threshold behavior; do not invent absolute values. Keep pace configuration separate from activity-detail ZoneMetric to avoid rebuilding released detail tables. Effective local configuration valid on the requested date wins, then the existing provider order and supported defaults. Provider alternatives remain visible. Implement a small authenticated API and usable existing settings/editor integration; reuse receipt/history/undo machinery. No automatic CP/CS promotion.

Schema numbering: develop released schema v14 (Yazio food sources) while this change was open, so the canonical extensions are schema v15. The v14 shape is frozen like every released shape, and the v14 to v15 step adds the extension tables and the feedback session backfill; v9 to v13 databases pass through the v14 step first.

Zone lists keep the open top entry; effective zone settings drop it, as the snapshot sport settings did. Selection works per metric: local first, then providers in `ProviderId` order; an indoor configuration applies to indoor and virtual sessions before an environment-free one; the latest `valid_from` on the day wins. A sport without any canonical configuration keeps reading the snapshot sport settings, because Intervals.icu thresholds without a zone list have no zone configuration. Local edits cover ride, run and swim with an optional indoor scope: power and pace as percent of the threshold, heart rate as absolute bpm with LTHR and maximum. Each edit is a `zone_configuration` change-history entity keyed by its configuration key; history keeps no zone values in its public view, and removal needs a confirmed request. Coach current performance lists the zones in effect today per sport and metric as `training_zones`, with their source, so the Coach follows confirmed local zones (athlete decision 2026-10-25).

### Provider domains and vocabulary

Map the actual allowlisted fields used by existing consumers for status/load balance, acute/chronic load and ratio, tolerance, readiness history, endurance details/history, performance history, Body Battery, stress, resting energy, subjective wellness and gear. Keep provider-defined scores separate from physical measurements and locally derived statistics. Garmin's locally accumulated `performance_history` cache is mapped from its stored element records into the existing kinds (FTP, VO2max, weight, readiness, thresholds, race predictions) on each value's measurement day, so its consumers read those kinds. The 2026-10-25 decision assumed every cached day already existed canonically; the browser fixture showed that days cached before the upgrade do not, so the athlete decided on 2026-10-26 to map the stored rows (Garmin health mapper version 13, reprojected without refetch). Max heart rate keys are not mapped because they include an activity-derived fallback. Garmin acute load from the daily status and from the training-status history is one provider quantity: one ACUTE_LOAD row per day, written by the record projected last if the sections ever disagree (athlete decision 2026-10-25). Status codes are mapped only when Garmin sends a text code; numeric training-status codes have no verified meaning. Reported Body Battery level, charged and drained are different meanings. Intervals subjective stress is separate from Garmin physiological stress. Subjective imported wellness remains provider-reported with manual recording origin, separate from local check-ins. Unknown/unverified aliases stay missing; tests use synthetic fixtures grounded in existing collection/read contracts.

The bounded Garmin recovery extension uses existing daily summaries for physiological stress: nested `stress.avgLevel` or the existing flat fallback `averageStressLevel`, retaining established precedence, valid zero and the provider's date. Store one daily mean on the 0-100 provider scale; do not add a redundant stress endpoint or substitute subjective or sleep-score stress. Reject invalid values and preserve missing coverage. Populate the established last-night HRV RMSSD method and overnight window. The athlete explicitly accepts unknown device model, firmware and sensor when measurement-associated evidence is unavailable; preserve any other unavailable context as unknown too. Do not fetch device inventories or assign the primary/last-used device to historical measurements. No new schema transition is planned for these existing v15 carriers.

Document producer and consumer/retention purpose for every MetricKind and verify against code in a consistency test; no tautological manifest-only check. Keep existing stored kinds even if explicitly export-only and do not conflate provider LoadModel with local sRPE. Gear needs typed canonical projection and session links; existing local equipment state and assignments remain data, with deterministic read-time normalization where this avoids destructive rewriting.

### Feedback and reversible history

Add nullable `activity_feedback.session_id` referencing canonical sessions and an index. Backfill only exact existing local ids or unique matching provider records; ambiguous or unmatched rows remain intact and unresolved. Preserve original ids, contents and timestamps. Keep origin-session association separate from effective survivor resolution so unmerge is lossless. A confirmed merged group exposes one effective whole row by descending updated_at and stable original-id tiebreak, with conflict metadata. Heuristic proximity alone never merges feedback. New saves edit the effective row, preserving omitted fields. Explicit clear removes effective group feedback without reviving hidden older rows; history retains originals for undo. Feedback history is one `activity_feedback` entity per group key holding every stored row; its field bound is a 32-row group rather than the general 4000 characters, so full-length notes are never dropped. An athlete-triggered unmerge is deferred (athlete decision 2026-10-25): merges stay automatic and irreversible as before, and the kept origin session keeps a future unmerge lossless.

Merge, unmerge and alias deletion must preserve an explicit reversible association, not rely on a route that deletion clears. Add actual bounded unmerge/undo support where the current merge implementation lacks it. A deleted surviving session retains feedback/history but does not contribute completed-session load. Maintain API payload compatibility, known-activity Coach validation and athlete-started write gates. Extend feedback/zone history entities and undo restore handlers without reducing the existing 4000-character notes contract; use a lossless bounded audit representation rather than silent truncation.

### Migration and exports

Freeze v13 digest/version pairing before bumping to v14. One transaction adds new structures/columns and deterministic data backfills; no table rebuild or natural-key rewrite. Fresh DDL must produce the same normalized schema signature as all upgrade paths. Preserve frozen v9–v13 fixtures and reject unknown version/shape pairs before writes. Update export format and every explicit column/table selection together. Backup restore continues to validate integrity/foreign keys after migration.

## Risks / Trade-offs

- Existing derived FORM lacks metadata: backfill or deterministic legacy decode is required before strict construction can be enforced on reads.
- Feedback conflicts cannot be averaged: expose one deterministic effective row and preserve alternatives plus origin for undo.
- Long notes exceed the audit JSON scalar bound: preserve complete original notes through the owning history representation and test the maximum length.
- Schema signatures depend on ALTER-compatible DDL text: compare fresh, migrated and frozen fixtures in tests.
- Provider domain shapes vary: only mapped allowlisted fields enter canonical public carriers, with missing values and source labels preserved.
- Wide consumer changes share mapper registries: adopt foundational contracts first, then serialize mapper integration and inspect every patch in the parent.

## Migration Plan

Implement types/stores/schema/export first with populated v9–v13 fixtures, failure injection, restart and unknown-schema tests. Adopt and checkpoint the verified foundation before dependent worktrees start. Complete ingestion/reprojection and consumer cutovers, then feedback/zones/gear UI and undo. Run the complete native suite, syntax, Ruff/mypy, JS, affected Playwright and isolated SQLCipher/Docker checks. Review the exact pinned branch range independently before spec sync/archive and again under the PR gate. No release readiness claim is possible without the encrypted matrix.
