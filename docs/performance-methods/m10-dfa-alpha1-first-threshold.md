# M10 — First threshold heart rate from chest-strap RR intervals (DFA-α1)

- **Card:** M10
- **Card version:** 1
- **Method ID:** dfa-alpha1-first-threshold v2 (`backend/canonical/dfa_alpha1.py:METHOD_VERSION`), athlete-level value in `backend/performance/first_threshold_estimate.py` (#2131, C-008)
- **Status:** implemented (`backend/providers/fit_rr_mapping.py` reads the RR intervals); per-session result stored with the stream set, athlete-level estimate shown in the profile and the Coach context, adopted only by the athlete
- **Classification:** model estimate
- **Literature checked:** 2026-11-13
- **Review:** blocked

## Target construct

The heart rate at which the athlete's short-term scaling exponent alpha1 of
detrended fluctuation analysis (DFA-α1) of beat-to-beat intervals crosses 0.75,
read from chest-strap recordings of the athlete's own runs. In laboratory
incremental tests this heart-rate variability threshold lies close to the first
ventilatory threshold (R56, R58), the construct that LT1 stands for here
(R54). The result is a heart-rate estimate for the athlete to review, not a
ventilatory or lactate threshold measurement. Nothing writes
it into the profile except the athlete's explicit adoption, which stores it as
the first threshold with the origin `estimated` (`first_threshold_origin`).

Athlete decision (2026-11-10, #2131): write this card and list the method as
implemented, no longer as deferred.

## Formula and units

Per recording (`dfa_alpha1.first_threshold`, unit bpm):

1. **Segments:** the RR series (ms) arrives as gap-free segments; a dropout of
   the sensor starts a new one and a window never spans two segments.
2. **Artifacts:** a beat is dropped when it lies outside 300 to 2000 ms or
   differs by more than 20 % from the last accepted beat; after 5 beats in a
   row rejected only for that change, the new level is accepted.
3. **Detrending:** the artifact-free series of a segment is detrended with
   smoothness priors (R61), λ = 500, before windowing.
4. **Windows:** 120 s windows on the segment's own beat clock (running sum of
   the intervals, each limited to 0.3 to 2 s), starting every 30 s. A window is
   analysed when it holds at least 100 beats, at most 5 % of them artifacts, and
   at least 100 artifact-free beats, and when the mean heart rates of its two
   halves differ by at most 8 bpm.
5. **alpha1:** integrate the detrended series (minus its mean), cut it into
   boxes of n = 4 to 16 beats, remove a linear trend per box, take the
   root-mean-square fluctuation F(n) over all boxes of that size, and fit
   log F(n) against log n; alpha1 is the slope (R56, R60).
6. **Window heart rate:** 60 000 / mean RR (ms) of the window's artifact-free
   beats, in bpm.
7. **Crossing:** a least-squares line of alpha1 on window heart rate over all
   analysed windows; the estimate is the heart rate where it reaches 0.75,
   `(0.75 − intercept) / slope`, rounded to 0.1 bpm.
8. **Quality:** `good` with at least 20 windows, an artifact share (dropped
   beats of all beats) of at most 0.03 and R² of at least 0.5, else `low`.

Per athlete (`first_threshold_estimate.first_threshold_estimate`, unit percent
of the run threshold HR, "% LSHF"):

1. Take one stored result per run session of the last 60 days (the better
   quality, then the more windows, wins among records of one session); only
   `good` sessions qualify.
2. Express each as `estimate_bpm / run threshold HR in effect on the session's
   day × 100`, rounded to 0.1, so a later threshold change does not move it;
   a session without a known threshold HR or with a percent outside 40 to 100
   does not qualify.
3. With at least 3 qualifying sessions the athlete-level value is their median,
   rounded to 0.1. Its bpm is that percent of today's run threshold HR,
   rounded half up, and absent when no threshold HR is known.
4. The athlete-level quality is `good` with at least 5 sessions whose values
   spread at most 5 percentage points, else `low`.

## Sources

- **Threshold definition and agreement with VT1:** R56 (laboratory, running,
  gas exchange), R57 and R58 (perspective and update by the same group), R59
  (systematic review of DFA-α1 in endurance exercise).
- **DFA method:** R60. **Smoothness-priors detrending:** R61.
- **Chest-strap RR quality:** R62.
- **Target construct (LT1 and VT1):** R54, R55.

## Population and reference measurement

- R56: 17 male volunteers aged 19 to 52 without medical history, 15 analysed
  (two excluded for frequent atrial ectopy), incremental treadmill run, ECG
  RR series, gas-exchange VT1 as reference. Mean VT1 heart rate 152 bpm
  against 154 bpm at DFA-α1 0.75; no female participants.
- R58 summarises further studies in elite, recreational and cardiac
  populations; it is a narrative update by the same group, not an independent
  validation.
- R62: 25 participants, Polar H10 against ECG in an exhaustive cycling ramp:
  RR and heart rate agree closely, DFA-α1 shows a wider bias and limits of
  agreement, especially at high intensity.
- No study validates a threshold read from uncontrolled outdoor sessions of one
  athlete over weeks against a laboratory VT1.

## Protocol and data window

- Input: the `hrv` messages (number 78) of the FIT file of a run or ride whose
  heart rate source is a chest strap (`backend/providers/fit_rr_mapping.py`,
  `fit_activity_detail_mapping._first_threshold`); optical heart rate gives no
  result. At most 150 000 intervals per file. The RR series is an input only
  and is never stored, logged, exported or sent to the Coach.
- A stretch where the file clock runs more than 10 s ahead of the intervals is
  a dropout and starts a new segment.
- The result is computed once when the stream set is mapped and stored with it
  (`activity_detail_sets.dfa_alpha1`: estimate, windows, artifact share,
  quality, method version).
- Athlete level: run sessions of the last 60 days up to today. Rides keep a
  stored result but do not enter the athlete-level estimate.
- The protocol of R56 is a ramp to exhaustion; sessions here are whatever the
  athlete ran. A recording gives a result only when its windows cross
  alpha1 0.75 at all (stop rules below).

## Measurement error and uncertainty

- DFA-α1 is biased by artifacts. R58 reports minimal bias below 3 % corrected
  artifacts and a negligible shift of the threshold at 6 %; the per-window
  limit of 5 % and the `good` limit of 3 % follow that range.
- The Polar H10 DFA-α1 bias against ECG is larger than that of RR and heart
  rate and grows with intensity (R62); the threshold region sits at moderate
  intensity, but the error is not quantified for this athlete or other straps.
- The estimate comes from a regression over all steady windows, not from the
  rapid-change section used in R56, and from sessions of varying structure and
  fatigue; no uncertainty interval is computed. The 5 percentage point
  spread of `good` sessions is a consistency check, not a confidence interval.
- Heat, fatigue, hydration, caffeine, hard days before and cardiac drift shift
  heart rate and autonomic activity; they are not corrected.

## Bias and transferability

- R56 included only men and one running protocol; transfer to this athlete,
  to outdoor running, to hills and to cycling is not shown.
- Intervals, recoveries and steps larger than 8 bpm per half window are
  removed, so the regression sees mostly steady and ramped efforts; a recording
  without effort above LT1 yields no result rather than a biased one.
- A person with frequent ectopic beats can give an artifact-corrected series
  with distorted DFA-α1 (excluded in R56); the artifact share only partly
  catches this.
- A weak or absent alpha1 response in some people is not excluded; the
  falling-line and crossing rules reject such recordings but cannot detect a
  wrong crossing that looks plausible.

## Deviations from the studied procedure

- Windows start every 30 s instead of every 5 s (R56).
- The line is fitted over all steady windows, not over the section from 1.0 to
  below 0.5 (R56), so the estimate is a recording-wide regression.
- Artifact correction is a fixed 300 to 2000 ms and 20 % rule, not the Kubios
  "automatic method" (R56); windows above 5 % artifacts are rejected instead
  of corrected by interpolation.
- Detrending is the smoothness-priors method of Kubios with its default
  λ = 500 (R56, R61), implemented with a banded solver.
- The athlete-level value is a median of per-session estimates expressed as
  percent of the threshold HR; the literature reports single laboratory tests.
- Field recordings instead of a laboratory ramp with a metabolic cart.

## Minimum data and stop rules

- Per recording no result unless: at least 10 analysed windows; the highest
  window heart rate at least 10 bpm above the lowest; the lowest alpha1 at most
  0.65 and the highest at least 0.85 (0.75 ∓ 0.1); a fitted slope below zero;
  and an estimate inside the range of the observed window heart rates and
  within 60 to 220 bpm (outside it the record is refused and no result is kept).
- Athlete level: fewer than 3 qualifying `good` sessions in 60 days give no
  estimate, nothing is shown and nothing is sent to the Coach.
- A stored estimate is replaced only through the athlete's adoption; a changed
  estimate between display and adoption is refused (409).

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| Threshold alpha1 | 0.75 | source | Midpoint between 1.0 (fractal) and 0.5 (uncorrelated) used as the first threshold marker in R56; supported by R58. `dfa_alpha1.py:THRESHOLD_ALPHA1`. |
| Window length | 120 s | source | R56 used 2-minute windows. `WINDOW_S`. |
| Window stride | 30 s | product assumption | R56 recalculated every 5 s; 30 s keeps windows overlapping but cheaper. `STRIDE_S`. |
| Box sizes | 4 to 16 beats | source | R56 set the DFA-α1 window width to 4 ≤ n ≤ 16; method from R60. `BOX_SIZES`. |
| Detrending | smoothness priors, λ = 500 | source | R61 method; R56 kept the Kubios default λ = 500. `DETREND_LAMBDA`. |
| Linear trend per box | order 1 | product assumption | Usual DFA-1; the order is not stated in the accessible text of R56. `alpha1`. |
| Valid RR range | 300 to 2000 ms | product assumption | Physiological plausibility guard; not taken from a cited threshold. `MIN_RR_MS`, `MAX_RR_MS`. |
| Beat-to-beat change | more than 20 % from the last accepted beat | product assumption | Common ectopic-beat guard; value not verified in R56/R58. `MAX_BEAT_CHANGE`. |
| Re-anchor after rejected beats | 5 in a row | product assumption | One bad first beat must not reject a recording. `REANCHOR_AFTER`. |
| Maximum artifact share per window | 0.05 | product assumption | Between the 3 % and 6 % levels R58 reports as low bias. `MAX_WINDOW_ARTIFACT_SHARE`. |
| Minimum beats per window | 100 | product assumption | Enough beats for boxes up to 16 within a 2-minute window at the lowest plausible rates. `MIN_WINDOW_BEATS`. |
| Heart-rate step between window halves | at most 8 bpm | product assumption | Keeps steady and ramped windows, drops intervals and recoveries. `MAX_HALF_HR_STEP_BPM`. |
| Minimum analysed windows | 10 | product assumption | Fewer windows cannot give a stable line. `MIN_WINDOWS`. |
| Minimum heart-rate spread | 10 bpm | product assumption | A flat line cannot locate a crossing. `MIN_HR_SPREAD_BPM`. |
| Crossing margin | alpha1 reaches 0.65 and 0.85 | product assumption | A recording that never goes below and above 0.75 gives no extrapolated crossing. `CROSSING_MARGIN`. |
| Stored estimate bounds | 60 to 220 bpm, rounded to 0.1 | product assumption | `DFA_ESTIMATE_BOUNDS_BPM` of the canonical record. |
| RR input bounds | at most 150 000 intervals; dropout when the file clock is 10 s ahead | product assumption | `fit_rr_mapping.MAX_RR_INTERVALS`, `MAX_UNACCOUNTED_S`. |
| Heart rate source | chest strap only | product assumption | The validation in R62 covers a chest strap against ECG; optical heart-rate sources are not covered by the cited evidence. |
| Recording quality `good`, artifact share | at most 0.03 | source | R58: minimal DFA-α1 bias below 3 % artifacts. `GOOD_MAX_ARTIFACT_SHARE`. |
| Recording quality `good`, windows and fit | at least 20 windows, R² at least 0.5 | product assumption | `GOOD_MIN_WINDOWS`, `GOOD_MIN_R_SQUARED`. |
| Athlete-level window | 60 days | product assumption | Same window as M9 (`ESTIMATE_DAYS`); one training state. |
| Athlete-level sessions | at least 3 `good` run sessions | product assumption | `MIN_SESSIONS`; one session is not an estimate. |
| Athlete-level aggregate | median of percent of the run threshold HR on each day | product assumption | Robust to one bad session; unaffected by later threshold changes. |
| Athlete-level `good` | at least 5 sessions, spread at most 5 percentage points | product assumption | `GOOD_MIN_SESSIONS`, `GOOD_MAX_SPREAD_PCT`. |
| Stored percent bounds | 40 to 100 % LSHF | product assumption | `FIRST_THRESHOLD_PERCENT_BOUNDS` of the profile value. |

## Allowed statements

- "Estimate from chest-strap RR intervals (DFA-α1, research stage), not a
  laboratory value: 150 bpm, 87,2 % LSHF, 6 sessions, quality good."
- "Your runs of the last 60 days give an estimate of your first threshold; you
  can adopt it as the stored value in the profile."
- "No estimate yet: fewer than three good chest-strap runs with a clear
  alpha1 crossing in the last 60 days."
- A change of the adopted value is the athlete's own action with receipt and
  undo.

## Forbidden statements

- The estimate as a measured, laboratory or validated first threshold or VT1.
- An automatic adoption or a Coach adoption; the Coach may only suggest it.
- Zones, heart-rate caps or plans changed from the estimate without the
  athlete's adoption; after adoption the caps carry the source `estimated`.
- A statement on the anaerobic threshold (alpha1 0.5) or on fitness, form,
  readiness or injury risk from alpha1.
- An estimate from optical heart rate, from fewer sessions than the minimum or
  from a cycling session.

## Open points

- No comparison with a laboratory VT1, a lactate step test or a field test of
  this athlete; until then the athlete's review of this card stays open.
- R56 tested men on a treadmill ramp only; female participants, outdoor running
  and cycling remain unchecked.
- The artifact rules, window stride and regression over all windows are
  implementation choices; their effect on the estimate against the Kubios
  procedure of R56 is not measured.
- Quality limits (20 windows, R² 0.5, 5 sessions, 5 percentage points) are
  untested thresholds; real coverage from the athlete's recordings is not yet
  counted.
- Cycling results are stored but unused: no decision yet on a ride estimate.

<!-- BEGIN GENERATED CONSTANTS -->
## Code constants

| Constant | Value | Module | Code comment |
| --- | --- | --- | --- |
| `HRV_MESSAGE` | `78` | `backend/providers/fit_rr_mapping.py` |  |
| `MAX_RR_INTERVALS` | `150000` | `backend/providers/fit_rr_mapping.py` | A day of beats at 100 bpm; longer series belong to no single activity. |
| `MAX_UNACCOUNTED_S` | `10.0` | `backend/providers/fit_rr_mapping.py` | The file clock may run this far ahead of the intervals before a dropout is assumed. |
| `METHOD_VERSION` | `2` | `backend/canonical/dfa_alpha1.py` |  |
| `MIN_RR_MS` | `300.0` | `backend/canonical/dfa_alpha1.py` |  |
| `MAX_RR_MS` | `2000.0` | `backend/canonical/dfa_alpha1.py` |  |
| `MAX_BEAT_CHANGE` | `0.2` | `backend/canonical/dfa_alpha1.py` |  |
| `REANCHOR_AFTER` | `5` | `backend/canonical/dfa_alpha1.py` | After this many beats in a row rejected only for their change, the new level is taken as real: a bad first beat must not reject the whole recording. |
| `DETREND_LAMBDA` | `500.0` | `backend/canonical/dfa_alpha1.py` | Smoothness priors detrending strength (Kubios and the DFA-a1 studies use 500). |
| `WINDOW_S` | `120.0` | `backend/canonical/dfa_alpha1.py` |  |
| `STRIDE_S` | `30.0` | `backend/canonical/dfa_alpha1.py` |  |
| `BOX_SIZES` | `tuple(range(4, 17))` | `backend/canonical/dfa_alpha1.py` |  |
| `MAX_WINDOW_ARTIFACT_SHARE` | `0.05` | `backend/canonical/dfa_alpha1.py` |  |
| `MIN_WINDOW_BEATS` | `100` | `backend/canonical/dfa_alpha1.py` |  |
| `MAX_HALF_HR_STEP_BPM` | `8.0` | `backend/canonical/dfa_alpha1.py` |  |
| `THRESHOLD_ALPHA1` | `0.75` | `backend/canonical/dfa_alpha1.py` |  |
| `CROSSING_MARGIN` | `0.1` | `backend/canonical/dfa_alpha1.py` | The lowest alpha1 must reach this far below the threshold and the highest this far above it, so a recording that never crosses 0.75 gives no estimate. |
| `MIN_WINDOWS` | `10` | `backend/canonical/dfa_alpha1.py` |  |
| `MIN_HR_SPREAD_BPM` | `10.0` | `backend/canonical/dfa_alpha1.py` |  |
| `GOOD_MIN_WINDOWS` | `20` | `backend/canonical/dfa_alpha1.py` |  |
| `GOOD_MAX_ARTIFACT_SHARE` | `0.03` | `backend/canonical/dfa_alpha1.py` |  |
| `GOOD_MIN_R_SQUARED` | `0.5` | `backend/canonical/dfa_alpha1.py` |  |
| `ESTIMATE_DAYS` | `60` | `backend/performance/first_threshold_estimate.py` |  |
| `MIN_SESSIONS` | `3` | `backend/performance/first_threshold_estimate.py` |  |
| `GOOD_MIN_SESSIONS` | `5` | `backend/performance/first_threshold_estimate.py` | The estimate is good with this many sessions that agree within this spread (percentage points of the threshold HR); otherwise it is low. |
| `GOOD_MAX_SPREAD_PCT` | `5.0` | `backend/performance/first_threshold_estimate.py` |  |
| `SOURCE_LABEL` | `'Schätzung aus Brustgurt-RR-Intervallen (DFA-α1, Forschungsstand), kein Laborwert'` | `backend/performance/first_threshold_estimate.py` |  |
<!-- END GENERATED CONSTANTS -->
