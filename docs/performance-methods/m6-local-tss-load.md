# M6 — Local TSS-scale session load and intensity

- **Card:** M6
- **Card version:** 1
- **Method ID:** local-tss-load v1 (#1725)
- **Status:** implemented (`backend/performance/local_tss.py`, `backend/sync/local_load.py`)
- **Classification:** model estimate
- **Literature checked:** 2026-11-06
- **Review:** released 2026-11-06 (athlete)

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

## Formula and units

One versioned method with three branches, tried in a fixed order. The first
branch whose inputs are complete gives the value. The value records which
branch that was (`load_branch`).

1. **Power** (ride and run):
   `IF = NP / FTP`,
   `TSS = duration_s × NP × IF / (FTP × 3600) × 100 = hours × IF² × 100`.
   - `NP`: the session's normalized power (W) from the canonical summary,
     computed by the device or provider. The app does not recompute it from
     streams.
   - `FTP`: the resolver's FTP for the session's sport on the session's local
     day.
2. **Pace** (run only, without power):
   `IF = v / v_threshold`, `TSS = hours × IF² × 100`.
   - `v`: Garmin's grade-adjusted average speed (`avgGradeAdjustedSpeed`,
     m/s), otherwise the average speed. The Garmin key is not mapped yet;
     #1725 adds it in a new Garmin activity mapper version. Without it the
     value is marked `pace_basis: average_speed`.
   - `v_threshold`: the resolver's run threshold pace on the day, stored as
     m/s.
3. **Heart rate** (every sport except strength, yoga and alpine ski, without
   power or pace):
   - `TSS = TRIMP_session / TRIMP_threshold_hour × 100`.
   - `TRIMP = minutes × HRr × 0.64 × e^(1.92 × HRr)`.
   - `HRr = (HR − HR_rest) / (HR_max − HR_rest)`.
   - `TRIMP_session` uses the session's average HR. `TRIMP_threshold_hour`
     is 60 minutes at the threshold HR.
   - `HR_max` and the threshold HR are the resolver's values for the sport on
     the day. Ride uses ride values; run and every other HR sport use run
     values.
   - `HR_rest` is the resting HR of the session day, or of the nearest
     earlier day within 7 days, from the recovery family (Garmin first).

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
  - `method`: `local-tss-load`, `method_version`: 1.
  - The owner is the canonical session.
  - `details` hold the branch, the pace basis, and the thresholds used with
    their sources and dates.
- **Fingerprint.** `input_fingerprint` is the SHA-256 over the method
  version, branch, session inputs and thresholds.
- **Recompute.** A method version bump or a changed input gives a new
  fingerprint. A local, idempotent backfill then recomputes the affected
  sessions, so a corrected or backfilled threshold changes past values.
- **FTP changes.** A later FTP change does not reach past sessions, because
  their dated threshold is unchanged.
- **Session changes.** A session that disappears or merges retires its
  observations.

## Sources

- **Power branch:**
  - R18 is the origin of NP, IF and TSS. It is a book with an author
    interest, and its formula is confirmed only in the vendor text V1.
  - R20 relates TSS to fitness change.
  - R27-R29 cover the error and meaning of FTP.
- **Heart-rate branch:** R19 (Banister TRIMP; constants not verified from
  the chapter). V2 shows that the "one hour = 100" normalisation is a vendor
  convention without a peer-reviewed source.
- **Pace branch:** V1 (rTSS convention, formula not verified) and R30 (use
  case only). R25 is evidence against it.
- **Agreement and comparison limits:** R21-R24 and R31. R26 reports the
  reliability of HR-based scores.

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

No study covers wrist-device running power, HR TRIMP normalised to a threshold
hour, or a mix of branches on one scale.

## Protocol and data window

- Thresholds are resolved per session day by the source policy of the
  current thresholds (`backend/performance/current_thresholds.py`):
  1. the locally confirmed zone configuration in effect that day;
  2. otherwise each provider's latest value observed on or before that day,
     within the policy's age limits counted from that day.
