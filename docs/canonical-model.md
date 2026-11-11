# Canonical data model

Every provider speaks its own vocabulary. Pacecraft maps all of it once, at the edge, into provider-neutral records, and every reader (API, UI, Coach, derived metrics) works on those records only. The field-by-field reference is the [canonical field map](canonical-field-map.md); this page explains how the pieces fit together.

## Provider-neutral records

- The vocabulary lives in `backend/canonical/` (standard library only): sports, environments, metric kinds, units, provider ids, record states.
- A **provider record** keeps the raw payload exactly as received, tagged with the provider and the mapper version that projected it.
- An **activity record** is one provider's copy of a workout (Garmin, Wahoo). An **observation** is one dated value of a metric kind (weight, resting heart rate, FTP, sleep duration, ...) with a unit, a measurement context and a period.
- **Activity detail** (streams, laps, zone times, strength sets) is stored as detail sets per record and served as `activity_detail.v1` for every provider.
- Sports are stored as `sport` plus `environment` (for example `ride` + `virtual`), with a lossless `sport_detail` for text that has no canonical sport. Only the Intervals.icu output adapter maps canonical values back to Intervals.icu activity types and field names.

## Sessions

A workout recorded by several devices (for example a Wahoo head unit and a Garmin watch) is one **session**. The session bundles the provider copies, picks the values to show, and keeps every copy stored; nothing is deleted at a provider. The athlete (or the Coach on request) can confirm a bundle, split a copy off, merge copies of the same day or delete the activity locally; corrected sessions are never re-bundled by later syncs. Athlete-entered data (feedback, session RPE, equipment, the "Art der Einheit" marking) belongs to the session, so it survives splits, merges and provider re-deliveries.

## Provenance and precedence

Each observation carries its provider, source kind, observation time and retrieval time. A metric kind has one ordered source rule (`backend/performance/source_policy.py`): a locally confirmed value (zone configuration, profile) leads for thresholds, then the providers in a fixed order, with age limits and plausibility bounds. The athlete can prefer a provider per group (thresholds, body, HRV, resting heart rate, sleep). Values from other sources stay visible as labelled alternatives; they are never averaged into the chosen value. AI estimates and derived values are labelled as such. Intervals.icu is an output target and never a source.

## Raw payload replay

Raw provider records (activity summaries and observations) are stored, so a mapper fix to them does not need a new download. Every provider record remembers its `mapper_version`; when the code's version is ahead, a background backfill re-projects the stored raw data into the canonical tables, without reviving deleted activities, and retires observations a newer mapper no longer emits (they stay stored, but are no longer served). Reads come from the canonical tables once the first backfill has completed; until then the app reports that data is being prepared instead of showing partial values. Activity detail (streams, laps, zones, strength sets, sensors) is mapped from files that are not stored: a detail-mapper change is applied by fetching the file again inside the provider's sync or replay window, and older detail sets keep their earlier projection.

## Derived records

Values the app computes itself are stored beside the provider data and recomputed after syncs, zone changes and corrections: session load and intensity (method M6), efficiency factor and decoupling (M8), session analyses and zone times. The methods and their evidence are in [performance methods](performance-methods/README.md).

## Related documents

- [Canonical field map](canonical-field-map.md): every mapper, field and enum member.
- [Schema history](schema-history.md): when each canonical table arrived.
- [Synchronization and jobs](synchronization.md) and [operations](operations.md): backfills and diagnostics.
