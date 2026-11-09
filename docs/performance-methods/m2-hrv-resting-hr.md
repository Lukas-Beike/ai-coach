# M2 — Personal HRV and resting HR description

- **Card:** M2
- **Card version:** 4
- **Method ID:** personal-quartiles-v1 (nightly value), rolling-lnrmssd-v1 (seven-day ln(RMSSD), #1772)
- **Status:** implemented on canonical inputs with the segment rule (#1428); seven-day ln(RMSSD) mean added (#1772)
- **Classification:** descriptive statistic
- **Literature checked:** 2026-11-07
- **Review:** released 2026-11-07 (athlete)

## Target construct

Whether today's provider-reported HRV or resting HR lies below, within or above
the athlete's own recent comparison distribution, measured under comparable
conditions. It is a description of a personal history, not a recovery,
readiness or health state.

## Formula and units

`personal-quartiles-v1` (`backend/performance/personal_recovery.py`):

- Series are kept per provider and measurement: RMSSD (ms), SDNN (ms) and
  resting HR (bpm) are never merged.
- Comparison set: values on days from today − 42 to the day before the latest
  observation, and not before the latest measurement change (segment rule
  below). The latest value is excluded from its own baseline.
- Lower and upper quartile: `quantiles(prior, n=4, method="inclusive")`;
  median shown alongside.
- Position: `below` the lower quartile, `above` the upper quartile, otherwise
  `within`.

`rolling-lnrmssd-v1` (`backend/performance/rolling_hrv.py`) reads the RMSSD
series of Garmin and any later non-Intervals provider; Intervals.icu values
are never an input:

- Window: the 7 days ending with the latest night (`observed - 6` to
  `observed`); missing nights stay missing.
- Seven-day mean: `m7 = mean(ln(RMSSD))` with RMSSD in ms over the window's
  nights. `mean(ln(RMSSD))` is not `ln(mean(RMSSD))`.
- Baseline: ln(RMSSD) of the nights in the 42 days before the window
  (`observed - 48` to `observed - 7`), so the current week never compares
  with itself; `b` is their mean, `s` their sample SD.
- Range: `b ± 0.5 s` (the smallest worthwhile change of R7 and R47).
- Position: `below` when `m7 < b - 0.5 s`, `above` when `m7 > b + 0.5 s`,
  otherwise `within`.
- Seven-day coefficient of variation: `CV = SD(window ln values) / m7 × 100`,
  shown as a number without rating.
- Output is back-transformed to ms (`exp(m7)`, `exp(b ± 0.5 s)`: geometric
  mean and range), rounded to 0.1 ms; CV to 0.1 %.
- Worked example: nights of 52, 48, 61, 45 and 55 ms in the window give
  `m7 = 3.949` (51.9 ms); 30 earlier nights with `b = 4.05` and `s = 0.16`
  give the range 53.0 to 62.2 ms, so the seven-day mean is `below`; CV 3.0 %.
- The ln transform belongs to this method only; quartile positions of the
  nightly comparison would not change under a monotonic transform.
- Nothing is stored; the comparison is computed on read.

## Sources

R7 and R8 (HRV-guided training: potential, no established performance
benefit), R9 (interpretation limits, rolling-baseline drift), R10 (device
agreement for nocturnal HRV and resting HR), R11 (measurement
standardisation), R47 (seven-day rolling ln(RMSSD) and its CV), R48 (at least
3 valid days per week), R49 (log transform and weekly means), V6 (Garmin HRV
status and resting HR definition).

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
window. R47 and R48 studied trained or elite triathletes with morning
recordings; in R48 standardised changes plateau after 3 to 4 random days per
week.

Garmin's resting HR is, per its device manuals (V6), the lowest 30-minute
average heart rate within 24 hours, which usually falls into sleep; it is not
an awake supine morning measurement. Garmin's HRV status compares a
seven-night average of overnight HRV with a slowly adapting personal baseline
that needs about three weeks; Garmin publishes no formula, so
`rolling-lnrmssd-v1` is not a reproduction of it.

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
  and is not used to prescribe training. `rolling-lnrmssd-v1` follows the R7
  comparison but on whole-night device values instead of a morning 4-min
  recording, with a 42-day baseline before the window instead of R7's fixed
  4-week reference, and it prescribes nothing.
- Series are separated by provider and field; within a series, the method,
  aggregation and measurement context (#1418, #1420) mark segments. Providers
  rarely report them: Garmin HRV carries only the `overnight` window, and values
  stored earlier from Intervals.icu carry nothing.
- HRV and resting HR come from canonical observations per provider and
  measurement (#1411); Garmin's weekly HRV average is not a baseline series.

## Minimum data and stop rules

- Fewer than 14 earlier matching values: no position, reason "at least 14
  earlier matching nights required".
- 14 to 27 values: position `provisional`; 28 or more: `ok`.
- Latest value older than yesterday: stale, no current position.
- HRV must be positive; resting HR outside 20 to 230 bpm is excluded.
- `rolling-lnrmssd-v1`: fewer than 3 nights in the window gives no comparison,
  reason "Mindestens 3 Nächte in den letzten 7 Tagen erforderlich."; fewer
  than 14 baseline nights, reason "Mindestens 14 frühere passende Nächte vor
  den letzten 7 Tagen erforderlich."; status `ok` with at least 5 window and
  28 baseline nights, otherwise `provisional`. A stale latest value gives no
  comparison. The segment rule applies to window and baseline: only nights
  since the latest change count (reason "Messkontext geändert; mindestens 14
  passende Nächte vor den letzten 7 Tagen seitdem erforderlich.").
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
| Comparison window | 42 days | product assumption | Existing rule, `personal_recovery()` cutoff in `personal_recovery.py`; R9 names no single window, R7 used a 4-week reference. |
| History loaded | 83 days | product assumption | Existing rule, `personal_recovery()` history start in `personal_recovery.py`; covers the 42-day window plus display history. |
| Minimum earlier values for a position | 14 | product assumption | Existing rule, `_baseline` in `personal_recovery.py`; no source fixes a minimum. |
| Values for status ok | 28 | product assumption | Existing rule, `_baseline` in `personal_recovery.py`. |
| Quartile method | inclusive, n = 4 | product assumption | Existing rule, `_baseline` in `personal_recovery.py`; the middle quartiles hold about half of the values by definition, so "outside" is not rare. |
| Current value counts as fresh | observed today or yesterday | product assumption | Existing rule, `_baseline` in `personal_recovery.py` (`current`). |
| Resting HR plausibility | 20 to 230 bpm | product assumption | Existing filter, `_add_record` in `personal_recovery.py`; data-entry guard, not a physiological range. |
| HRV plausibility | greater than 0 ms | product assumption | Existing filter, `_add_record` in `personal_recovery.py`. |
| RMSSD and SDNN kept separate | yes | source | Different metrics; R8 pools them separately, R10 and R11 report RMSSD. |
| Seven-day window | 7 days ending with the latest night | source | R7, R47 (7-day rolling mean of ln(RMSSD)). |
| Minimum window nights | 3 | source | R48: at least 3 valid days per week. Chosen by the athlete 2026-11-07. |
| Window nights for status ok | 5 | product assumption | R48 shows little gain beyond 3 to 4 days; 5 marks a well-covered week. Chosen by the athlete 2026-11-07. |
| Rolling baseline | 42 days before the window; 14 nights minimum, 28 for ok | product assumption | Same counts as the nightly comparison; R7 used a 4-week reference; the current week is excluded. Chosen by the athlete 2026-11-07. |
| Range width | baseline mean ± 0.5 SD of ln(RMSSD) | source | R7, R47 (smallest worthwhile change). |
| Seven-day CV | shown without rating | product assumption | R47 describes the CV as an additional observation; no threshold exists. Chosen by the athlete 2026-11-07. |
| Measurement change | restart, 14 values since the change | product assumption | `_segment_start` in `personal_recovery.py`; R10 validates specific models and firmware; values across a device or window change are not assumed comparable. Chosen by the athlete 2026-11-01. |

## Allowed statements

- "Resting HR today is above your previous comparison distribution (42 days,
  26 earlier values, provisional)."
- "HRV (RMSSD, Garmin) is within the range of your earlier values (42 days)."
- "Not enough earlier values for a comparison: 9 of 14."
- "The latest HRV value is from three days ago."
- "The measurement context changed on 28 September; 4 of 14 values since then."
- "The seven-day mean of your HRV (5 nights, 51.9 ms) lies below your range
  from the 42 days before (53.0 to 62.2 ms)."
- "HRV varied by 3.0 % over the last 7 days."

## Forbidden statements

- Recovery, readiness, fitness-to-train, overtraining or illness statements
  from HRV or resting HR alone.
- Green/red training clearance or an automatic training change.
- Describing the quartile range as a normal range or "outside" as an alarm.
- Calling the seven-day range a normal or healthy range, a seven-day mean
  below it a recovery deficit, or the CV good or bad.
- Presenting the seven-day comparison as Garmin's HRV status.
- Claiming the athlete's device was validated because a study examined the same
  brand (R10).
- Merging RMSSD with SDNN, or nocturnal with morning values, without saying so.

## Open points

- Providers that report a device model; until then continuity stays unknown.
- Garmin resting HR has no validation data in R10.
