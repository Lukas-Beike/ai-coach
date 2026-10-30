# Proposal

## Why

Issue #1413 (Epic A #1407) asks for one provider-neutral read shape. The daily wellness values are already canonical observations, but `backend/performance/canonical_sections.py` turns them back into Intervals.icu-shaped rows (`restingHR`, `sleepSecs`, `ctLoad`, `bodyFat` and similar keys), layered over the snapshot's `recent_wellness` rows. Those rows still carry fields that have no observation, such as `sportInfo`. Every performance reader therefore still depends on Intervals.icu field names. The Coach and HTTP performance JSON also exposes `restingHR`, `hrv`, `sleepScore`, `rampRate`, `icu_ftp` and `icu_w_prime`. This change is the first of two #1413 slices (user decision 2026-10-30). It covers daily wellness and recovery. The second slice covers activity summaries, the browser activity and plan views, and the field-name guard.

## What Changes

- Add a typed, provider-neutral daily wellness view. It is built only from canonical Intervals.icu wellness-day observations, and every value keeps its observation and provenance. It replaces the rebuilt wellness rows, `WELLNESS_ROW_KEYS` and the snapshot carrier.
- Move every reader of the wellness rows onto the view: load context CTL/ATL, actual ATL reconstruction, CTL/ATL comparisons, 30-day trend averages, current weight and body fat, subjective ratings, and body history. Snapshot `recent_wellness` and `raw_provider_data.wellness` are no longer read for these values. Without canonical inputs the values are absent. This matches the existing recovery, eFTP and form requirements and takes over the wellness-row items of #1415.
- Remove the wellness `sportInfo` fallbacks for FTP, LTHR, VO2max, threshold pace and Zone-2 pace. Intervals.icu wellness `sportInfo` entries carry the sport type, CTL, ATL, eFTP, W′ and Pmax, but none of those keys. The 30-day running threshold-power average now reads the canonical run eFTP wellness-day observations, which the removed carrier read as the run `sportInfo` eFTP.
- **BREAKING (Coach/HTTP JSON):** rename the provider-shaped keys of the performance context:
  - `recovery`: `restingHR` becomes `resting_hr_bpm`, `hrv` becomes `hrv_ms` and `sleepScore` becomes `sleep_score`. Their `*_source` and `source_freshness` keys are renamed the same way.
  - `comparisons`: `restingHR` becomes `resting_hr_bpm` and `hrv` becomes `hrv_ms`.
  - `current_load`: `rampRate` becomes `ramp_rate` and `rampRate_source` becomes `ramp_rate_source`.
  - `thresholds`: `icu_ftp` becomes `ftp_w` and `icu_w_prime` becomes `w_prime_j`.

  Values and source labels stay unchanged. No browser module reads these keys, which was verified by grep over `public/`.
- Personal recovery measurement labels become method names (`RMSSD`, `SDNN`, `duration`, `resting`) instead of provider field names (`lastNightAvg`, `sleepSecs`, `restingHR`). Series stay separated by provider and method.
- Sleep timing variability keeps its documented pre-sleep-period fallback. It reads the stored snapshot wellness records directly from the composition, not through the rebuilt rows, until #1416 removes the legacy read state.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `performance-and-readiness`: wellness-derived values come from the neutral day view only. The performance output keys are provider-neutral, the `sportInfo` threshold fallbacks are removed, and the measurement labels are neutral. The ramp-rate and eFTP/form requirements are updated for the renamed keys.

## Impact

- Code: `backend/performance/canonical_sections.py`, `canonical_inputs.py`, `context.py`, `load.py`, `load_context.py`, `comparisons.py`, `trends.py`, `wellness.py`, `current_metrics.py`, `body.py`, `chart_history.py` and `personal_recovery.py`, plus a new neutral wellness-day module in `backend/performance/`.
- Coach context and `/api/state` and `/api/performance` JSON: renamed keys only. The PWA is unaffected apart from the displayed HRV measurement label, which is a server value. No JavaScript, asset version or service-worker change is needed. The e2e fixture label is updated.
- No schema, mapper or provider change, and no remote write. Tests: performance unit and characterization suites, parity tests and the `e2e/analysis-info.spec.js` fixture.
- Exclusions: activity summaries, `public_metrics`, the PWA activity and plan views and the guard test (slice 2); snapshot athlete and Garmin view fallbacks (#1415); the read selector, legacy read state and dead readers (#1416); local planning record keys (user decision, follow-up issue).
