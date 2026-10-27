## Why

Cycling eFTP, form (TSB) and ramp rate still come from snapshot carrier fields: the `sportInfo` entries and the `tsb`/`rampRate` keys of the Intervals.icu wellness rows, plus the athlete's `sport_settings`. `MetricKind.EFTP` and `MetricKind.FORM` are already mapped to canonical observations but only the planning-recovery view reads FORM, and ramp rate has no canonical form at all. Issue #1412 (Epic A #1407) makes canonical observations the only source for these three values, so the performance context, trends, Coach and PWA stop depending on snapshot rows (their removal is #1416).

## What Changes

Existing behavior (verified in source on origin/develop `6eab8617d`):

- eFTP:
  - `backend/performance/current_metrics.py:current_performance_metrics` computes `cycling_eftp_watts` as the first ride-matching entry of `snapshot["athlete"]["sport_settings"]`, else the ride entry of the latest wellness row's `sportInfo` (`_intervals_eftp_value`, `_sport_info_setting`), else the latest ride activity's eFTP. The ride match is a substring test (`ride`, `bike`, `rad`, `cycling`) over every `types` entry, or over `type`/`sport`/`sport_type` when `types` is not a list.
  - `backend/performance/eftp.py:eftp_daily_values` builds the daily series from the `sportInfo` of wellness rows (via its own `_sport_info_setting`) plus ride activities; same-day wellness wins. `eftp_30_day_average` averages it. Callers: `backend/performance/body.py:body_history`, `backend/performance/chart_history.py` (eFTP chart) and `backend/performance/comparisons.py:performance_comparisons` (`cycling_eftp_30d`). Values are bounded 20-2000 W by `activity_validation.bounded_performance_metric`.
  - The eFTP observations exist (`backend/providers/intervals_wellness_mapping.py:_map_sport_info`, `_map_sport_setting`, `_add_eftp`; mapper version 7 on develop) but no reader uses them.
- Form: `backend/performance/load_context.py:performance_load_context` sets `tsb` from `backend/performance/wellness.py:wellness_form_value` of the latest wellness row (`tsb`, `form`, `freshness`, else `ctl - atl` rounded to 2 decimals). `comparisons.form_tsb` averages the same function over the last 7 days (`wellness_form_average`). The mapper stores the reported value, else a DERIVED `ctl - atl`, as `MetricKind.FORM`.
- Ramp rate: `performance_load_context` passes the latest wellness row's `rampRate` through unchanged. There is no canonical kind.
- `backend/performance/canonical_sections.py` states that `tsb`, `rampRate` and the `sportInfo` eFTP are "not rebuilt" and come from the snapshot carrier rows.

Proposed behavior:

- eFTP and form are read only from canonical Intervals.icu observations; ramp rate is computed locally from canonical CTL observations. Without canonical inputs the three values are absent: no legacy fallback and no `canonical=None` snapshot branch.
  - Current eFTP: the athlete-record ride eFTP of the latest sync, else the ride eFTP observation of the latest wellness day, else the latest ride activity's eFTP (activity rows are already canonical and unchanged).
  - eFTP series (body, chart, 30-day comparison): ride eFTP observations of wellness days, merged with ride activity eFTP exactly as today (wellness wins the same day). The 20-2000 W consumer bounds stay.
  - Form: the FORM observation of the latest wellness day; the 7-day `form_tsb` average over FORM observations by day. The consumer no longer derives `ctl - atl` and no longer reads `tsb`/`form`/`freshness` from rows.
- **BREAKING (displayed value)** Ramp rate is the locally derived `round(CTL_t - CTL_(t-7), 2)` from canonical wellness-day CTL observations of the latest wellness day `t` and exactly seven days earlier. If either day has no CTL observation, or there is no wellness day, it is `None`. It is labelled by a new additive key `current_load.rampRate_source` (`"Intervals.icu CTL (berechnet)"`, `None` when the value is `None`). It can differ from Intervals.icu's own `rampRate`, which is no longer shown. No new `MetricKind`.
- Output keys are unchanged (`current_load.{id,ctl,atl,tsb,rampRate}`, `comparisons.form_tsb`, `comparisons.cycling_eftp_30d`, `metrics.cycling_eftp_watts`, chart key `cycling_eftp_watts`), as are all source labels apart from `rampRate_source`. Provider-neutral names are #1413.
- No mapper change and no `MAPPER_VERSION` bump (the wellness mapper is at version 7 since Epic B, PR #1464, which did not change the eFTP, form classification or athlete-record keys). Known deviations that follow from the unchanged mapper are documented in the design and are not requirements:
  - two ride sport settings: the observation store keeps the last, legacy took the first;
  - `sportInfo` entries identified only by `sport` or `sport_type` (not `types`/`type`), and settings whose ride type is not the first `types` entry, yield no eFTP observation;
  - a reported `tsb` that is not a number yields no FORM observation, so form is absent instead of derived.
- Out of scope: `backend/performance/trends.py:intervals_performance_average` (its non-eFTP `sportInfo` thresholds have no canonical kind), removal of the `tsb`, `rampRate` and `sport_info` carrier fields from compact snapshot rows (#1416), own load models (#1432), provider-neutral key names (#1413), and the planning-recovery view.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `performance-and-readiness`: current eFTP, the eFTP series and comparison, form and its 7-day comparison read canonical observations only; ramp rate is a labelled local derivation.
- `provider-normalization-and-provenance`: the Intervals wellness mapping requirement records which eFTP and form inputs yield observations (the unchanged mapper's limits).

## Impact

- Backend:
  - `backend/performance/canonical_inputs.py`, `backend/performance/canonical_current.py`
  - `backend/performance/load_context.py`, `backend/performance/wellness.py`, `backend/performance/eftp.py`
  - `backend/performance/current_metrics.py`, `backend/performance/comparisons.py`, `backend/performance/body.py`, `backend/performance/chart_history.py`, `backend/performance/context.py`
  - `backend/performance/canonical_sections.py` (docstring only) and the module docstrings of `source_policy.py` and `intervals_wellness_mapping.py` that mention these values
  - callers that pass the rows today (public performance, activity read service, Coach context) only forward the existing `canonical` inputs.
- Tests: eFTP, wellness, load, load context, comparisons, body, chart history, current metrics, canonical parity/current/sections, source policy and the characterization modules; `tests/architecture_registry.py` for the changed `eftp` functions.
- Data: no schema change, no mapper bump, no reprojection, no provider refetch and no remote writes. The stored observations from mapper version 7 are read as they are.
- API/Coach/PWA: same keys plus `current_load.rampRate_source`. The PWA reads only `cycling_eftp_watts` (`public/analysis.js`, `public/performance-view.js`), so no frontend change and no `public/index.html` or service-worker version change.
- Coordination: Epic B (PR #1464) is merged; this change is rebased onto it (develop `cec8e9d2`) and adds no mapper version.
