# Proposal

## Why

The canonical model cannot yet represent sleep timing, measurement context, zone configuration, several provider domains or session-owned athlete feedback. These gaps keep affected reads tied to provider shapes and prevent reproducible future local metrics (#1408, #1417–#1423).

## What Changes

- Extend validated observations with method, aggregation, version, input fingerprint and observation period; support provider categorical values without inventing numbers. Require reproducible metadata on derived observations.
- Preserve explicit unknown device/model/protocol context without athlete-identifying serials; expose continuity changes through canonical reads.
- Ingest and reproject canonical sleep periods with UTC instants, timezone, wake-date assignment and night/unknown kind. Move existing sleep regularity to these inputs with method parity.
- Refine Garmin recovery collection against evidenced fields: daily-summary physiological stress, main-sleep NIGHT semantics and fixed overnight RMSSD metadata, retaining unknown unassociated hardware.
- Persist canonical per-sport zones and thresholds, preserve separately visible provider values, and allow authoritative local editing with undo. Calendar, plan and affected zone calculations read this configuration.
- Retain all #1422 domains as labelled provider values, including resting energy and training-load balance, with session-linked equipment. This explicit session decision supersedes the two derivations proposed in the issue comment.
- Resolve feedback to canonical sessions while preserving legacy feedback, history, API/Coach contracts, merge/unmerge and provider-deletion behavior. Count one effective session feedback once without losing conflicting historical records.
- Add vocabulary producer/consumer coverage and reproject stored provider records without network refetches. Preserve provider load-model semantics and keep local session-RPE methods out of LoadModel.
- Combine necessary schema changes into one versioned transition where practical, freezing v13 and proving populated upgrades from v9–v13, rollback, restart and encrypted backup/restore.

## Capabilities

### New Capabilities

None; extend the existing domain contracts.

### Modified Capabilities

- `provider-normalization-and-provenance`: reproducible typed metadata, canonical sleep, device context, zones and all retained provider domains.
- `activity-analysis-and-feedback`: canonical session feedback identity and lossless duplicate handling.
- `performance-and-readiness`: canonical sleep regularity and provider-domain consumers without raw-provider reads in the affected paths.
- `encrypted-storage-and-migrations`: supported v9–v13 upgrades to the extended schema and data-preserving backup/restart behavior.
- `athlete-profile-and-checkins`: authoritative local zone configuration with provider separation and undo.

## Impact

Owners: `backend/canonical`, `backend/db`, `backend/providers`, `backend/sync`, `backend/activities`, `backend/performance`, `backend/athlete`, planning/HTTP assembly and affected public consumers. Preserve all athlete state, receipts, source labels, session/CSRF protection and encryption. No new runtime dependency, proprietary metric recreation, new scientific method, implicit provider write, deployment, live data access or broad unrelated Epic A cutover is authorized by this change.

Evidence baseline: clean `eed88ccef264501697e3c5e5d83bf173963b16ea`; current schema v13 in `backend/db/schema.py`; metadata gaps in `backend/canonical/records.py` and `backend/db/canonical_store.py`; provider-keyed feedback in `backend/activities/feedback.py` and `backend/activities/activity_reference.py`; provider-shaped zones in `backend/activities/zone_settings.py`. Existing migration evidence lives in `tests/test_db_migrations.py`. New behavior and encrypted v15 evidence (renumbered after develop released v14) remain to be implemented and verified.