- Resting HR comes from the recovery family on the session day or up to 7
  days earlier.
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
- The male coefficient is fixed for this athlete and does not transfer.

## Deviations from the studied procedure

- NP comes from the device or provider summary, not from the app's own
  30-s/4th-power calculation over streams.
- HR TRIMP uses the session's average HR, not zone or per-second HR. The
  threshold-hour normalisation follows the vendor convention (V2), not a
  published method.
- Pace uses Garmin's grade-adjusted average speed, not normalized graded pace
  from streams, and the flat average speed when that is missing.
- Strength, yoga and alpine ski get no TSS. Their sRPE AU stays beside the
  sum.

## Minimum data and stop rules

- A value needs a positive duration and a branch with complete inputs.
  Without one, the session has no TSS, counts in `load_missing_sessions` and
  shows its sRPE AU beside the sum (`backend/performance/load.py`). A
  provider load is never used as a fallback.
- Power: `NP > 0` and an `FTP > 0` for the sport on the day.
- Pace: `v > 0` and `v_threshold > 0`.
- Heart rate: average HR, HR_rest, HR_max and the threshold HR all known,
  with `HR_rest < threshold HR < HR_max` and `0 < HRr ≤ 1`.
- An IF above 2.0 is rejected as implausible (`implausible_intensity`).
- Duplicate imports count once (canonical session).
- A session without a valid threshold on its day uses the earliest later
  threshold under the same source policy and is flagged
  `threshold_after_session` with that threshold's date (athlete decision
  2026-11-06). Without any later threshold it has no value.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| TSS formula | hours × IF² × 100, IF = NP/FTP | source | R18 as given in vendor text V1; R20 relates TSS to fitness change. |
| Branch order | power, pace (run), heart rate | product assumption | Athlete decision 2026-11-06; external load before internal load. |
| Pace TSS | hours × (v/v_threshold)² × 100 | product assumption | rTSS convention (V1), formula unverified; R25 does not support it. |
| TRIMP prefactor and coefficient | 0.64 and 1.92 | product assumption | Banister male constants as cited for R19, not verified from the chapter; coefficient chosen by the athlete 2026-11-06. |
| HR normalisation | 60 min at threshold HR = 100 | product assumption | Vendor convention (V2); no peer-reviewed source. |
| HR guards | HR_rest < threshold HR < HR_max, 0 < HRr ≤ 1 | product assumption | Keeps HRr defined and the normalisation positive; not a published rule. |
| Resting HR look-back | 7 days | product assumption | Keeps HRr on a recent resting HR; not a published value. |
| Resting HR source | recovery family, Garmin first | product assumption | Same family rule as `backend/performance/source_policy.py`. |
| Implausible IF | above 2.0 | product assumption | Guard against a wrong FTP or unit; not a physiological rule. |
| Stored intensity | intensity_pct = IF × 100, power branch only | product assumption | Issue #1725 scope (NP/FTP); pace IF is not comparable. |
| Sports without TSS | strength, yoga, alpine ski | product assumption | HR load agrees poorly with sRPE in strength work (Dai et al. 2025, README); yoga and alpine ski are treated alike because their HR does not reflect endurance load. |
| HR thresholds of other sports | run values | product assumption | The resolver keeps HR thresholds for ride and run only. |
| Threshold after the session | earliest later threshold, flagged | product assumption | Athlete decision 2026-11-06; fills history before the first stored threshold. |
| Duration | moving, else elapsed | product assumption | `summary_duration_s` in `backend/canonical/activity_summary.py:117`. |

## Allowed statements

- "99 TSS from NP 230 W at FTP 250 W over 1 h 10 min (IF 0.92, power)."
- "This week: 410 TSS from 5 sessions (4 power, 1 heart rate); 1 strength
  session has no TSS."
- "This value uses the FTP of 2026-03-01 from your local zones."

## Forbidden statements

- Equating power, pace and heart-rate TSS, or AU with TSS (R21, R22).
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
- **Evidence gaps:**
  - The funding and interest statements of the IJSPP papers are known only
    from abstracts.
  - Running-power TSS has no peer-reviewed validation.
