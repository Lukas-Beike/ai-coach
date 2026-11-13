# M5 — Short- and long-term session-RPE load

- **Card:** M5
- **Card version:** 1
- **Method ID:** smoothed-session-load v1 (`backend/performance/smoothed_load.py`, #1432)
- **Status:** implemented as an estimate on the M1 daily load
- **Classification:** model estimate
- **Literature checked:** 2026-10-24
- **Review:** released 2026-11-03 (athlete)

## Target construct

Exponentially smoothed subjective training load of this athlete: a short-term
curve (about one week) and a long-term curve (about six weeks) of the M1
session-RPE load per local day. They describe how load of the recent days
weighs against older load. They are not measured fitness, fatigue, form,
readiness or injury risk, and not the physiological fitness-fatigue model
itself (R17).

## Formula and units

`E_t = exp(−1/τ) × E_(t−1) + (1 − exp(−1/τ)) × L_t`, unit arbitrary units (AU).

- `L_t`: M1 load of local day t, the sum of all sessions of that day.
- τ = 7 days (short-term) and 42 days (long-term).
- Start state `E = 0` on the day before the first recorded session within the
  history window. A provider CTL, ATL or load value never initialises or
  corrects a curve.
- A day without any session is a rest day, `L_t = 0`, once the day has passed.
  The day of the last provider sync and later days without a session are open:
  no value, since the session may not have synced yet.
- A day with an unrated or invalid session is a gap: `L_t` is unknown, the
  state is held unchanged and no value is shown for that day.
- Values appear after a warm-up of 2τ days from the first recorded session
  (14 and 84 days); rounded to 0.1 AU only for output.
- Reference case for tests: loads 300 AU every second day for 100 days give the
  recursion value computed independently in `tests/test_smoothed_load.py`.

## Sources

R17 (fitness-fatigue family with two exponentially decaying responses), R1 (M1
input), R14 and R15 (no ACWR or ratio-based risk output). Card M1 holds the
input limits.

## Population and reference measurement

R17 modelled a runner's performance from training impulses; it does not
validate τ 7 and 42 or sRPE input, and no reference measurement exists for
this athlete. The 7- and 42-day values are the constants already used by the
planning scenarios (`backend/planning/season_preparation.py`), not individually
measured recovery times.

## Protocol and data window

Daily M1 AU of all sports, athlete-local days, from the first recorded session
in the history window through the period end. The window starts 168 days (4τ)
before the period, but never later than 251 days before today, so Coach and
load tab seed the same day and agree for the same date.
Local RPE first, a labelled provider RPE only without it (card M1).

## Measurement error and uncertainty

No uncertainty interval is computed. Every error of a session's RPE or elapsed
duration (card M1) carries into the curve, damped by the smoothing. The start
state biases early values low; the warm-up bounds this to about 14 % of the
start error (`exp(−2)`).

## Bias and transferability

R17 is a 1990 single-case model; its parameters differ by person. Strength and
functional sessions agree less with HR-based load (see README, newer work), and
sRPE is higher than momentary RPE (R2). Missing ratings lower the curve only
when treated as zero, which this method does not do.

## Deviations from the studied procedure

- The curves use sRPE AU, not training impulses based on HR.
- τ values are product assumptions, not fitted to this athlete.
- No performance model, no fitness-minus-fatigue difference and no ratio.

## Minimum data and stop rules

- No value before 2τ days after the first recorded session, per curve.
- No value on a gap day or an open day; the state is held.
- No sessions at all: status `insufficient_data`, reason `no_sessions`.
- No ACWR, ratio, difference, ramp, readiness or risk output, and no use as
  training-plan input (stop rule of Epic S).

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| Short-term τ | 7 days | product assumption | Matches the 7-day constant of the planning scenarios; chosen by the athlete on #1432. |
| Long-term τ | 42 days | product assumption | Matches the 42-day constant of the planning scenarios; chosen by the athlete on #1432. |
| Start state | 0 AU the day before the first session | product assumption | Own curve, never seeded from provider CTL/ATL. |
| Warm-up | 2τ days | product assumption | Leaves about 14 % of the start error. |
| Rest day | 0 AU for a past day without a session | product assumption | Needed for the decay; a missed sync is indistinguishable from a rest day. |
| Gap day | unrated or invalid session: state held, no value | product assumption | A missing rating is unknown, not zero (card M1). |
| History window | 168 days before the period, at the latest 251 days before today | product assumption | Warm-up of 84 days plus 84 days again: an established athlete has values from the first day, start error below 2 %. |
| Model form | `E_t = exp(−1/τ) E_(t−1) + (1 − exp(−1/τ)) L_t` | source | R17 exponential response. |

## Allowed statements

- "Kurzzeitbelastung 210 AU, Langzeitbelastung 180 AU (aus deinen bewerteten
  Einheiten, τ 7 und 42 Tage)."
