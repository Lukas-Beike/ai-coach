# M3 — Sleep duration, goal shortfall and timing

- **Card:** M3
- **Card version:** 3
- **Method ID:** personal-quartiles-v1 (duration and goal shortfall), sleep-timing-variability-v2 (timing)
- **Status:** implemented on canonical sleep observations and periods (#1429)
- **Classification:** descriptive statistic
- **Literature checked:** 2026-10-24
- **Review:** version 2 released 2026-10-26 (athlete); version 3 implements its stop rule without a new claim

## Target construct

Device-estimated sleep duration, the known shortfall against the athlete's own
explicit sleep goal, and how far sleep onset and wake times deviate from the
athlete's own earlier clock times. It is not measured sleep need, physiological sleep
debt, sleep quality or a sleep diagnosis.

## Formula and units

- Duration: the provider's device-estimated sleep duration in hours, per
  provider and field, from canonical sleep duration observations.
- Goal shortfall (`backend/performance/personal_recovery.py:170-199`): with a
  goal of 4 to 12 h, `sum(max(0, goal_h − duration_h))` over known nights from
  today − 6 to today, in hours, rounded to 0.01 h after summing.
- Timing (`sleep-timing-variability-v2`, `personal_recovery.py:sleep_timing_variability`):
  local onset and wake clock times in minutes after midnight. Circular median
  over 1,440 minutes of the earlier intervals in the 42-day window; per night
  the absolute circular deviation from that median, rounded to 0.1 min. With
  fewer than 14 earlier intervals there is no median and no deviation (v2;
  v1 computed both from any number).
- This timing deviation is not the Sleep Regularity Index (SRI). SRI (R13) is
  the probability that two time points 24 h apart have the same sleep/wake
  state, from 1-min epochs including naps, rescaled to −100..100. The two keep
  different names.

## Sources

R12 (individual sleep need, wearable measurement limits), R13 (original SRI).
L1 is background only. Newer work: two open-source SRI calculators gave
substantially different scores (Czeisler et al. 2026, see README).

## Population and reference measurement

R12: expert consensus and narrative review for athletes; wearable statements
are against polysomnography. R13: 61 analysed Harvard undergraduates with
about 30 days of sleep diaries; diary-based, no wearable. No source validates
the athlete's device for sleep duration or onset/wake timing.

## Protocol and data window

Duration comes from canonical sleep duration observations, timing from
canonical sleep periods; no raw provider row is read. Timing uses intervals
longer than 0 and at most 24 h whose local end date is within the last 83
days; the comparison set is the earlier intervals in the last 42 days. The
goal shortfall uses the last 7 local days. The local timezone is the athlete's
configured timezone.

## Measurement error and uncertainty

R12: research-grade and consumer devices overestimate sleep duration and
underestimate wake after sleep onset versus polysomnography, and do worse in
fragmented sleep. No error figure is available for the athlete's device. The
shortfall sum has no uncertainty interval. It is bookkeeping over recorded
duration on known nights only: missing nights leave it incomplete, unrecorded
naps can make it larger than a shortfall of total sleep, and device error has
no known direction.

## Bias and transferability

R13 associations were found in students and concern academic performance and
circadian timing; they do not transfer to individual athlete prognosis. R12
recommends individual needs over a blanket 7-9 h target. Daytime naps are
usually absent from the provider data used here. R13 authors and one R12
author declare ties to wearable and sleep-technology makers; L1's author
declares lighting-industry funding.

## Deviations from the studied procedure

- No polysomnography or diary; device estimates only.
- Timing deviation uses one main interval per night, not a sleep/wake series
  with naps, so it cannot be an SRI.
- The goal is entered by the athlete, not derived from measured need.
- Sleep duration comes from canonical observations (#1411), timing from
  canonical sleep periods only (#1419, #1429). The periods hold the intervals
  v1 read from provider rows (`backend/canonical/sleep_bounds.py`), with the
  same field precedence; providers and field pairs stay apart, each interval
  is dated by its end in the profile zone and the latest interval of a day is
  kept; parity is pinned in
  `tests/test_sleep_timing_variability_canonical_parity.py`.
- Coverage limits: only intervals with both a start and an end field are read;
  Garmin's main daily sleep is stored as NIGHT and every other interval as
  UNKNOWN, but both count, as in v1. Naps are not collected. A night whose
  provider row was never stored is missing, never estimated.

## Minimum data and stop rules

- No goal, or a goal outside 4 to 12 h: no shortfall statement; "no goal set"
  is a valid state.
- Shortfall status `ok` only with 7 known nights, otherwise `partial` with the
  known count.
- Timing: fewer than 14 earlier intervals gives status `insufficient_data`
  with no median and no deviation; 14 to 27 is `provisional`; 28 or more is
  `ok`.
- Durations above 24 h and non-positive values are excluded.
- SRI enters scope only with a sufficiently complete sleep/wake series
  including daytime segments, and with the exact calculator named.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| Valid sleep goal | 4 to 12 h | product assumption | Existing rule, `personal_recovery.py:177`; input guard, not a recommended range. |
| Shortfall window | 7 days | product assumption | Existing rule, `personal_recovery.py:184`; one week of bookkeeping. |
| Shortfall status ok | 7 known nights | product assumption | Existing rule, `personal_recovery.py:195`. |
| Maximum sleep interval | 24 h | product assumption | Existing filters, `personal_recovery.py:97` and `:324`; data guard. |
| Timing comparison window | 42 days | product assumption | Existing rule, `personal_recovery.py:373`; same window as M2. |
| Timing history loaded | 83 days | product assumption | Existing rule, `personal_recovery.py:327`. |
| Minimum earlier intervals | 14 | product assumption | Existing rule, `personal_recovery.py:377`; no source fixes a minimum. |
| Intervals for status ok | 28 | product assumption | Existing rule, `personal_recovery.py:379`. |
| Shortfall rounding | 0.01 h after summing | product assumption | Existing rule, `personal_recovery.py:192-193`; display precision only. |
| Deviation rounding | 0.1 min | product assumption | Existing rule, `personal_recovery.py:361`; display precision only. |
| Circular day length | 1,440 min | source | Clock time wraps at midnight; R13 also uses 24-h comparison. |
| No blanket sleep target | individual goal only | source | R12 recommends individual sleep needs over 7-9 h for everyone. |

## Allowed statements

- "Garmin estimates 6.4 h of sleep last night."
- "Below your 8 h goal by 3.5 h in total over 6 known nights this week."
- "You fell asleep 75 minutes later than the median of your earlier nights
  (42 days, 31 earlier nights)."
- "No sleep goal set, so no shortfall is shown."

## Forbidden statements

- "Sleep debt" or "you need X more hours" as a measured physiological quantity.
- Calling the timing deviation a Sleep Regularity Index or SRI.
- Sleep stage, sleep quality or disorder statements from these values.
- A blanket 7-9 h (or any) target presented as the athlete's need.
- Health or performance prognoses from irregular timing (R13 is
  associational).

## Open points

- Naps are out of scope for the canonical model (athlete decision 2026-10-25).
- SRI stays out of scope until a full sleep/wake series exists; then name the
  calculator and settings.
