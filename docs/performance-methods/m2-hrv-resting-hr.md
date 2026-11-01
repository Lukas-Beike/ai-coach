# M2 — Personal HRV and resting HR description

- **Card:** M2
- **Card version:** 3
- **Method ID:** personal-quartiles-v1
- **Status:** implemented on canonical inputs with the segment rule (#1428)
- **Classification:** descriptive statistic
- **Literature checked:** 2026-10-24
- **Review:** released 2026-11-01 (athlete)

## Target construct

Whether today's provider-reported HRV or resting HR lies below, within or above
the athlete's own recent comparison distribution, measured under comparable
conditions. It is a description of a personal history, not a recovery,
readiness or health state.

## Formula and units

`personal-quartiles-v1` (`backend/performance/personal_recovery.py`):

- Series are kept per provider and field: RMSSD (`hrv`, ms), SDNN (`hrvSDNN`,
  ms) and resting HR (bpm) are never merged.
- Comparison set: values on days from today − 42 to the day before the latest
  observation, and not before the latest measurement change (segment rule
  below). The latest value is excluded from its own baseline.
- Lower and upper quartile: `quantiles(prior, n=4, method="inclusive")`;
  median shown alongside.
- Position: `below` the lower quartile, `above` the upper quartile, otherwise
  `within`.
- Planned extension after review: `ln(RMSSD)` with RMSSD in ms;
  `mean(ln(RMSSD))` and `ln(mean(RMSSD))` are different methods.

## Sources

R7 and R8 (HRV-guided training: potential, no established performance
benefit), R9 (interpretation limits, rolling-baseline drift), R10 (device
agreement for nocturnal HRV and resting HR), R11 (measurement
standardisation).

## Population and reference measurement

R7: 40 recreational runners, morning 4-min supine RMSSD from a chest belt.
R8: 8 studies, 199 participants, mostly morning short-term recordings.
R10: 13 healthy adults (7 men, 6 women, 33 ± 9 years), 536 nights against
Polar H10 ECG processed in Kubios. Repeated nights of 13 people are not 536
independent participants. R11 is cardiology and rehabilitation guidance.

## Protocol and data window

Studied protocols: morning short-term recording after waking (R7, R8) or a
whole-night average from a wearable (R10). Provider values in this app are
already processed device outputs; their window (nocturnal, morning) is usually
not delivered. Data window: 42 days comparison, 83 days of history loaded.
R9 notes 7-day rolling means as current practice and no single recommended
window.

## Measurement error and uncertainty

R10, Garmin Fenix 6 nocturnal HRV against ECG: mean bias −1.84 ms, limits of
agreement −15.2 to +11.6 ms, mean absolute percentage error 10.5 %. Garmin
resting HR was not validated in R10 (no timestamp of its lowest window). No
error figures exist for the athlete's device model. Quartiles are not
uncertainty intervals.

## Bias and transferability

R10 covers specific device models at the firmware used during the study, in healthy adults; it does
not validate all Garmin models or later firmware. R11 comes from clinical
practice. HRV is non-specific: illness, alcohol, travel, sleep, cycle phase and
training all move it, and a higher value is not always better (R9). R10 has a
critical industry letter in response (see register). One R8 author declared
minor fees from wearable and HRV-app vendors; R10 declares government funding
and no competing interests.

## Deviations from the studied procedure

- No controlled measurement protocol: values come from provider summaries of
  unknown window, position and artefact handling.
- Quartile position is not the R7 rule (7-day rolling mean vs mean ± 0.5 SD)
  and is not used to prescribe training.
- Series are separated by provider and field; within a series, the method,
  aggregation and measurement context (#1418, #1420) mark segments. Providers
  rarely report them: Garmin HRV carries only the `overnight` window, Intervals
  values carry nothing.
- HRV and resting HR come from canonical observations per provider and
  measurement (#1411); Garmin's weekly HRV average is not a baseline series.

## Minimum data and stop rules

- Fewer than 14 earlier matching values: no position, reason "at least 14
  earlier matching nights required".
- 14 to 27 values: position `provisional`; 28 or more: `ok`.
- Latest value older than yesterday: stale, no current position.
- HRV must be positive; resting HR outside 20 to 230 bpm is excluded.
- Segment rule (restart): a change of method, aggregation or measurement
  context (device model, firmware, algorithm, sensor, window, protocol) within a
  provider series restarts the comparison. Only values since the latest change
  count; older values stay in the history and the change day is reported
  (`context_changed_on`) while it lies inside the 42-day window. Below 14 values
  since the change: no position, reason "Messkontext geändert; mindestens 14
  passende Nächte seitdem erforderlich." The rule covers HRV and resting HR, not
  sleep duration (M3).
- A switch between unknown and known metadata is a change. Without a reported
  device model a device change cannot be seen: `continuity` is `unknown` and
  shown as "Messkontext unbekannt"; the comparison is still made. The Coach
  receives continuity and the change day, not the provider's device text.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| Comparison window | 42 days | product assumption | Existing rule, `personal_recovery.py:83`; R9 names no single window, R7 used a 4-week reference. |
| History loaded | 83 days | product assumption | Existing rule, `personal_recovery.py:84`; covers the 42-day window plus display history. |
| Minimum earlier values for a position | 14 | product assumption | Existing rule, `personal_recovery.py:214`; no source fixes a minimum. |
| Values for status ok | 28 | product assumption | Existing rule, `personal_recovery.py:217`. |
| Quartile method | inclusive, n = 4 | product assumption | Existing rule, `personal_recovery.py:215`; the middle quartiles hold about half of the values by definition, so "outside" is not rare. |
| Current value counts as fresh | observed today or yesterday | product assumption | Existing rule, `personal_recovery.py:191`. |
| Resting HR plausibility | 20 to 230 bpm | product assumption | Existing filter, `personal_recovery.py:144`; data-entry guard, not a physiological range. |
| HRV plausibility | greater than 0 ms | product assumption | Existing filter, `personal_recovery.py:137`. |
| RMSSD and SDNN kept separate | yes | source | Different metrics; R8 pools them separately, R10 and R11 report RMSSD. |
| Measurement change | restart, 14 values since the change | product assumption | `_segment_start`, `personal_recovery.py:161`; R10 validates specific models and firmware; values across a device or window change are not assumed comparable. Chosen by the athlete 2026-11-01. |

## Allowed statements

- "Resting HR today is above your previous comparison distribution (42 days,
  26 earlier values, provisional)."
- "HRV (RMSSD, Garmin) is within the range of your earlier values (42 days)."
- "Not enough earlier values for a comparison: 9 of 14."
- "The latest HRV value is from three days ago."
- "The measurement context changed on 28 September; 4 of 14 values since then."

## Forbidden statements

- Recovery, readiness, fitness-to-train, overtraining or illness statements
  from HRV or resting HR alone.
- Green/red training clearance or an automatic training change.
- Describing the quartile range as a normal range or "outside" as an alarm.
- Claiming the athlete's device was validated because a study examined the same
  brand (R10).
- Merging RMSSD with SDNN, or nocturnal with morning values, without saying so.

## Open points

- Whether to add `ln(RMSSD)` and a 7-day rolling mean as the R7/R9 protocol
  family, with its own minimum coverage.
- Providers that report a device model; until then continuity stays unknown.
- Garmin resting HR has no validation data in R10.
