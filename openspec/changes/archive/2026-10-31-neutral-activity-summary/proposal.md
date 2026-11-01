## Why

Backend consumers (activities, performance, season preparation and the Coach
context) still read Intervals.icu-shaped activity rows (`start_date_local`,
`moving_time`, `icu_training_load`, `type` "Ride", ...). They therefore see only
Intervals.icu activities, and the Coach and several HTTP views show provider keys
and type names (#1510, follow-up of #1413, Epic A #1407).

## What Changes

- Activity records carry the summary values that consumers need and that were only
  in the raw payload (intensity, RPE, feel, average/weighted speed, pace, FTP,
  eFTP, VO2max, zone times, average temperature, planned-event reference). The
  Intervals.icu, Garmin and Wahoo mappers fill them where the provider reports them;
  the mapper version bumps re-map stored rows through the existing backfill. No
  schema change: the values live in the record details.
- A provider-neutral activity summary is built per canonical session from all its
  active records of every provider. Each value comes from the best-ranked record
  that has it (measured and derived order as in `activity_detail.v1`) and names its
  source. The summary `id` is the local session id (`act_...`).
- The summary uses the HTTP/detail vocabulary (`started_at_local`,
  `moving_duration_s`, `distance_m`, `avg_power`, `normalized_power`,
  `training_load` with `load_model`, ...) and the canonical `sport` and
  `environment` instead of provider type names.
- `training_load` is filled only from TSS-like models (Intervals.icu training load,
  TSS). A session with only a Garmin training load adds duration and distance to
  totals but no load.
- Activity consumers in `activities/`, `performance/`, `planning/season_preparation`
  and the Coach context read summaries. Garmin-only and Wahoo-only sessions now
  appear in the Coach context, calendar, load rollups, reports and season
  preparation; duplicates of one session are counted once.
- HTTP outputs built from activities (training calendar, training report, training
  focus, season preparation, Coach) carry canonical sports and neutral keys; the PWA
  label maps follow.
- The provider-coupling guard's `_ACTIVITY_ROWS` field-module allowlist entries are
  removed; files that still import a field-name module do so only for local planning
  record keys or the Garmin training-effect snapshot read, under those reasons.

Exclusions: local planning record keys (`_PLANNING_RECORDS`), the legacy fallbacks
of #1415 (equipment, Garmin views), the dead legacy readers and the read selector
fallback (#1416), the paginated activity list and feedback validation, which keep
their raw-row readers, and the raw activity detail projection, which moves to the
Intervals.icu provider adapter unchanged.

## Capabilities

### New Capabilities

### Modified Capabilities

- `provider-normalization-and-provenance`: activity records carry the summary
  values; consumers read the neutral activity summary instead of provider rows.
- `coach-context-and-provenance`: Coach activity context uses neutral keys,
  canonical sports and local session ids, and includes every provider.
- `performance-and-readiness`: load rollups, report, focus and season preparation
  count each session once across providers with TSS-like load only.

## Impact

Backend: `canonical/records.py`, provider activity mappers, `db/canonical_store.py`
details, `sync/canonical_table_reader.py` and the read selector, a new summary
builder in `activities/`, the listed consumers, `tests/provider_coupling.py`.
Frontend: label maps and keys in the analysis, plan and performance views
(`public/index.html` query versions and the service-worker cache bump together).
No schema change; the mapper bumps re-project stored activity rows.
