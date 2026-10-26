## Context

Epic A (#1407) moves every application read onto the canonical model. #1410 (activity detail) and #1411 (recovery) are merged; #1412 covers the load-side metrics that still read snapshot carrier rows. The wellness mapper (`backend/providers/intervals_wellness_mapping.py`, version 6) already produces `MetricKind.EFTP` (sport-scoped, from wellness `sportInfo` and from athlete sport settings) and `MetricKind.FORM` (reported `tsb`/`form`/`freshness`, else a DERIVED `ctl - atl`). Canonical wellness rows (`canonical_sections.wellness_rows`) only overlay observations onto the carrier rows, which therefore keep serving `tsb`, `rampRate` and `sportInfo`. #1411 set the precedent used here: values come from observations only and are absent when no canonical inputs exist.

Inspected revision: origin/develop `6eab8617d`. Epic B (PR #1464) is unmerged and owns the wellness mapper version 7.

## Goals / Non-Goals

**Goals:**
- eFTP, form and ramp rate computed from canonical observations only, with unchanged output keys and labels (plus `rampRate_source`).
- Identical values in the performance context, trends, Coach and PWA for synthetic canonical data without snapshot rows.
- No mapper change, no schema change, no provider refetch.

**Non-Goals:**
- Renaming keys (#1413); removing carrier fields from compact snapshot rows (#1416); own load models (#1432).
- `backend/performance/trends.py` (its `sportInfo` FTP/LTHR/VO2max/run values have no canonical kind) and the `sport_info` reads in `current_metrics` for FTP, LTHR and VO2max.
- The planning-recovery view and the Garmin FTP history.

## Decisions

### D1 Day series from wellness-day observations

`read_performance_inputs` already reads every wellness kind once through the unit's `ReadOnceObservationReader` and keeps the wellness-day observations (`canonical_sections.read_wellness_observations`, `_is_wellness_day`). Extend that read to `MetricKind.FORM` and `MetricKind.EFTP` (EFTP restricted to `Sport.RIDE`) and build per-day mappings in `canonical_inputs.py`:

- `form_by_day: Mapping[date, float]` and `eftp_by_day: Mapping[date, float]`, new optional fields of `CanonicalPerformanceInputs` (default None means not read);
- the CTL mapping used by D3, built from the CTL observations already read.

A helper `wellness_day_series(observations)` maps `observed_on` to the value. The wellness natural key allows one observation per kind, sport and day, so no tie-break is needed. Athlete-record observations (`source_record_id` different from the day) are excluded by `_is_wellness_day`, which keeps the athlete eFTP (D4) out of the series.

The unit read count grows by two kinds; `tests/test_performance_canonical_parity.py:_UNIT_READS` is adjusted.

Alternative considered: overlay `FORM` into the canonical wellness rows through `WELLNESS_ROW_KEYS` (key `tsb`). Rejected: `wellness_rows` copies the carrier row and `row.update(...)` replaces only keys that have an observation, so a carrier `tsb`/`form`/`freshness` stays readable whenever no FORM observation exists. That is the legacy fallback this change removes. Day series keep the consumers away from those keys altogether. An eFTP overlay is rejected for the same reason, and because it would replace the carrier `sportInfo` that the FTP, LTHR and VO2max fallbacks still read.

### D2 Form

- `tsb` in `current_load` is `form_by_day.get(wellness_day)` (the FORM observation of the latest wellness day), or `None` when there is no canonical input, no wellness day or no observation. The latest-day restriction is the one CTL and ATL already use (`canonical.wellness_day`).
- `wellness.wellness_form_value` and its alias and derivation logic are removed. `wellness.wellness_form_average` becomes a 7-day average over `form_by_day` (inclusive window ending on `today`, rounded to 2 decimals), and `comparisons.form_tsb` uses it.
- Reported and derived values stay as the mapper stored them (`PROVIDER_REPORTED`, or DERIVED `ctl - atl` rounded to 2 decimals), so the displayed numbers equal the legacy ones whenever the row's `tsb` was usable or absent.
- Accepted deviation: a reported `tsb`/`form`/`freshness` that the mapper rejects (not a number, or outside +-10000) yields no FORM observation. The legacy reader fell back to `ctl - atl`; the canonical reader shows no form for that day. This is the mapper's documented rule that invalid first-present aliases do not silently fall through. The mapper also accepts `ctLoad`/`atlLoad` for the derivation, which the legacy `ctl`/`atl`-only derivation did not, so a few days gain a derived form.

### D3 Ramp rate

- `ramp_rate: float | None` is a new defaulted field of `CanonicalPerformanceInputs`, computed in `read_performance_inputs` from the CTL mapping of D1: `round(ctl[t] - ctl[t - 7 days], 2)` where `t` is the latest wellness day. Exact days only: if either CTL day is absent, or `t` is None, it is `None`. No interpolation, no nearest-day search. CTL wellness-day observations are Intervals-only, so no provider is pooled.
- `performance_load_context` sets `load["rampRate"] = canonical.ramp_rate` (None without canonical inputs) and adds `load["rampRate_source"] = "Intervals.icu CTL (berechnet)"` when the value is not None, else `None`. The label follows the existing German derived-value wording (`"Abgeschlossene Aktivitäten (berechnet)"` for the actual load) and the `*_source` sibling convention of the recovery block.
- Intervals.icu's own `rampRate` is no longer shown or read. The derivation is the athlete's decision; the spec states that the number can differ from Intervals.icu's.
- No new `MetricKind`, so there is no vocabulary, validation, mapper or reprojection change.

### D4 Current eFTP

`CanonicalCurrentInputs` (`canonical_current.py`) gains two optional observations next to the weight pair:

- `athlete_eftp`: the ride eFTP observation of the athlete record of the latest Intervals sync, found like the athlete weight (Intervals, `Sport.RIDE`, record id different from the observation's day, `retrieved_at` equal to the sync instant, inside the sync-day window). `EFTP` is not added to `_SYNC_KINDS`, so the sync instant is still defined by thresholds, VO2max and weight.
- `wellness_eftp`: the wellness-day ride eFTP observation of the latest wellness day, like the wellness weight.

`read_current_inputs` includes both in its "all empty" check. `current_metrics.current_performance_metrics` then computes the current value as `athlete_eftp or wellness_eftp or latest ride activity eFTP`, with the unchanged source label `PROVIDER_INTERVALS_NAME`. The mapper already drops zero values, which keeps the legacy "zero means unset" behaviour. The latest-ride-activity step still reads the canonical activity rows (`ESTIMATED_FTP_ALIASES`) and is unchanged. The snapshot `athlete.sport_settings` and the wellness `sportInfo` are no longer read for eFTP; `_sport_setting` and `_sport_info_setting` keep serving FTP, LTHR, VO2max and the other fallbacks.

Without `CanonicalCurrentInputs` (no Intervals sync marker and no Wahoo value) the first two steps are absent and only the activity step applies.

The current value is not bounded (as today); the mapper bound is 0-2500 W with zero unset.

### D5 eFTP series and comparison

`eftp.eftp_daily_values(eftp_by_day, activities, start, end)` keeps its merge rule (one value per day; activities first, a wellness value overrides the same day; the activity step is untouched) and its 20-2000 W bounds (`activity_validation.bounded_performance_metric("cycling_eftp_watts", ...)`, applied to the observation value). Its wellness-row branch (`_wellness_eftp_value`, `_sport_info_setting`) is removed. `eftp_30_day_average` takes the mapping.

Callers: `comparisons.performance_comparisons` (new `eftp_by_day` argument, passed from `context.py` with `canonical.eftp_by_day`), `body.body_history` and `chart_history` (both already receive `canonical` and pass `eftp_by_day` from it). With `canonical` None or `eftp_by_day` None the wellness part is empty and only activity eFTP contributes.

The canonical series spans all stored wellness days, while the compact snapshot rows held 42-90 days. Every consumer windows the series (30-day average, 84-day body history, 90-day chart), so displayed values are unchanged.

### D6 Known deviations (documented, not fixed here)

The wellness mapper is out of scope (Epic B owns version 7). The unchanged mapper therefore differs from the legacy readers in these cases. They are recorded in the spec's detailed contract as limits, tracked by a follow-up issue after #1464, and pinned by tests that name them:

- Two athlete sport settings that classify as ride: their observations share one natural key (`provider|eftp|ride|athlete|day`), so the store keeps the last one written. The legacy reader took the first matching setting. Wellness `sportInfo` is unaffected (`_map_sport_info` keeps the first entry per sport).
- Classification uses `types[0]` (or `type` for `sportInfo`). A ride setting whose first `types` entry is not ride-like, and `sportInfo` entries identified only by `sport` or `sport_type`, yield no observation. Legacy matched any `types` entry and all three alias keys. The real Intervals.icu shape (`tests/fixtures/providers/intervals/wellness.json`) carries `types` and `type`, so the aliases occur only in unit-test fixtures (`tests/test_performance_eftp.py`).
- Invalid reported form: see D2.
- A value above 2000 W but below the mapper's 2500 W bound is stored; the series bounds drop it, while the unbounded current value shows it (as before).

### D7 Removals

Removed when no caller remains: `wellness.wellness_form_value` (with its `tsb`/`form`/`freshness` and `ctl - atl` logic), the wellness-row branch of `eftp.py`, the `rampRate` and form reads in `load_context.py`, and the snapshot eFTP reads in `current_metrics.py` (`_intervals_eftp_value` stays only if another caller needs it). `tests/architecture_registry.py` is updated for the changed `backend.performance.eftp` functions. The `canonical_sections.py` docstring is corrected once PR #1464 settles the surrounding text.

### D8 Tests

Parity tests compare the legacy readers (golden values from the existing characterization tests on snapshot wellness rows) with the canonical path built by the real mappers (`map_intervals_wellness`, `map_intervals_athlete_thresholds`) on equivalent data. They then run the canonical path with empty `recent_wellness` and `athlete.sport_settings` to prove that the snapshot rows are not read. Every changed expectation is commented as an intended D2-D6 difference. New tests cover missing, stale and multi-sport cases:

- missing: no FORM day, no CTL seven days earlier, no wellness day, no canonical inputs, no athlete record;
- stale: an older eFTP day with a newer wellness day without eFTP (the current value falls to the activity step and the series keeps the older day), a CTL pair eight days apart;
- multi-sport: Ride and Run `sportInfo` and sport settings (only ride feeds eFTP), VirtualRide classified as ride, two ride settings (pinned deviation).

## Risks / Trade-offs

- [Values only present in carrier fields disappear] -> Intended by the cutover (strict canonical, as #1411). The compact-snapshot refetch story is #1416.
- [Ramp rate differs from Intervals.icu's] -> Athlete decision; labelled `Intervals.icu CTL (berechnet)` and documented in the spec.
- [Two ride settings show the last setting's eFTP] -> Known deviation (D6); follow-up issue after #1464, not fixed here to avoid a second wellness mapper bump.
- [Merge conflicts with Epic B] -> Both touch `canonical_sections.py`, `comparisons.py`, `body.py` and `chart_history.py`. This change adds no mapper version, so only textual rebasing is needed. The docstring correction waits for #1464.
- [Read count in unit-of-work tests changes] -> Two additional kinds are read once each; the parity tests assert the new count.

## Migration Plan

- No schema change, no mapper bump, no reprojection. Stored version 6 (or 7 after #1464) observations are read as they are.
- Rollback: reverting the change restores the snapshot readers; no data is written or removed.

## Open Questions

None. The duplicate-ride-setting and unclassified `sportInfo` follow-up is tracked as an issue after #1464.
