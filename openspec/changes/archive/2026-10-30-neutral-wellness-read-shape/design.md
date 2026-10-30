# Design

## Context

Inspected revision: `3a5547be` (develop).

`read_performance_inputs` (`backend/performance/canonical_inputs.py`) reads the Intervals.icu wellness-day observations through `canonical_sections.read_wellness_observations`. `canonical_sections.wellness_rows` then turns them into dict rows keyed by the first Intervals alias of each kind (`WELLNESS_ROW_KEYS`), laid over the snapshot's `recent_wellness` rows. A second set of rows additionally carries `raw_provider_data.wellness` for the history views.

The consumers of those rows are:

- `context.py`: picks the latest row, passes rows on, and reads the subjective ratings.
- `load_context.py`: CTL and ATL of the latest row; the canonical override is already applied there.
- `load.py:actual_atl_series`: the first row's `atl` seeds the reconstruction.
- `comparisons.py`: CTL/ATL 7-day averages through `wellness.wellness_average`, and `trends.intervals_performance_average` for the 30-day trends. The trends read `weight`, readiness aliases and `sportInfo` FTP/LTHR/VO2max/pace and run eFTP.
- `current_metrics.py`: latest-row `weight` and `bodyFat`, plus `sportInfo` fallbacks for LTHR, FTP, threshold pace, Zone-2 pace and VO2max.
- `body.py:_intervals_measurements`: weight and body fat per day, through `chart_history.py`.
- `personal_recovery.py:sleep_timing_variability`: walks the rows for sleep start and end fields when no canonical sleep periods exist.

Without canonical inputs, `context.py`, `current_metrics.py`, `comparisons.py` and `body.py` read the snapshot rows themselves.

The existing requirements already make recovery values, eFTP and form absent without canonical inputs (`openspec/specs/performance-and-readiness/spec.md`, "Current and planning recovery sources" and "Cycling eFTP and form ..."). Production always builds canonical inputs, because the read selector serves the legacy projection through the same ports. The `canonical=None` path is reached only by tests and unconfigured compositions.

## Goals / Non-Goals

**Goals:**

- One typed wellness day view, keyed by `MetricKind`, with observation provenance; no Intervals.icu field names in performance readers of wellness values.
- Neutral output keys for the performance context sections listed in the spec, in a single contract with no dual keys.
- Behaviour parity of values and labels for equivalent canonical data.

**Non-Goals:**

