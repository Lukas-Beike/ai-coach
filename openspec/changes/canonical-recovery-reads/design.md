## Context

Epic A (#1407) moves every application read onto the canonical model. #1411 covers the recovery metrics. The source rules that reproduce the legacy precedence already exist (`backend/performance/source_policy.py`: `CURRENT_RULES` and `DAILY_RULES` for sleep duration/score, RMSSD, resting HR and readiness). The canonical wellness rows (`canonical_sections.wellness_rows`) already carry the Intervals values from observations. The remaining bypasses are:

- the raw Garmin view passed as `garmin` to `recovery_context` and `personal_recovery`;
- the "replace only on match" overrides (`canonical_recovery.prefer_canonical`, `canonical_recovery_averages.prefer_canonical_average`, `personal_recovery._prefer_canonical_resting_hr`);
- the legacy branch taken when canonical inputs are None;
- the optional observation source of the morning check-in.

Inspected revision: origin/develop `2524a08bc`.

## Goals / Non-Goals

**Goals:**
- One canonical input object for all recovery reads, read once per unit of work. It is also read without a wellness day and without an Intervals snapshot.
- Current values, averages, labels and dates computed from observations only. Existing precedence and bounds are kept through `select_current`.
- Personal baselines from daily observations per provider and measurement, with unchanged labels, thresholds and statuses.
- Garmin weekly HRV as its own kind and as a labelled fallback.
- Removal of the legacy readers and match-and-replace helpers that become unused.

**Non-Goals:**
- Renaming output keys (#1413).
- Sleep onset/wake times (#1419), measurement context (#1420), planning recovery and daily health, Garmin projection for the Coach `recovery` section, comparisons and source freshness (#1414).
- Any schema change, provider refetch or remote write.

## Decisions

### D1 One canonical recovery input

Replace `CanonicalRecoveryInputs` (three selected observations), `CanonicalRecoveryAverageInputs` and `CanonicalPersonalRecoveryInputs` with a single frozen `CanonicalRecoveryInputs` in `backend/performance/canonical_recovery.py`:

- `observations: Mapping[MetricKind, tuple[Observation, ...]]` for `SLEEP_DURATION`, `SLEEP_SCORE`, `RESTING_HR`, `HRV_RMSSD`, `HRV_SDNN`, `HRV_WEEKLY_AVERAGE` and `READINESS`, from all providers;
- `latest_wellness_day: date | None`.

`read_recovery_inputs(reader, db, *, as_of, latest_wellness_day)` reads each kind once from `as_of - 83 days` with no end bound, through the unit's `ReadOnceObservationReader`. `CanonicalPerformanceInputs` keeps one `recovery` field; `personal_recovery` and `recovery_averages` are removed.

`read_performance_inputs` reads the recovery inputs in both branches (with and without a latest wellness day). A Garmin-only athlete therefore keeps recovery values.

Alternative considered: keep three input types and only add kinds. Rejected, because each type re-reads the same kinds and the match-and-replace contract they encode disappears.

### D2 Current recovery values (`recovery_context`)

`performance_recovery_context(recovery: CanonicalRecoveryInputs | None, today)` returns the same keys as today. With None, every value, source, date and average is None.

For each metric the current observation is `select_current(observations[kind], kind, latest_wellness_day=...)`. The existing rules keep Garmin first for sleep duration, sleep score, resting HR and RMSSD, Intervals first for readiness, the Garmin bounds and the latest-Intervals-row restriction.

- Sleep: `sleep_hours = round(seconds / 3600, 1)`. The source is `GARMIN_PERFORMANCE_SOURCE` or `INTERVALS_WELLNESS_SOURCE`. `sleep_date` is the observation day for Garmin and None for Intervals (unchanged output shape: the recovery `id` falls back to the latest wellness row).
- Sleep score: selected independently. A Garmin sleep duration with an Intervals score keeps the Intervals label, as today.
- Resting HR and readiness: the value as stored. A whole number is returned as an int, so the JSON shape is unchanged. The Garmin date is set as for sleep.
- HRV: the RMSSD observation. When none is selected, the newest in-bounds Garmin `HRV_WEEKLY_AVERAGE` is used with the source `"<Garmin label> (Wochenmittel)"`, its date, and `hrv_average = None`. SDNN is not a current-context value (unchanged).
- Averages: the observations of the selected provider (Intervals when nothing is selected), one per day (first input record, as `select_daily`), in `[today - 6, today]`, averaged by `recovery.rounded_average`. Values outside the kind's current-rule bounds are skipped, as the legacy Garmin averages skipped them (`source_policy.within_current_bounds`). Sleep averages use exact hours per day.

Intended differences to the legacy output:
- The Garmin sleep average no longer rounds each night to 0.1 h before averaging.
- The readiness average uses the selected provider instead of always Intervals.
- Garmin sleep from seconds now carries its date, so the recovery `id` follows the Garmin sleep night before the resting HR day.
- A Garmin sleep score without a Garmin duration is selected on its own; a zero-second Garmin night is not stored by the mapper, so Intervals sleep is used.
- Values that exist only in the raw view or only in wellness carrier fields disappear.
- Weekly HRV is labelled.

These are recorded in the characterization tests.

### D3 Personal baselines

`personal_recovery(wellness, garmin, profile, today, *, canonical)` keeps its signature. Only `sleep_regularity` still uses `wellness` and `garmin`, with a code comment pointing to #1419.

The groups are built per provider from each provider's own observations, with one value per day (the first input record):

| Provider | Kind | metric | measurement label |
|---|---|---|---|
| Intervals | SLEEP_DURATION | sleep | `sleepSecs` |
| Intervals | RESTING_HR | resting_hr | `restingHR` |
| Intervals | HRV_RMSSD | hrv | `RMSSD` |
| Intervals | HRV_SDNN | hrv | `SDNN` |
| Garmin | SLEEP_DURATION | sleep | `garmin_perf_fields.SLEEP_SECONDS` |
| Garmin | RESTING_HR | resting_hr | `garmin_perf_fields.RESTING_HEART_RATE` |
| Garmin | HRV_RMSSD | hrv | `garmin_perf_fields.HRV_NIGHT_AVERAGE` |

The values go through the existing `_add_record`, which keeps the window, the non-positive filter, the sleep ≤ 24 h rule and resting HR 20–230. The existing `_baseline` and `_sleep_deficits` follow unchanged. With `canonical=None` the baselines and deficits are empty. Weekly HRV is not a baseline series.

`_unavailable_context` (no Intervals snapshot) receives the canonical inputs, so Garmin baselines come from observations there too.

### D4 Morning check-in

`ManualMorningCheckinService` requires `GarminSleepObservations`. `local_assembly` always passes it; the observation port is configured in every production composition. `_sleep_ready` reads `read_garmin_sleep_day` and passes the day to `garmin_sleep_ready_for_checkin`, which still reads `source_freshness` from the Garmin view. That field is sync metadata, not a measurement (#1414). The `_FROM_SNAPSHOT` default branch is removed if it has no other caller.

### D5 Weekly HRV kind and mapper

- `MetricKind.HRV_WEEKLY_AVERAGE = "hrv_weekly_average"`: unit `ms`, validation bounds `(0, 500)` like RMSSD, current rule Garmin only with bounds 1–300.
- `garmin_fields.GARMIN_HRV_WEEKLY_ALIASES = ("hrvWeeklyAvg", "weeklyAvg")`. `garmin_performance_fields` reuses it.
- The Garmin health mapper adds the field to the `hrv` group as `PROVIDER_REPORTED` (a Garmin-computed aggregate). `MAPPER_VERSION` goes from 10 to 11, and the existing canonical backfill reprojects stored Garmin health records.
- `diagnostics/canonical_counts.py` stays unchanged: it counts only Intervals wellness kinds, and the weekly average is Garmin-only. The kind inventories pinned by tests (units, current rules, fixture counts) are updated.

### D6 Removals

These are removed when no caller remains:
- `canonical_recovery.prefer_canonical`;
- the `canonical_recovery_averages` module;
- `canonical_personal_recovery` (its reader is folded into D1);
- `recovery.garmin_recovery_metric`, `garmin_recovery_average` and `garmin_recovery_window_values`;
- `recovery_context` helpers that read raw Garmin;
- `garmin_performance_fields.HRV_WITH_WEEKLY_ALIASES`.

`recovery.dated_garmin_recovery_records` stays (daily health, planning recovery).

### D7 Tests

A test helper maps the existing raw Garmin and wellness fixtures through the real mappers (`map_garmin_health`, `map_intervals_wellness`) into observations and builds `CanonicalRecoveryInputs`. Existing characterization and recovery tests keep their fixtures and expectations, so they act as parity tests. Every changed expectation is commented as an intended D2/D3 difference.

New tests cover:
- the weekly HRV fallback and its label;
- Garmin-only inputs without a wellness day;
- None inputs;
- provider switch, gap and stale statuses;
- the mapper version and the weekly kind;
- morning readiness from observations only.

## Risks / Trade-offs

- [The Garmin mapper bump reprojects every stored Garmin health record once] → This uses the existing, tested backfill path with batch limits. Until reprojection completes, the table reader serves only current-version observations (`provider-normalization-and-provenance` reprojection continuity). So weekly HRV and other Garmin values can be briefly absent after the upgrade.
- [Values only present in raw views disappear] → This is the intended behavior of the cutover; #1416 handles compact-only snapshots with an athlete-triggered refetch.
- [Behavior differences break hidden consumers] → Keys are unchanged. Coach, HTTP and PWA tests and the e2e fixtures are run.

## Migration Plan

- No schema change.
- On deploy, the mapper version bump triggers the existing canonical reprojection.
- Rollback: an older build (mapper 10) reprojects again on its own version check. The `observations.metric` text `hrv_weekly_average` is ignored by readers that do not know the kind.

## Open Questions

None. Key naming is deferred to #1413 by decision.
