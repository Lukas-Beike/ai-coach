# M9 — LT1 pace and power from own steady sessions

- **Card:** M9
- **Card version:** 1
- **Method ID:** pace-at-heart-rate-v2 and power-at-heart-rate-v1, read by `backend/performance/pace_at_hr.py:output_at_heart_rate` (#2427)
- **Status:** implemented; LT1 origin `own_sessions` in `backend/performance/current_metrics.py:first_thresholds`
- **Classification:** model estimate
- **Literature checked:** 2026-11-12
- **Review:** released 2026-11-12 (athlete)

## Target construct

The running pace and the cycling power that belong to the athlete's LT1 heart
rate, read from the athlete's own steady sessions. The LT1 heart rate itself
is not derived here: it keeps its precedence (measured, adopted DFA-α1
estimate, top of the heart-rate zone 2, 85 % of the threshold HR). The value
replaces a population stand-in (zone 2 top of the pace or power zones, 88 % of
the threshold speed, 75 % of the FTP) with the athlete's own heart-rate to
output relation. It is not a lactate or ventilatory threshold measurement.

Athlete decisions (2026-11-12, #2427): pace and power at the LT1 heart rate,
no heart-rate value from decoupling; read in a direct heart-rate band, no
regression; precedence own sessions > zone 2 top > fixed share; labelled
"Schätzung" like the other stand-ins.

## Formula and units

1. **Run profile** (`pace-at-heart-rate-v2`, unchanged): seconds, distance and
   squared speed per 5 bpm heart-rate bin of steady, flat-ish samples after a
   10-minute warm-up; grade-adjusted speed (R44) where a slope is known.
2. **Ride profile** (`power-at-heart-rate-v1`): seconds, work (J) and squared
   power per 5 bpm heart-rate bin after a 10-minute warm-up. Each heart-rate
   sample is paired with the mean power of the 60 s before it, once at least
   54 s of that minute are recorded (so the first minute after a pause or gap
   does not count); samples whose own power is zero (coasting) do not count.
3. **Band:** the 10 bpm band of two 5 bpm bins whose centre is nearest to the
   LT1 heart rate `h`: `low = 5 × round((h − 4.5) / 5)`, band `low` to
   `low + 9` bpm.
4. **Per session:** time-weighted mean output in the band, `v = Σd / Σt` (m/s)
   or `P = ΣW / Σt` (W), when the band holds at least 600 s with a coefficient
   of variation of at most 0.15.
5. **Value:** the median over the qualifying sessions; run pace
   `1000 / median(v)` in s/km, ride power `median(P)` in W, both rounded to
   whole units in `first_thresholds`.

## Sources

- **LT1 definition and its correspondence with the first ventilatory
  threshold:** R54; three-zone model with LT1/VT1 as the boundary of the easy
  zone: R55.
- **Cardiovascular drift**, the reason for the warm-up exclusion and for the
  rejection of a drift-derived heart rate: R32, R34; hydration R33.
- **Grade adjustment:** R44.
- **Decoupling as a field test of the aerobic threshold:** vendor text V3, V4;
  no peer-reviewed validation against lactate or gas exchange was found, so it
  is not used here.

## Population and reference measurement

- R54: review of laboratory lactate threshold concepts in endurance athletes.
- R55: descriptive review of elite endurance athletes' intensity distribution.
- No study validates pace or power at an LT1 heart rate read from uncontrolled
  field sessions against a laboratory LT1.

## Protocol and data window

- Ride and run sessions of the last 60 days with full-resolution streams,
  merged as in the session curves (`backend/performance/mean_max_curve.py`);
  e-bike rides, commutes, warm-ups and cool-downs are left out
  (`TrainingProfileSelectionService.curve_records`).
- Runs road and track only (trail excluded). Outdoor sessions first; indoor
  (treadmill, trainer, virtual) sessions only when fewer than three outdoor
  sessions qualify, for runs and rides alike (rides: product assumption,
  heat raises the heart rate indoors).
- Computed at read time from the in-memory session curves; nothing is stored.

## Measurement error and uncertainty

- Heart rate at a given output rises with heat (R34, R35), fluid loss (R33)
  and fatigue; the median over sessions damps but does not remove this.
- Wrist optical heart rate lags and drifts more than a chest strap; the
  recording device is not checked.
- The band may sit up to 2.5 bpm off the LT1 heart rate because the stored
  bins are 5 bpm wide.
- The error of the LT1 heart rate itself (zone 2 top or fixed share) carries
  over fully; a value read at a stand-in heart rate is no better than that
  stand-in.
- No uncertainty interval is shown.

## Bias and transferability

- Sessions are the athlete's own choice: if steady sessions cluster away from
  the LT1 heart rate, no value results rather than a biased one.
- Treadmill speed is uncalibrated; it counts only without enough outdoor runs.
- Outdoor ride power at a heart rate depends on terrain only through power,
  not speed, so wind and gradient do not bias it.

## Deviations from the studied procedure

- The literature determines LT1 in a stepwise laboratory test; this method
  never determines LT1 and only maps a given LT1 heart rate onto output from
  field sessions.
- The band is quantised to the 5 bpm bins of the existing pace-at-heart-rate
  profile instead of the decided 5 bpm below to 4 bpm above the LT1 heart
  rate.

## Minimum data and stop rules

- An LT1 heart rate and an LT2 value of the sport must exist (no LT1 without
  LT2).
- At least 3 sessions, each with at least 600 s in the band and a coefficient
  of variation of at most 0.15; otherwise no value, and the zone 2 top or the
  fixed share applies.
- Ride profile: at least 30 minutes of recording with power and heart-rate
  streams; run profile: the rules of `pace-at-heart-rate-v2`.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| Data window | 60 days | product assumption | Same window as the DFA-α1 estimate (`first_threshold_estimate.py:ESTIMATE_DAYS`); one training state. |
| Minimum sessions | 3 | product assumption | Same minimum as the DFA-α1 estimate and the session comparison of pace at heart rate. |
| Band width | 10 bpm (two 5 bpm bins) | product assumption | `pace_at_hr.py:BIN_BPM`, `BAND_BINS`; athlete decision 2026-11-12. |
| Minimum time in band per session | 600 s | product assumption | `pace_at_hr.py:MIN_BAND_S`. |
| Maximum output variation in band | coefficient of variation 0.15 | product assumption | `pace_at_hr.py:MAX_SPEED_CV`, also applied to power. |
| Warm-up exclusion | 600 s | source | Drift starts 10-20 min into exercise (R32, R34). |
| Power smoothing before pairing with heart rate | 60 s | product assumption | Heart rate trails a power change by up to about a minute; `pace_at_hr.py:POWER_SMOOTH_S`. |
| Flat-ground limit for runs | 3 % grade | product assumption | `pace_at_hr.py:FLAT_GRADE_PCT`; grade adjustment from R44. |

## Allowed statements

- "LT1 pace 5:32 /km, an estimate from your own steady runs at the LT1 heart
  rate of 128 bpm (top of your heart-rate zone 2)."
- "No LT1 power from your rides yet: fewer than three steady rides near
  131 bpm in the last 60 days."

## Forbidden statements

- The value as a measured, laboratory or validated LT1.
- An LT1 heart rate derived from this method or from decoupling.
- A fitness trend from a change of this value (use pace at heart rate, M8).
- Zone changes made automatically from this value.

## Open points

- No comparison with a laboratory or field LT1 test of this athlete yet; a
  step test with lactate or a DFA-α1 ramp would check it.
- The 0.15 variation limit, decided for both sports, may reject many outdoor
  rides over rolling terrain (60 s power varies more than running speed); to
  be checked against real coverage: the diagnostic report's `lt1_ride_coverage`
  counts qualifying rides at 0.15, 0.20 and 0.25 (#2535).
- The session curve memo is held twice (public state and training reports)
  until the composition shares one reader.