- Activity rows and summaries (`compact_activity_rows`, `load.py` activity load aliases, `start_date_local` reads), `public_metrics` and the PWA activity and plan views. These belong to slice 2, which also adds the field-name guard.
- Snapshot `athlete` sport settings and Garmin view fallbacks in `current_metrics.py`, `garmin_metrics.py` and `body.py` (#1415), and the selector and legacy read state (#1416).
- The ingest compaction in `planning/context.py` (`WELLNESS_FIELDS`), which is not a read path.

## Decisions

### D1 — A frozen `WellnessDay` view instead of dict rows

The new module `backend/performance/wellness_days.py` defines `WellnessDay(day: date, observations: Mapping[MetricKind, Observation])` with `value(kind) -> float | None`. It also defines the helpers `read_wellness_days(reader, db) -> tuple[WellnessDay, ...]` (all days, ascending), `current_window(days)` (the 90 days ending on the latest day), `latest(days)` and `series(days, kind) -> dict[date, float]`. The kinds are the former `WELLNESS_ROW_KEYS` kinds plus `FORM`, so a day that has only a form observation still counts as a wellness day, as its carrier row did. The wellness-day filter (`_is_wellness_day`) and `wellness_day_values` move to this module.

`canonical_sections.py` keeps only `compact_activity_rows` until slice 2. `row_day`, `wellness_rows`, `WELLNESS_ROW_KEYS` and `read_wellness_observations` are removed.

Alternative considered: neutral string-keyed dicts (`resting_hr_bpm` and similar). That adds a second vocabulary next to `MetricKind` and loses provenance. Rejected.

### D2 — Inputs carry days and series, not rows

`CanonicalPerformanceInputs.wellness_rows` and `history_wellness_rows` become `wellness_days` (current window) and `history_wellness_days` (every stored day). A `run_eftp_by_day` series is added next to `eftp_by_day`. The CTL series for the ramp rate and `form_by_day` come from the same days, so each kind is still read once per unit (`ReadOnceObservationReader`).

`_activity_start` uses the first day of the current window. The latest wellness day is the latest day of the view. Snapshot rows no longer contribute days. A day that only a snapshot row had, or that has only sport-scoped eFTP observations, is no longer a wellness day. This is accepted and documented in the spec scenario.

### D3 — No snapshot adapter for `canonical=None`

Without canonical inputs, the wellness values are absent. This is the same rule as for recovery, eFTP and form. Mapping snapshot rows through `providers.snapshot_projection` inside performance was rejected: it would keep a second legacy path alive that #1415 and #1416 must delete again, and would import a provider module into performance. Tests that asserted wellness values on the legacy path move to canonical inputs built from the real mapper, which is the existing parity-test pattern in `tests/test_performance_canonical_parity.py`.

### D4 — Consumers take typed inputs

- `load_context.performance_load_context(activities, days, today, canonical=...)` reads CTL and ATL from `canonical` (already selected) and `id` from the latest day.
- `load.actual_atl_series(atl_by_day, activities, end_date)` takes the ATL day series.
- `wellness.wellness_average` gets a day-series variant. The `("ctl", "ctLoad")` key tuples disappear.
- `trends.intervals_performance_average(days, run_eftp_by_day, key, days_count, end_date)` keeps only `weight_kg`, `readiness` and `run_threshold_watts`. `_sport_info_setting` is removed from `trends.py` and `current_metrics.py`. The other trend keys return None on the Intervals path, as they already did for real payloads.
- `current_metrics` takes `latest_wellness: WellnessDay | None` for weight and body fat. The `wellness_ride` and `wellness_run` parameters are removed.
- `body._intervals_measurements` takes the history days and reads `WEIGHT` and `BODY_FAT`. The bounding helpers and the source and date tuple shape are unchanged. `synced_at` is the observation's `provenance.retrieved_at`, ISO formatted, instead of the snapshot `synced_at`. This is the same instant for synced data and must be verified by a test.

### D5 — Output keys renamed in place, single contract

`context.py`, `comparisons.py` and `load_context.py` emit the neutral keys of the spec. `RAMP_RATE_SOURCE` is unchanged. The thresholds become `ftp_w` and `w_prime_j`. They still read the snapshot athlete record, which is #1415 territory, so only the keys change here; the import of `intervals_performance_fields` in `context.py` is dropped. No compatibility aliases are emitted. No browser module reads these keys (grep over `public/`). The Coach context forwards the dict unchanged, so the Coach sees the new keys.

### D6 — Measurement labels

In `personal_recovery._SERIES` the third tuple element becomes a method label: sleep `duration`, resting HR `resting`, HRV `RMSSD` or `SDNN`. The Garmin field constants import is dropped from that table. The series group key stays `(provider, metric, label)`. Garmin nightly HRV and Intervals.icu RMSSD remain separate through the provider. `tag_impact` copies the label unchanged.

### D7 — Sleep timing fallback reads the stored rows explicitly

`personal_recovery(...)` gets the stored snapshot wellness records only for the documented pre-sleep-period fallback. `context.py` passes `snapshot["recent_wellness"]` rows. These are the rows the carrier provided, so the behaviour is identical. The walk does not run when canonical sleep periods exist. #1416 removes it together with the legacy read state.

## Risks / Trade-offs

- [Wide test churn: legacy-path tests asserted wellness values without canonical inputs] → Move them to canonical inputs built from the real mapper. Keep the golden values. Delete only tests that assert the removed `sportInfo` threshold fallbacks, and replace each with a test that pins their absence.
- [Snapshot-only wellness days disappear] → The legacy projection maps the same `recent_wellness` rows into observations, and TABLES state stores every synced day. Only rows with no mappable value are lost. The spec scenario documents this.
- [Coach answers keyed on old names] → The Coach reads the JSON it is given. No prompt or tool schema names the old keys (grep over `backend/coach`).
- [History in legacy read state covers only `recent_wellness`] → This is an accepted transitional limit until #1416, documented here. TABLES state is the production state after the first backfill.

## Migration Plan

There is no schema or data migration; deploy normally. Roll back by reverting the PR. Stored data is unaffected.