- "Zwei Tage ohne Bewertung sind Lücken, dafür gibt es keinen Wert."
- "Die Kurven sind noch in der Einlaufphase."

## Forbidden statements

- Fitness, fatigue, form, freshness, readiness or injury or overtraining risk
  from the curves.
- A ratio or difference of short- and long-term load, or any ACWR.
- A comparison with or conversion to CTL, ATL, TSS, Garmin load or TRIMP.
- Automatic plan or workout changes from the curves.

## Open points

- τ 7 and 42 are not evaluated against this athlete's data; no observation
  phase has run.
- A replacement of the Garmin training-load balance (#1422) is not decided.
- TRIMP, further threshold or VO2max estimates, W′ balance and HRV-based
  recommendations stay deferred: no proven benefit or data basis. DFA-α1 is
  implemented on chest-strap RR intervals as its own method (M10) and does not
  feed this load.
- Passive CP/CS from everyday data (R16) stays unreleased and is checked
  separately against protocol tests (#1431).

<!-- BEGIN GENERATED CONSTANTS -->
## Code constants

| Constant | Value | Module | Code comment |
| --- | --- | --- | --- |
| `METRIC_ID` | `'smoothed_session_load'` | `backend/performance/smoothed_load.py` |  |
| `METHOD_ID` | `'smoothed-session-load'` | `backend/performance/smoothed_load.py` |  |
| `METHOD_VERSION` | `1` | `backend/performance/smoothed_load.py` |  |
| `UNIT` | `'AU'` | `backend/performance/smoothed_load.py` |  |
| `EVIDENCE_CARD` | `'docs/performance-methods/m5-smoothed-session-load.md'` | `backend/performance/smoothed_load.py` |  |
| `SHORT_TAU_DAYS` | `7` | `backend/performance/smoothed_load.py` |  |
| `LONG_TAU_DAYS` | `42` | `backend/performance/smoothed_load.py` |  |
| `WARMUP_TAUS` | `2` | `backend/performance/smoothed_load.py` |  |
| `METHOD_NOTE` | `"Short-term (tau 7 d) and long-term (tau 42 d) exponentially smoothed session-RPE load, from the ...` | `backend/performance/smoothed_load.py` |  |
| `LIMITS` | `'Smoothed subjective load, not measured fitness, fatigue, form or injury risk. No ratio of the tw...` | `backend/performance/smoothed_load.py` |  |
| `STATE_RATED` | `'rated'` | `backend/performance/smoothed_load.py` |  |
| `STATE_REST` | `'rest'` | `backend/performance/smoothed_load.py` |  |
| `STATE_GAP` | `'gap'` | `backend/performance/smoothed_load.py` |  |
| `STATE_OPEN` | `'open'` | `backend/performance/smoothed_load.py` |  |
| `STATE_NO_HISTORY` | `'no_history'` | `backend/performance/smoothed_load.py` |  |
<!-- END GENERATED CONSTANTS -->
