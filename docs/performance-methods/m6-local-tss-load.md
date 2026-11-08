# M6 — Local TSS-scale session load and intensity

- **Card:** M6
- **Card version:** 5
- **Method ID:** local-tss-load v5 (#1725, v2 #1726, v3 #1774, v4 #1771, v5 #1773)
- **Status:** implemented (`backend/performance/local_tss.py`, `backend/sync/local_load.py`)
- **Classification:** model estimate
- **Literature checked:** 2026-11-08
- **Review:** released 2026-11-08 (athlete)

## Target construct

A training-stress estimate per completed session, on the TSS scale, where one
hour at the athlete's threshold scores about 100, plus the session's intensity
factor. It comes from the session summary and the thresholds in effect on the
session's day. The sessions sum to the day, week and period load of the
rollups and of the local fitness and fatigue curves (#1726). It is not
measured fatigue, readiness, metabolic stress or injury risk, and not the
session-RPE load M1.

Athlete decisions (2026-11-06, comments on #1725):

- TSS and IF are always computed locally, for every session, with this one
  method and the local thresholds from the resolver.
- Provider loads and intensities are never used as the load and are at most
  kept for cross-checking:
  - Intervals.icu `icu_training_load` and `icu_intensity`;
  - Wahoo `power_bike_tss_last`;
  - Garmin `activityTrainingLoad`, which is EPOC-based;
  - Garmin `trainingStressScore`/`intensityFactor`, which are not mapped.
- Each value is stored as a derived observation owned by its canonical
  session.
- Fitness, fatigue and form (#1726) stay computed on read.

Athlete decisions for v2 (2026-11-06, #1726):

- Strength gets a load from its session-RPE load (card M1) times the
  athlete's own TSS per AU, because heart rate misses the load of strength
  work, leg training in particular.
- The factor is the median `TSS / AU` of the rated ride and run sessions with
  a local load of the 365 days up to the session day, from at least 20 pairs.
  Only local feedback and Garmin device ratings calibrate; ratings relayed by
  Intervals.icu do not.
- Walking takes the heart-rate branch like hiking. Yoga and alpine ski keep no
  value.

Athlete decisions for v3 (2026-11-07, #1774):

- The heart-rate branch takes its TRIMP constants from the profile setting
  `sex`: male `0.64·e^(1.92·HRr)`, female `0.86·e^(1.67·HRr)`.
- Without a saved value it uses the male constants and marks the value
  `sex_assumed` ("Geschlecht nicht gesetzt, männliche Konstanten angenommen").
  The athlete is male (confirmed 2026-11-07).
- The value is not prefilled from Garmin or Wahoo; the athlete sets it once in
  the profile.

Athlete decisions for v4 (2026-11-07, #1771, after the science review of
2026-11-07):

- The strength factor comes from rides and runs of similar effort: the pairs
  whose RPE lies within 1 of the strength session's RPE, widened to 2 when
  fewer than 20 pairs qualify; otherwise the session has no value. One median
  over all pairs let the many easy sessions set the factor, because
  `TSS / AU = 100·IF² / (60·RPE)` falls with intensity, and over-scored
  strength sessions (RPE 6-8) by an estimated 30-50 %.
- A calibration pair uses one duration for both sides: its AU is computed with
  the same duration as its TSS (moving, else elapsed). The stored M1 AU of the
  session is unchanged.
- The factor per RPE, the band used and the split of the pairs by rating
  source (local feedback, Garmin watch) are kept with each strength value and
  served to the Coach; the app view is unchanged.

Athlete decisions for v5 (2026-11-08, #1773, after the science review of
2026-11-07):

- The heart-rate branch sums the TRIMP over the session's heart-rate
  distribution instead of taking the TRIMP of the average HR (R52, Manzi's
  per-second idea): the exponential weight makes the average understate
  sessions with a high-intensity part.
- A session whose heart-rate samples cover less than 80 % of its TSS duration
  keeps the average-HR TRIMP, and so does a session without a stored
  distribution.
- A threshold observed more than 90 days after the session no longer stands in
  for it; the session is treated as having no threshold.

## Formula and units

One versioned method with four branches. Endurance sessions try the first
three in a fixed order and take the first whose inputs are complete; strength
uses only the fourth. The value records which branch gave it
(`load_branch`).

1. **Power** (ride and run):
   `IF = NP / FTP`,
   `TSS = duration_s × NP × IF / (FTP × 3600) × 100 = hours × IF² × 100`.
   - `NP`: the session's normalized power (W) from the canonical summary,
     computed by the device or provider. The app does not recompute it from
     streams.
   - `FTP`: the resolver's FTP for the session's sport on the session's local
     day. An indoor or virtual ride uses the locally confirmed indoor power
     zone in effect that day when one exists (athlete decision 2026-11-06);
     a provider indoor FTP is not read.
2. **Pace** (run only, without power):
   `IF = v / v_threshold`, `TSS = hours × IF² × 100`.
   - `v`: Garmin's grade-adjusted average speed (`avgGradeAdjustedSpeed`,
     m/s), otherwise the average speed. The Garmin key is not mapped yet;
     #1725 adds it in a new Garmin activity mapper version. Without it the
     value is marked `pace_basis: average_speed`.
   - `v_threshold`: the resolver's run threshold pace on the day, stored as
     m/s.
3. **Heart rate** (every sport except strength, yoga and alpine ski, without
   power or pace; walking included since v2):
   - `TSS = TRIMP_session / TRIMP_threshold_hour × 100`.
   - `TRIMP = minutes × HRr × a × e^(b × HRr)`, with `a = 0.64`, `b = 1.92`
     for men and `a = 0.86`, `b = 1.67` for women (v3). The prefactor `a`
     cancels in the ratio; `b` changes the value.
   - The sex comes from the profile. Without a saved value the male
     constants apply and the value is marked `sex_assumed`.
   - `HRr = (HR − HR_rest) / (HR_max − HR_rest)`.
   - `TRIMP_session` (v5) sums over the session's heart-rate distribution,
     the seconds `t_b` at each whole bpm `b` (moving samples only, gaps over
     5 s left out, readings of 30-240 bpm; stored by the session analysis):
     `TRIMP_session = Σ_b (t_b / 60) × HRr_b × a × e^(b × HRr_b) × D / C`,
     with `HRr_b = (b − HR_rest) / (HR_max − HR_rest)` clamped to 0-1,
     `C = Σ t_b` the covered seconds and `D` the TSS duration. The scale
     `D / C` carries the counted time to the whole session.
   - Coverage rule: with `C < 0.8 × D`, or without a stored distribution,
     `TRIMP_session` is the TRIMP of the session's average HR for `D`, as in
     v4. The value records `hr_basis` (`distribution` or `average`) and,
     when a distribution exists, `hr_coverage = C / D` and a hash of the
     distribution.
   - `TRIMP_threshold_hour` is 60 minutes at the threshold HR.
   - `HR_max` and the threshold HR are the resolver's values for the sport on
     the day. Ride uses ride values; run and every other HR sport use run
     values.
   - `HR_rest` is the resting HR of the session day, or of the nearest
     earlier day within 7 days, from the recovery family (Garmin first).
     Without one, the earliest later resting HR stands in, flagged
     `threshold_after_session` (athlete decision 2026-11-06), when that
     value was observed at most 90 days after the session day (v5).
4. **Session RPE** (strength only, v2; k matched by RPE since v4):
   `TSS = AU × k(RPE)`.
   - `AU`: the session-RPE load of card M1, elapsed minutes × RPE, from the
     local feedback RPE, else the provider rating of the session (Garmin).
   - Calibration pairs: the ride and run sessions with a local load (any
     branch) and a local or Garmin rating with RPE > 0, observed in the 365
     days up to the session day. Each pair has its RPE and
     `q = TSS / (duration_min × RPE)`, where `duration_min` is the duration
     its TSS used (moving, else elapsed), so both sides share one duration
     and `q = 100·IF² / (60·RPE)` for the power branch.
   - `k(RPE)`: the median `q` of the pairs with `|RPE_pair − RPE| ≤ 1`,
     needing at least 20 pairs; with fewer, the pairs with
     `|RPE_pair − RPE| ≤ 2`, again at least 20; otherwise no value
     (`not_calibrated`).
   - Worked example (synthetic): 30 easy rides, 60 min at IF 0.65 with RPE 2,
     give `q = 42.25 / 120 = 0.35`; 22 threshold runs, 50 min at IF 0.90 with
     RPE 7, give `q = 67.5 / 350 = 0.19`. A strength session of 60 min at RPE 7
     (420 AU) matches the 22 runs (band 6-8): `TSS = 420 × 0.19 = 80`. The v3
     median over all 52 pairs was 0.35 and gave 147.
   - Detail table: for every RPE 1-10 the median `q` and pair count of its
     ±1 band (factor only from 20 pairs), so the slope is visible.

Worked example for the heart-rate branch (v5, synthetic; rest 50, threshold
165, max 190, male, 60 min): 40 min at 100 bpm and 20 min at 160 bpm have an
average HR of 120. The average-HR TRIMP is `60 × 0.5 × 0.64 × e^(0.96) = 50.1`
against `60 × 0.8214 × 0.64 × e^(1.577) = 152.7` for the threshold hour, so
32.8. The distribution gives `40 × 0.357 × 0.64 × e^(0.686) = 18.1` plus
`20 × 0.786 × 0.64 × e^(1.509) = 45.5`, 63.6, so 41.7. A constant 120 bpm gives
32.8 both ways.

General rules:

- `duration_s` is the canonical session duration: moving, else elapsed.
- `IF` is stored for the power branch only: `intensity_pct = IF × 100`, so
  NP/FTP in percent. The pace IF is internal to the pace branch.
- TSS is unitless. Each session is computed in full precision; values are
  rounded only for display.
- The branches are not equivalent (R21, R22). A sum over sessions of
  different branches is shown with its branch counts.

### Storage

- **Observations.** Each session gets one derived observation for TSS and,
  for the power branch, one for IF.
  - `observed_on`: the session's local day.
  - `sport`: the session's sport.
  - `source_kind`: `derived`.
  - `method`: `local-tss-load`, `method_version`: 5.
  - The owner is the canonical session.
  - `details` hold the branch, the pace basis, and the thresholds used with
    their sources and dates; a heart-rate value also holds the sex the
    constants came from and `sex_assumed` when it was not set; a session-RPE
    value also holds `k`, its pair count, window and RPE band, the pairs by
    rating source (local feedback, Garmin) and the factor per RPE (v4).
- **Fingerprint.** `input_fingerprint` is the SHA-256 over the method
  version, branch, session inputs (for heart rate including the sex and
  whether it was assumed, the `hr_basis`, coverage and a hash of the
  distribution), thresholds and, for strength, the calibration.
- **Recompute.** A method version bump or a changed input gives a new
  fingerprint. A local, idempotent backfill then recomputes the affected
  sessions, so a corrected or backfilled threshold changes past values.
- **FTP changes.** A later FTP change does not reach past sessions, because
  their dated threshold is unchanged.
- **Session changes.** A session that disappears or merges retires its
  observations.
- **Rating changes.** A saved, changed or undone session RPE requests a pass,
  so strength values and the calibration follow it.
- **Distribution changes.** The distribution is stored with the canonical
  session analysis, which runs after the load pass. A newly stored or changed
  distribution changes the fingerprint, so the next pass recomputes the
  value.
- **Sex changes.** A saved or undone profile sex requests a pass; the
  heart-rate values get a new fingerprint and are recomputed, and M7 follows.

## Sources

- **Power branch:**
  - R18 is the origin of NP, IF and TSS. It is a book with an author
    interest, and its formula is confirmed only in the vendor text V1.
  - R20 relates TSS to fitness change.
  - R27-R29 cover the error and meaning of FTP.
- **Heart-rate branch:** R52 (TRIMP summed over the heart-rate distribution
  of the session, with individual weights; the card uses the Banister weights
  of R19, not the individual ones); R19 (Banister TRIMP; male and female constants not
  verified from the chapter; R25 prints 0.84 instead of 0.86 for the female
  prefactor, which cancels in the normalisation). V2 shows that the "one hour = 100" normalisation is a vendor
  convention without a peer-reviewed source.
- **Pace branch:** V1 (rTSS convention, formula not verified) and R30 (use
  case only). R25 is evidence against it.
- **Agreement and comparison limits:** R21-R24 and R31. R26 reports the
  reliability of HR-based scores.
- **Session-RPE branch:** R1 (session RPE as a load measure, card M1); R45
  and R46 support session RPE for resistance training. The conversion of AU
  into TSS by a personal factor has no source; it is a product assumption
  (v2). V1's TSS estimate from RPE (about 70 TSS per hour at RPE 6 in its
  worked example, i.e. 0.19 TSS per AU) is a vendor table, not a study; no
  platform publishes a validated strength conversion.

## Population and reference measurement

- R20: 15 well-trained road cyclists over 10 weeks, against the change in
  power at 2 and 4 mmol/L lactate.
- R21: 21 professional cyclists, 11,716 sessions, against energy expenditure
  in kJ.
- R22: 9 participants over 8 weeks, fitness-fatigue model error per load
  method.
- R23: 11 recreational cyclists, against the acute performance drop.
- R24: 14 cyclists, against the acute performance drop.
- R25: 11 runners (10 men).
- R26: 10 recreational athletes, against VO2.
- R27: 15 cyclists, FTP against MLSS.
- R28: 25 cyclists, 20-min test reliability.
- R29: 13 cyclists, time to failure at FTP.
- R52: 8 recreational runners over 8 weeks, against changes in speed at 2 and
  4 mmol/L lactate and race times.

No study covers wrist-device running power, HR TRIMP normalised to a threshold
hour, or a mix of branches on one scale.

## Protocol and data window

- Thresholds are resolved per session day by the source policy of the
  current thresholds (`backend/performance/current_thresholds.py`):
  1. the locally confirmed zone configuration in effect that day;
  2. otherwise each provider's latest value observed on or before that day,
     within the policy's age limits counted from that day: Garmin, then Wahoo
     for FTP. Intervals.icu values are not a source (athlete decision
     2026-11-07).
- Resting HR comes from the recovery family on the session day or up to 7
  days earlier, else the earliest later value, flagged.
- Each value covers one session; no history window is needed.
- The backfill covers every stored session.

## Measurement error and uncertainty

- TSS scales with 1/FTP². An FTP 5 % too high gives about −9 % TSS; 5 % too
  low gives about +11 %.
- FTP agrees with MLSS within ±9.2 % (95 % limits of agreement, R27). Leaving
  out its 1.4 % bias, an MLSS-anchored TSS could therefore lie within about
  ×0.84 to ×1.21.
- IF = 1 is not a validated physiological boundary (R29).
- Banister TRIMP has a test-retest CV of 15.6 % (R26).
- No uncertainty interval is shown per session.

## Bias and transferability

- Almost all the evidence comes from cyclists. The one running study goes
  against pace TSS (R25).
- Device NP algorithms differ between vendors. Garmin running power uses its
  own model, so run FTP must come from the same model (Garmin FTP/RUN).
- TSS reacts more strongly to intensity than sRPE or luTRIMP do (R21).
  Power TSS over-expresses intensity relative to the acute performance drop
  (R23, R24).
- HR-based scores in water or in strength work may misrepresent load. This is
  a product assumption, not a cited finding.
- The strength factor assumes that one AU of strength costs as much TSS as one
  AU of the athlete's rides and runs at a similar RPE. Nothing validates this;
  it is a personal scaling, not a measurement.
- Garmin watch ratings do not follow the session-RPE protocol of R1: the
  scale is anchored only at its ends and the rating is given right after
  saving, not about 30 minutes later. The value reports how many pairs came
  from local feedback and how many from the watch.
- The constants are chosen by the profile sex. A person outside both
  reference groups, or an unset profile (male assumed), gets constants that
  may not fit.

## Deviations from the studied procedure

- NP comes from the device or provider summary, not from the app's own
  30-s/4th-power calculation over streams.
- HR TRIMP sums over the heart-rate distribution (v5), but with the fixed
  Banister weights of the profile sex, not the individual lactate and
  heart-rate weights of R52. The threshold-hour normalisation follows the
  vendor convention (V2), not a published method.
- Pace uses Garmin's grade-adjusted average speed, not normalized graded pace
  from streams, and the flat average speed when that is missing.
- Yoga and alpine ski get no TSS. Their sRPE AU stays beside the sum.
- Strength TSS is the session-RPE load scaled by a personal factor, not a
  published TSS method.
- Calibration pairs use the TSS duration for their AU, not M1's elapsed
  duration.

## Minimum data and stop rules

- A value needs a positive duration and a branch with complete inputs.
  Without one, the session has no TSS, counts in `load_missing_sessions` and
  shows its sRPE AU beside the sum (`backend/performance/load.py`). A
  provider load is never used as a fallback.
- Power: `NP > 0` and an `FTP > 0` for the sport on the day.
- Pace: `v > 0` and `v_threshold > 0`.
- Heart rate: average HR, HR_rest, HR_max and the threshold HR all known,
  with `HR_rest < threshold HR < HR_max`. The distribution needs covered
  seconds of at least 80 % of the TSS duration and a positive TRIMP; else
  `0 < HRr ≤ 1` for the average HR.
- Session RPE (strength): a rated session with a positive elapsed duration
  (`no_rating` otherwise) and at least 20 calibration pairs within 2 RPE of
  its rating in the window (`not_calibrated` otherwise). An RPE of 0 gives
  0 AU and so 0 TSS without a factor.
- An IF above 2.0 is rejected as implausible (`implausible_intensity`).
- Duplicate imports count once (canonical session).
- A session without a valid threshold on its day uses the earliest later
  threshold under the same source policy and is flagged
  `threshold_after_session` with that threshold's date (athlete decision
  2026-11-06), when that threshold was observed at most 90 days after the
  session day (v5). Otherwise that threshold counts as missing and the branch
  falls through as with no threshold.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| TSS formula | hours × IF² × 100, IF = NP/FTP | source | R18 as given in vendor text V1; R20 relates TSS to fitness change. |
| Branch order | power, pace (run), heart rate | product assumption | Athlete decision 2026-11-06; external load before internal load. |
| Pace TSS | hours × (v/v_threshold)² × 100 | product assumption | rTSS convention (V1), formula unverified; R25 does not support it. |
| TRIMP prefactor and coefficient | male 0.64 and 1.92, female 0.86 and 1.67 | product assumption | Banister constants as cited for R19, not verified from the chapter; male coefficient chosen by the athlete 2026-11-06, constants by profile sex 2026-11-07 (v3). |
| Unset sex | male constants, marked `sex_assumed` | product assumption | Athlete decision 2026-11-07 (#1774); keeps existing values for the male athlete. |
| HR distribution | TRIMP summed per bpm over the moving samples, scaled by TSS duration / covered seconds | source | R52 weights the impulse by the heart-rate distribution of the session; the Banister weights of R19 replace its individual ones (product assumption). Athlete decision 2026-11-08 (v5). |
| HR coverage minimum | 80 % of the TSS duration, else the average-HR TRIMP | product assumption | Keeps a mostly missing stream from scaling up a short part; not a published value. Athlete decision 2026-11-08 (v5). |
| HR distribution samples | moving samples, gaps over 5 s excluded, 30-240 bpm | product assumption | Same sample rules as the stream analyses (M8); readings outside the range are sensor faults. |
| HR normalisation | 60 min at threshold HR = 100 | product assumption | Vendor convention (V2); no peer-reviewed source. |
| HR guards | HR_rest < threshold HR < HR_max, 0 < HRr ≤ 1 | product assumption | Keeps HRr defined and the normalisation positive; not a published rule. |
| Resting HR look-back | 7 days, else the earliest later value within 90 days, flagged | product assumption | Keeps HRr on a recent resting HR; the later stand-in follows the athlete decision of 2026-11-06 after the count on the 2026-10-24 copy (2,334 sessions had none within 7 days); not a published value. |
| Resting HR source | recovery family, Garmin first | product assumption | Same family rule as `backend/performance/source_policy.py`. |
| Implausible IF | above 2.0 | product assumption | Guard against a wrong FTP or unit; not a physiological rule. |
| Stored intensity | intensity_pct = IF × 100, power branch only | product assumption | Issue #1725 scope (NP/FTP); pace IF is not comparable. |
| Sports without TSS | yoga, alpine ski | product assumption | Their HR does not reflect endurance load; athlete decision 2026-11-06 (v2). |
| Walking | heart-rate branch | product assumption | Like hiking; athlete decision 2026-11-06 (v2) reverses the earlier exclusion. |
| Strength branch | session-RPE AU × personal TSS per AU | product assumption | HR load agrees poorly with sRPE in strength work (Dai et al. 2025, README) and misses leg load; athlete decision 2026-11-06 (v2). R1 covers the AU, not the conversion. |
| Calibration statistic | median of TSS / AU per pair | product assumption | Robust to single outliers; athlete decision 2026-11-06. |
| Calibration matching | pairs within ±1 RPE of the strength session, else ±2, else no value | product assumption | TSS / AU = 100·IF² / (60·RPE) falls with intensity, so an unmatched median follows the easy sessions (science review 2026-11-07, P2); RPE and intensity relate non-linearly. Athlete decision 2026-11-07 (v4). |
| Calibration duration | the pair's AU uses its TSS duration (moving, else elapsed) | product assumption | One duration on both sides (review P3); athlete decision 2026-11-07 (v4). |
| Calibration window | 365 days up to the session day | product assumption | Follows slow changes and dates each value; athlete decision 2026-11-06. |
| Calibration minimum | 20 pairs in the band used | product assumption | Enough for a stable median; athlete decision 2026-11-06, per band since v4. |
| Calibration ratings | local feedback and Garmin device only | product assumption | Ratings relayed by Intervals.icu are left out; athlete decision 2026-11-06. |
| HR thresholds of other sports | run values | product assumption | The resolver keeps HR thresholds for ride and run only. |
| Indoor ride FTP | local indoor power zone of the day, else the ride FTP | product assumption | Athlete decision 2026-11-06 after review; plans also apply local indoor zones. |
| Threshold after the session | earliest later threshold, flagged | product assumption | Athlete decision 2026-11-06; fills history before the first stored threshold. |
| Later threshold cap | observed at most 90 days after the session day, else missing | product assumption | A threshold from much later may not describe the athlete at the session; athlete decision 2026-11-08 (v5). |
| Duration | moving, else elapsed | product assumption | `summary_duration_s` in `backend/canonical/activity_summary.py:117`. |

## Allowed statements

- "99 TSS from NP 230 W at FTP 250 W over 1 h 10 min (IF 0.92, power)."
- "This week: 410 TSS from 5 sessions (4 power, 1 heart rate); 1 strength
  session has no TSS."
- "This value uses the FTP of 2026-03-01 from your local zones."
- "62 TSS from heart rate; sex not set, male constants assumed."
- "Krafteinheit 80 TSS: 420 AU × 0,19 TSS/AU aus 22 bewerteten Rad- und
  Laufeinheiten mit RPE 6-8 (Schätzung)."

## Forbidden statements

- Equating power, pace and heart-rate TSS, or AU with TSS outside the
  calibrated strength branch (R21, R22).
- Presenting a strength TSS as measured, or without naming its factor basis.
- Metabolic-stress, fatigue, readiness or injury statements from one session's
  TSS (R23-R25).
- Presenting IF = 1 as the lactate threshold or MLSS (R29).
- Using or showing a provider TSS or IF as this value.
- Treating a session without a value as zero load.

## Open points

- **Unverified primary sources:**
  - R18 itself was not read: the NP definition and the TSS formula are
    confirmed only in vendor text (V1).
  - The Banister constants and the chapter page range were not verified from
    R19 itself.
  - The rTSS formula is unverified in vendor text, and R25 goes against it.
    The pace branch may be dropped at review.
- **Method scope:** the heart-rate branch mixes an internal-load model into a
  power scale (R22). The athlete decides at review whether to keep it.
- **Strength conversion (v2, v4):** no study supports converting
  session-RPE AU into TSS with a factor from endurance sessions; the factor
  carries the RPE-to-TSS relation of rides and runs at a similar RPE into
  strength work.
- **Evidence gaps:**
  - The funding and interest statements of the IJSPP papers are known only
    from abstracts.
  - Running-power TSS has no peer-reviewed validation.
