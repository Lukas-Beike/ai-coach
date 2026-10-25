## Why

The current recovery values and the personal recovery baselines still read HRV, sleep duration and most Garmin values from the raw Garmin view and Intervals-shaped wellness rows. Canonical observations (`HRV_RMSSD`, `HRV_SDNN`, `SLEEP_DURATION`, `SLEEP_SCORE`, `RESTING_HR`, `READINESS`) exist but only replace a legacy value when it matches. Issue #1411 (Epic A #1407) makes canonical observations the only source for these metrics, so the local HRV/resting-HR (#1428) and sleep (#1429) methods are built on provider-neutral data.

## What Changes

Existing behavior (verified in source on origin/develop 2524a08bc):

- `backend/performance/recovery_context.py:performance_recovery_context`:
  - reads sleep duration, sleep hours, the sleep date and the 7-day sleep average from the raw Garmin `sleep` section or the wellness rows;
  - reads HRV from the raw Garmin `hrv` section with `HRV_WITH_WEEKLY_ALIASES`, so a Garmin weekly average silently stands in for the last-night value under the same label, or from the wellness rows;
  - reads resting HR and readiness from Garmin/wellness first. Canonical values (`backend/performance/canonical_recovery.py:prefer_canonical`, `canonical_recovery_averages.py:prefer_canonical_average`) replace them only when provider, day and number match. Without canonical inputs the legacy readers run unchanged.
- `backend/performance/personal_recovery.py:personal_recovery` builds Intervals baselines from the wellness rows (`sleepSecs`, `restingHR`, `hrv`, `hrvSDNN`) and Garmin baselines from the raw view (`dated_garmin_recovery_records`). Canonical resting HR replaces a day only when it matches (`_prefer_canonical_resting_hr`). Without an Intervals snapshot (`backend/performance/context.py:_unavailable_context`) the baselines come from the raw Garmin view only.
- `backend/coach/morning.py:ManualMorningCheckinService._sleep_ready` reads the sleep day from canonical observations only when an observation source is wired; otherwise it reads the raw Garmin recent view.
- The Garmin mapper (`backend/providers/garmin_health_mapping.py`, mapper version 10) keeps the weekly HRV average out of `HRV_RMSSD` and does not store it at all.

Proposed behavior:

- The current recovery values come only from canonical observations, selected by the existing source rules (`backend/performance/source_policy.py:select_current`):
  - sleep duration and hours, sleep score, resting HR, HRV (RMSSD) and readiness;
  - their 7-day averages (the selected provider's daily values only, never mixed across providers);
  - their source labels and dates.
- **BREAKING (displayed value)** A Garmin weekly HRV average is no longer shown as the HRV value. It becomes its own canonical kind `HRV_WEEKLY_AVERAGE` (Garmin mapper version 11, existing automatic reprojection). It is shown only when no last-night RMSSD is selected, with a distinct source label and no 7-day average.
- Personal recovery baselines and sleep deficits read the daily canonical values per provider and measurement:
  - kinds: sleep duration, resting HR, RMSSD, SDNN, with RMSSD and SDNN never pooled;
  - the existing bounds, quartile, staleness and current-value-exclusion rules are kept;
  - measurement labels are unchanged.
  This also applies when there is no Intervals snapshot.
- Sleep regularity keeps its current input path (sleep onset/wake times have no canonical form until #1419). The code and spec say so explicitly.
- The morning check-in always reads the Garmin sleep day from canonical observations. The observation source becomes required.
- No legacy fallback remains for these metrics. Without canonical inputs (no observation source configured) the recovery values and baselines are reported as missing instead of falling back to raw provider data. The canonical recovery inputs are read even when there is no usable wellness day, so Garmin-only data stays visible.
- The now-unused legacy match-and-replace helpers and raw Garmin recovery readers are removed.
- Output keys (`restingHR`, `hrv`, `sleepScore`, `*_source`, `sleep_hours`, …) are unchanged. Provider-neutral key names are deferred to #1413 by the athlete's decision of 2026-10-25.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `performance-and-readiness`: current recovery values, averages, personal baselines and the morning sleep check read canonical observations only; weekly HRV is a labelled fallback; sleep regularity's interim input path is stated.
- `provider-normalization-and-provenance`: Garmin weekly HRV average is mapped as its own observation kind, still never as a last-night reading.

## Impact

- Backend:
  - `backend/canonical/vocabulary.py`, `backend/canonical/validation.py`
  - `backend/providers/garmin_fields.py`, `backend/providers/garmin_performance_fields.py`, `backend/providers/garmin_health_mapping.py`
  - `backend/performance/source_policy.py`, `backend/performance/canonical_recovery.py`, `backend/performance/canonical_recovery_averages.py` (removed or reduced), `backend/performance/canonical_personal_recovery.py`, `backend/performance/canonical_inputs.py`
  - `backend/performance/recovery_context.py`, `backend/performance/personal_recovery.py`, `backend/performance/recovery.py`, `backend/performance/context.py`
  - `backend/coach/morning.py`, `backend/coach/local_assembly.py`, `backend/performance/garmin_observations.py`
- Tests: the recovery context, characterization, personal recovery, canonical recovery, canonical parity, morning and Garmin mapping modules. Recovery tests move from raw Garmin/wellness dicts to observations produced by the real mappers.
- Data: no schema change (the `observations.metric` column is free text). Bumping the Garmin health mapper reprojects stored Garmin health records through the existing canonical backfill. No provider refetch and no remote writes.
- API/Coach/PWA: same keys. Values differ only where the legacy path disagreed with canonical data (weekly HRV, raw-only Garmin values, carrier-only wellness values).
