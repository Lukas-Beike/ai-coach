# M8 — Local efficiency factor, variability index, work and decoupling

- **Card:** M8
- **Card version:** 4
- **Method ID:** local-session-metrics v4 (#1680, #1770, #1773, #1950)
- **Status:** implemented (`backend/performance/session_metrics.py`, `backend/sync/session_metrics.py`)
- **Classification:** descriptive statistic
- **Literature checked:** 2026-11-07
- **Review:** released 2026-11-08 (athlete)

## Target construct

Four descriptive numbers per completed ride or run, computed locally from the
canonical Garmin or Wahoo summary and, where stored, the merged
full-resolution streams:

- **Efficiency factor (EF):** output per heartbeat over the whole session.
- **Variability index (VI):** how steady a ride's power was.
- **Mechanical work:** the work done on the pedals or, for runs with power,
  by Garmin's running-power model, in kJ.
- **Aerobic decoupling:** how much output per heartbeat fell from the first to
  the second half of a steady session (Pw:HR for rides, Pa:HR for road runs).

They describe one session. They are not a fitness score, a durability score,
an aerobic-threshold test, energy expenditure or a readiness statement.
Calories are a separate device value: the Garmin `calories` or Wahoo
`calories_accum` estimate is mapped as `energy_kcal` with its provider label
and is not part of this method.

Athlete decisions (2026-11-07, #1680):

- Run EF uses speed, not running power, so it matches the Pa:HR decoupling.
- Pa:HR uses grade-adjusted speed, as run EF does (v2, 2026-11-07, #1770).
- Work covers rides and runs with power; run work is labelled as Garmin's
  running-power model.
- Values exist only where full-resolution streams are stored; a follow-up
  issue re-fetches the streams of the history, and the values then follow
  automatically.
- Calories come from the device as `energy_kcal`, not from a local formula.
- Card 3 (2026-11-08, #1773): the decoupling's output per heartbeat is named
  `steady_output_per_hr` (halves: `output_per_hr`), apart from the session
  EF; run work carries `power_model: running_power_model`; the steady-output
  rule for outdoor rides is re-measured after the stream history is fetched
  again (#1763).
- Provider values of these metrics (Intervals.icu `icu_efficiency_factor`,
  `icu_variability_index`, `decoupling`, `icu_joules`) are never used.

## Formula and units

1. **EF, ride:** `EF = NP / HR_avg` in W/bpm.
   - `NP`: the session's normalized power from the canonical summary
     (device or provider), not recomputed from streams.
2. **EF, run:** `EF = v × 60 / HR_avg` in (m/min)/bpm.
   - `v`: Garmin's grade-adjusted average speed, else the average speed. The
     value records which (`basis`: `grade_adjusted_speed` or
     `average_speed`).
3. **VI, ride:** `VI = NP / P_avg`, unitless.
4. **Work, ride or run with power:** the device's work total (Wahoo
   `work_accum`, `basis: device_total`), else
   `W = Σ P_i × Δt_i / 1000` in kJ over the power stream (`basis:
   power_stream`). Samples with `Δt > 5 s`, a missing or negative power and,
   when a `moving` stream exists, stopped samples are skipped (v4). Run work records `power_model: running_power_model`: it is the
   output of the device's running-power model (R40), not a measured force.
5. **Aerobic decoupling:** the drift of `aerobic_analysis`
   (`backend/performance/session_analysis.py`, method
   `time-weighted-session-analysis-v2`):
   `decoupling = (EF₁ − EF₂) / EF₁ × 100` in %, with `EF_h` the time-weighted
   mean non-zero output over the mean HR of half `h`, stored as
   `output_per_hr` per half and `steady_output_per_hr` for both halves. It is
   not the session EF of items 1 and 2: it uses the mean of non-zero output
   samples, not NP or Garmin's grade-adjusted average. Output is power for rides and
   grade-adjusted speed for road runs.
   - Grade-adjusted speed per sample: `v × C(g) / C(0)` with the Minetti
     et al. (2002) cost of running `C(g)` at the sample's grade `g`, clamped
     to ±45 %. The grade is the stored grade stream, else the altitude change
     over the next 200 m of distance. This is the same adjustment as
     `pace-at-heart-rate-v2`.
   - Treadmill and virtual runs are flat: their speed is not adjusted. An
     outdoor run without a grade or altitude and distance stream gets no
     decoupling.
   - The first 10 minutes are excluded; the rest is split at its midpoint.
   - A positive value means less output per heartbeat in the second half.

### Storage

- Each value is a derived observation owned by its canonical session:
  `observed_on` is the session's local day, `source_kind` `derived`,
  `method` `local-session-metrics`, `method_version` 4, natural key series
  `session:<id>`.
- Kinds: `efficiency_factor`, `variability_index`, `mechanical_work`,
  `aerobic_decoupling`. The derivation holds the basis, the unit of EF, the
  power coverage of a stream work value, and the halves of the decoupling.
- **Fingerprint:** SHA-256 over the method version, the session-analysis
  method, the summary inputs (including start, local day and recording
  origin), the content hashes of the full-resolution
  stream sets and the session's records in merge order. It is computed before
  any stream is decoded.
- **Recompute:** a changed fingerprint (new or replaced streams, a changed
  summary, a merge or split, a method bump) recomputes the session in the
  canonical backfill follow-up stage, at most 100 sessions per transaction.
  An unchanged session is not decoded or written. Rows of sessions that
  disappear are retired.

## Sources

- **EF and decoupling definitions:** vendor text V3 and V4 (Friel,
  TrainingPeaks). No peer-reviewed validity or reliability study of EF was
  found.
- **VI:** vendor text V5; R18 is the vendor-level origin of NP. No
  peer-reviewed validation of VI was found.
- **Cardiovascular drift as the mechanism:** R32, R34; durability as a concept
  R36.
- **Decoupling magnitude in a controlled protocol:** R38 (cyclists). R39
  reports that drift and Pw:HR decoupling correlate. R37 uses a different
  ratio in marathon runners.
- **Confounders:** hydration R33, heat R34 and R35.
- **Running power:** R40.
- **Grade-adjusted speed in Pa:HR:** R44 (Minetti 2002).
- **Work versus energy:** R41-R43.

## Population and reference measurement

- R33: 10 trained cyclists, 2 h at 70 % VO2max, 22 °C.
- R35: 7 men, 60 % VO2max at 35 °C, running and cycling.
- R37: 82,303 recreational marathon runners, race data.
- R38: 17 trained men, 60 min at 75 % FTP indoors with fan and fluid.
- R39: 20 cyclists over 5 months.
- R40: 12 trail runners with a footpod.
- R44: 10 elite mountain runners on a treadmill, slopes −45 to +45 %.
- R42: 17 men on an ergometer.

No study covers wrist-device running power, Garmin grade-adjusted speed or
uncontrolled outdoor sessions.

## Protocol and data window

- Each value covers one session; no history window.
- EF, VI and a device work total come from the canonical session summary.
- Stream work and decoupling come from the session's stored full-resolution
  streams of its Garmin, Wahoo and local records, merged as in the canonical
  session analysis; Intervals.icu streams are not read (athlete decision
  2026-11-07, #1685). Downsampled sets never count. Missing streams are not fetched by this method.
- Decoupling needs a steady session: at least 30 minutes of recording, 20
  minutes after the warm-up, and the eligibility rules of the session
  analysis (below).

## Measurement error and uncertainty

- No test-retest data exist for EF, VI or decoupling from field recordings.
- In a controlled indoor protocol decoupling was 2.00 ± 2.38 % over 60
  minutes (R38); the spread between athletes is about as large as the mean.
- Fluid loss raised HR by 10 % against 5 % with full replacement over 2 hours
  at 22 °C (R33); heat raised it by 17-19 % within 30 minutes (R35). One
  value in heat or without drinking can exceed any typical range.
- EF inherits the errors of NP and of the device's grade-adjusted speed; NP
  algorithms differ between vendors.
- VI uses the device's average power, which depends on Garmin's "include
  zeros" power-averaging setting: excluding zeros raises the average and
  lowers VI for rides with coasting. The setting is not reported.
- The second half includes any cool-down at the end of the session; a
  symmetric trim is evaluated together with the steady-output rule (#1763).
- Stream work misses the skipped samples; its coverage is stored. Mechanical
  work is not energy expenditure: gross efficiency is about 20 % and varies
  with work rate and training (R41-R43).
- No uncertainty interval is shown per session.

## Bias and transferability

- Most evidence comes from cyclists in the laboratory.
- Outdoor sessions have no temperature, wind or hydration control.
- Run EF from speed depends on terrain; average speed on hills is not
  comparable, grade-adjusted speed only partly corrects it. Pa:HR adjusts
  each sample with Minetti 2002, run EF uses Garmin's own grade-adjusted
  average; both are models of level-ground cost.
- Garmin running power is a model; run work is model output, not a measured
  force.
- Runs and rides are on different scales and are never compared.

## Deviations from the studied procedure

- EF uses the device's NP or grade-adjusted average speed, not normalized
  graded pace from streams (V3).
- Decoupling uses the session-analysis eligibility rules, not a fixed
  steady-state protocol; the warm-up exclusion is 10 minutes.
- No 5 % (or other) decoupling band is applied.

## Minimum data and stop rules

- Sport ride or run; other sports get no value.
- EF: an average HR within 30-240 bpm and `NP > 0` (ride) or `v > 0` (run).
- VI: ride with `NP > 0` and `P_avg > 0`; a VI outside 0.5-5.0 is dropped.
- Work: a positive device total, else a power stream whose valid samples
  cover at least 85 % of the moving (else elapsed) duration and a positive
  sum; with a `moving` stream only moving samples count toward coverage and
  work, so stopped samples cannot fill a power dropout (v4). A moving
  duration of 0 falls back to the elapsed duration (v4).
- Decoupling, from `aerobic_analysis`:
  - ride with power, or road run (trail runs excluded) with speed; an
    outdoor run also needs a grade, or altitude and distance;
  - a recording of at least 30 minutes;
  - at least 85 % paired output and HR time in each half;
  - an output coefficient of variation of at most 15 % in each half;
  - the halves' mean outputs within 10 % of each other;
  - HR within 30-240 bpm, output above 0, steps above the adaptive gap rule
    `max(30 s, 3 × median step)` of the zone times, stops excluded (v4).
- A session without a value has no row; it is never zero.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| EF ride | NP / average HR, W/bpm | product assumption | Vendor definition V3; no peer-reviewed validation. |
| EF run | grade-adjusted (else average) speed × 60 / average HR | product assumption | Speed, as the Pa:HR decoupling; athlete decision 2026-11-07; V3 uses normalized graded speed. |
| VI | NP / average power, rides | product assumption | Vendor definition V5; no peer-reviewed validation. |
| VI plausibility | 0.5-5.0 | product assumption | Guard against a wrong unit or a broken summary; V5 (unverified snippet) lists steady rides at 1.00-1.02 and MTB up to 1.50. |
| Work | device total, else Σ P × Δt | product assumption | Physical definition of work; Wahoo reports its own total. |
| Work coverage | at least 85 % of the moving duration | product assumption | Same coverage as the decoupling halves; not a published value. |
| Sample gap | work: over 5 s skipped; decoupling: over `max(30 s, 3 × median step)` skipped | product assumption | Decoupling uses the zone times' rule (`stream_zones.max_step_s`) so downsampled and smart-recording streams count. Analysis method v7, histogram v2 (#1950). |
| Decoupling formula | (EF₁ − EF₂) / EF₁ × 100 | source | Vendor definition V3; R38 uses the same split for power:HR. |
| Warm-up exclusion | 10 minutes | product assumption | `aerobic_analysis`; drift starts after about 10-20 minutes (R32, R34), which motivates an exclusion but validates no cut-off. |
| Minimum recording | 30 minutes | product assumption | `aerobic_analysis` requires 30 minutes (20 after the warm-up); V5 (unverified snippet) names 20 minutes. |
| Paired coverage | at least 85 % per half | product assumption | `aerobic_analysis`; not a published value. |
| Output variation | CV at most 15 % per half | product assumption | `aerobic_analysis`; keeps the comparison steady; not a published value. |
| Half match | mean outputs within 10 % | product assumption | `aerobic_analysis`; not a published value. |
| HR range | 30-240 bpm | product assumption | `aerobic_analysis`; sensor plausibility. |
| Run decoupling output | Minetti 2002 grade-adjusted speed per sample | source | R44 cost model; athlete decision 2026-11-07 (#1770): same basis as run EF; Minetti 2002 is a laboratory cost model, not Garmin's GAP, so EF and Pa:HR adjust grade with different models. |
| Grade span from altitude | 200 m of distance | product assumption | Same as `backend/performance/pace_at_hr.py:GRADE_SPAN_M`; smooths GPS altitude noise. |
| Grade clamp | ±45 % | product assumption | Validity range of the Minetti 2002 polynomial. |
| Trail runs | no decoupling | product assumption | Pace on trails is not comparable; `aerobic_analysis` since #1670. |
| Batch | 100 sessions per transaction | product assumption | Keeps the writer lock short; no physiological meaning. |

## Allowed statements

- "EF 1,62 W/bpm (NP 230 W, Ø HF 142)."
- "Decoupling 3,1 %: in der zweiten Hälfte etwas weniger Leistung pro
  Herzschlag; Wärme und Trinken beeinflussen das."
- "VI 1,03: die Fahrt war gleichmäßig."
- "Arbeit 1 085 kJ (aus dem Leistungsstream)."
- "Für diese Einheit gibt es kein Decoupling, weil sie nicht gleichmäßig genug
  war."

## Forbidden statements

- Any fixed decoupling band (such as 5 %) as a research-based limit of
  aerobic fitness (V4, R37).
- A durability, fitness or aerobic-threshold verdict from one session's
  decoupling or EF.
- Comparing run EF with ride EF, or run work with ride work.
- Presenting mechanical work as calories burned, or a kJ-to-kcal factor as
  exact (R41-R43).
- Presenting a provider EF, VI, decoupling or work as this value.
- Treating a session without a value as zero.

## Open points

- **Validity:** no peer-reviewed validity or reliability study of EF, VI or
  field decoupling; all three stay descriptive. Candidate reference R53: in
  51 trained cyclists, HR decoupling over about 2.5 h of moderate cycling
  tracked the fall of power at the first ventilatory threshold (r = −0.76);
  controlled laboratory sessions, not everyday outdoor files.
- **Steady-output rule:** the output CV ≤ 15 % on ~1 s samples probably
  excludes most outdoor rides (science review 2026-11-07). A counts-only
  measurement (`scripts/decoupling_eligibility_dry_run.py`) on the athlete's
  data on 2026-11-08 found no session of the last 365 days with Garmin or
  Wahoo full-resolution streams, so it could not be evaluated; it runs again
  after the stream history re-fetch (#1763), and the rule is decided then.
- **History:** sessions without stored full-resolution streams have no stream
  work and no decoupling until the follow-up stream re-fetch.
- **EF trend:** an EF or decoupling trend over comparable sessions is not
  offered; it would need a card of its own with a comparability rule.
- **Funding and interests:** declared "no competing interests" for R37-R40;
  not checked for the others.
