# M7 — Local fitness, fatigue and form

- **Card:** M7
- **Card version:** 2
- **Method ID:** local-fitness-fatigue v1 (#1726)
- **Status:** implemented (`backend/performance/fitness_fatigue.py`)
- **Classification:** model estimate
- **Literature checked:** 2026-11-06
- **Review:** released 2026-11-08 (athlete)

## Target construct

Two exponentially smoothed curves of this athlete's local TSS-scale load
(card M6) per local day: a long-term curve (fitness, about six weeks) and a
short-term curve (fatigue, about one week), and their difference (form). They
replace the Intervals.icu CTL, ATL and form as the app's load curves. They
describe how recent load weighs against older load on the TSS scale. They are
not measured fitness, fatigue, readiness or performance, and not a race-time
or injury-risk prediction (R17, R22).

Athlete decisions (2026-11-06, #1726):

- Local fitness, fatigue and form from the M6 load, not M5 only.
- Computed on read from the stored per-session load, never stored.
- Never initialised, corrected or mixed with Intervals.icu CTL, ATL or form;
  the stored Intervals series are not shown (athlete decision 2026-11-07).
- A session without a local load adds nothing and marks its day incomplete.

## Formula and units

`E_t = exp(−1/τ) × E_(t−1) + (1 − exp(−1/τ)) × L_t`, unit TSS per day.

- `L_t`: the sum of the stored M6 loads of the sessions on local day t.
- τ = 42 days (fitness) and 7 days (fatigue).
- Form = fitness − fatigue of the same day, as Intervals.icu and the planning
  scenarios (`backend/planning/season_preparation.py`) define it.
- Start state `E = 0` on the day before the first day with a stored local
  load in the whole stored history.
- A past day without any session is a rest day, `L_t = 0`. The day of the
  last provider sync and later days without a session are open: no value,
  state unchanged, since a session may not have synced yet.
- A day with a session that has no local load (yoga, alpine ski, unrated or
  uncalibrated strength, or no complete branch inputs, card M6) adds nothing for that
  session. The day is marked `incomplete` with the number of such sessions
  and their rated session-RPE AU (card M1) beside, never converted to TSS.
- Values appear after a warm-up of 2τ days from the first load day (84 days
  for fitness, 14 for fatigue; form needs both). Each day is computed in full
  precision and rounded to 0.1 only for output.
- The result carries `incomplete_days` (days in the served window with state
  `incomplete`) and `incomplete_share` (that count over all days of the
  window, 0 to 1, rounded to 3 decimals). The load-tab chart shows it as
  "N % der Tage unvollständig" only above 0.
- TrainingPeaks conventions differ: its gain is 1/τ, this app uses
  1 − e^(−1/τ), so the values differ slightly; form is computed here with
  the same day's fitness and fatigue.
- Reference case for tests: 80 TSS every second day for 120 days gives the
  recursion values computed independently in `tests/test_fitness_fatigue.py`.

## Sources

R17 (fitness-fatigue family with two exponentially decaying responses), R20
(TSS relates to fitness change in cyclists), R22 (load series of different
methods evolve differently in the fitness-fatigue model). Card M6 holds the
limits of the input load; card M5 the same recursion on AU.

## Population and reference measurement

R17 modelled one runner's performance from training impulses; it does not
validate τ 42 and 7 or TSS input. R20: 15 well-trained road cyclists over
10 weeks. R22: 9 participants over 8 weeks. No reference measurement exists
for this athlete. τ 42 and 7 are the constants of the planning scenarios and
of M5, and the common CTL/ATL convention, not individually fitted.

## Protocol and data window

- Input: the stored M6 load per local day over the whole stored history
  (`LocalLoadDayReader`), from the first day with a load through the period
  end. Sessions of the period mark the incomplete days.
- The load tab shows the last 84 days; the Coach training report the report
  period of all-sport reports. Both read the same stored loads.
- The Coach load block (`current_load`, last 7 days with averages), the
  fitness, fatigue and form comparisons, the progress report and block review
  (`ctl` first and last of the window), and the daily planning context read the same curve
  (#1726). The stored Intervals.icu values are not shown.
- The Coach comparison of the last 7 days' load with the 7 days before is
  neutral (no good or bad colour) and carries the counts of sessions without a
  load for both weeks; with any such session it has no delta, direction or
  colour.

## Measurement error and uncertainty

No uncertainty interval is computed. Every error of the session load (card
M6: FTP error, branch mix, HR TRIMP CV) carries into both curves, damped by the
smoothing. The start state biases early values low; the warm-up bounds this to
about 14 % of the start error (`exp(−2)`). Sessions without a load lower the
curves; their count stays visible.

## Bias and transferability

R17 is a 1990 single-case model; its parameters differ by person. The M6
branches are not equivalent (R21, R22), so a curve over sessions of different
branches mixes their errors. Almost all TSS evidence comes from cyclists.
Intervals.icu computes its CTL from its own loads and settings; the local
curve differs from it by design and is never compared with it as a check.

## Deviations from the studied procedure

- The input is the local TSS-scale load (M6), not R17's HR-based training
  impulse.
- τ values are product assumptions, not fitted to this athlete.
- No performance model: no fitted gains, no predicted performance.

## Minimum data and stop rules

- No value before 2τ days after the first load day, per curve; no form before
  both curves have values.
- No value on an open day; the state is held.
- No stored load at all: status `insufficient_data`, reason `no_load`; only
  warm-up days: reason `warmup`.
- No performance, race-time, readiness or injury-risk output, and no automatic
  plan or workout change.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| Model form | `E_t = exp(−1/τ) E_(t−1) + (1 − exp(−1/τ)) L_t` | source | R17 exponential response. |
| Fitness τ | 42 days | product assumption | Common CTL convention; same constant as the planning scenarios and M5; athlete decision 2026-11-06. |
| Fatigue τ | 7 days | product assumption | Common ATL convention; same constant as the planning scenarios and M5; athlete decision 2026-11-06. |
| Form | fitness − fatigue, same day | product assumption | Matches the Intervals.icu definition and `backend/planning/season_preparation.py`; athlete decision 2026-11-06. |
| Start state | 0 the day before the first load day of the whole history | product assumption | Own curve, never seeded from a provider CTL or ATL; athlete decision 2026-11-06. |
| Warm-up | 2τ days | product assumption | Leaves about 14 % of the start error. |
| Rest day | 0 for a past day without a session | product assumption | Needed for the decay; a missed sync is indistinguishable from a rest day. |
| Open day | from the last sync day on without a session: no value, state held | product assumption | Same rule as M5. |
| Session without load | adds nothing, day marked incomplete with count and sRPE AU | product assumption | Athlete decision 2026-11-06; M6 forbids a provider load or a conversion as fallback. |

## Allowed statements

- "Lokale Fitness 52, Ermüdung 61, Form −9 (aus deiner lokalen TSS, τ 42
  und 7 Tage)."
- "Am Dienstag fehlt die Krafteinheit in der Kurve (keine TSS, 270 AU
  daneben)."
- "Die Fitnesskurve ist noch in der Einlaufphase."

## Forbidden statements

- Mixing, blending or comparing the local curves with Intervals.icu CTL, ATL
  or form, or filling local gaps with Intervals values.
- Performance, race-time, readiness, injury- or overtraining-risk statements
  from the curves or from form (R17, R22).
- A ramp rate, ratio or ACWR from the curves.
- Treating a session without a local load as zero load in words.
- Automatic plan or workout changes from the curves.

## Open points

- τ 42 and 7 are not evaluated against this athlete's data; no observation
  phase has run.
- No new literature search ran for this card; it relies on the register
  entries checked for M5 and M6.

<!-- BEGIN GENERATED CONSTANTS -->
## Code constants

| Constant | Value | Module | Code comment |
| --- | --- | --- | --- |
| `METRIC_ID` | `'local_fitness_fatigue'` | `backend/performance/fitness_fatigue.py` |  |
| `METHOD_ID` | `'local-fitness-fatigue'` | `backend/performance/fitness_fatigue.py` |  |
| `METHOD_VERSION` | `1` | `backend/performance/fitness_fatigue.py` |  |
| `UNIT` | `'TSS/d'` | `backend/performance/fitness_fatigue.py` |  |
| `EVIDENCE_CARD` | `'docs/performance-methods/m7-local-fitness-fatigue.md'` | `backend/performance/fitness_fatigue.py` |  |
| `SOURCE_LABEL` | `'Lokal berechnet (M7)'` | `backend/performance/fitness_fatigue.py` | The source label every consumer of the curve shows. |
| `FITNESS_TAU_DAYS` | `42` | `backend/performance/fitness_fatigue.py` |  |
| `FATIGUE_TAU_DAYS` | `7` | `backend/performance/fitness_fatigue.py` |  |
| `METHOD_NOTE` | `'Fitness (tau 42 d), fatigue (tau 7 d) and form (fitness minus fatigue) from the local TSS-scale ...` | `backend/performance/fitness_fatigue.py` |  |
| `LIMITS` | `'Model estimate from the local load, not measured fitness, fatigue or readiness and no performanc...` | `backend/performance/fitness_fatigue.py` |  |
| `STATE_LOADED` | `'loaded'` | `backend/performance/fitness_fatigue.py` |  |
| `STATE_INCOMPLETE` | `'incomplete'` | `backend/performance/fitness_fatigue.py` |  |
| `STATE_REST` | `'rest'` | `backend/performance/fitness_fatigue.py` |  |
| `STATE_OPEN` | `'open'` | `backend/performance/fitness_fatigue.py` |  |
| `STATE_NO_HISTORY` | `'no_history'` | `backend/performance/fitness_fatigue.py` |  |
<!-- END GENERATED CONSTANTS -->
