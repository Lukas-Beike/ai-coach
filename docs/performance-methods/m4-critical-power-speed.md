# M4 — Critical Power and Critical Speed

- **Card:** M4
- **Card version:** 2
- **Method ID:** critical-power-speed v1 (`backend/performance/critical_power.py`)
- **Status:** implemented as an experimental model estimate (#1431) on the local mean-maximal curve (#1430, `mean-max-curve` v1)
- **Classification:** model estimate
- **Literature checked:** 2026-10-24
- **Review:** released 2026-11-02 (athlete)

## Target construct

Parameters of the two-parameter power-duration model for cycling (CP, W′) and
distance-time model for running (CS, D′), fitted to suitable maximal efforts of
one sport and one comparable period. They are model parameters, not measured
FTP, lactate threshold, MLSS or an isolated anaerobic energy store (R3).

## Formula and units

- Cycling: `P(t) = CP + W′ / t`, equivalently `work(t) = CP × t + W′`.
- Running: `distance(t) = CS × t + D′`.
- Units: t in s, P and CP in W, work and W′ in J, CS in m/s, distance and D′
  in m.
- Fit: linear least squares of work (or distance) on time, chosen before
  looking at data; the power-versus-1/t fit is reported only as a
  sensitivity analysis.
- Reference cases for tests: CP 250 W and W′ 18,000 J give 350 W at 180 s,
  292.857142857 W at 420 s and 275 W at 720 s. CS 4 m/s and D′ 200 m give
  920 m at 180 s, 1,880 m at 420 s and 3,080 m at 720 s. Both fits must
  recover the parameters exactly.

## Sources

R3 (model and physiology), R4 (cycling field CP from 3/7/12-min efforts),
R5 (running CS field tests), R6 (3-min all-out test in cycling), R16 (CS from
everyday training data, deferred to M5). Newer work: protocol choice changes CS
and D′ (Anderson et al. 2026, see README).

## Population and reference measurement

R4: trained cyclists (count not reachable in the abstract); reference was lab
CP from three exhaustive constant-power trials. R5: 19 running studies, 285
participants, recreational to national level, compared field CS with treadmill
or track protocols. R6: 20 studies, 284 participants. R16: logged runs of
recreational marathon runners, no lab reference.

## Protocol and data window

- Cycling starting point: three efforts of about 3, 7 and 12 min (R4); in a
  single session with 30 min recovery, as repeated field efforts in random
  order, or as the best 3/7/12
  min from training and race files. These are checked, not prompted: the app
  does not ask the athlete to do maximal tests.
- Running: a running-specific protocol from R5, with fixed durations or
  distances of 3 to 12 min whose durations differ by at least 7 min, trials
  longest to shortest or randomised. Within 3 to 12 min the 7-min rule can
  only apply to the shortest and longest trial; 3/7/12 min spans 9 min.
  Recovery is the 30-min product assumption in the numeric rules, released by
  the athlete; R5's included studies report 30-60 min. CP protocols are not
  transferred to running.
- Inputs need real power for cycling and reliable time and distance for
  running. Record test intent, date, recovery, sensor, indoor/outdoor and
  conditions, or mark them unknown.
- Implemented selection (v1): the best 180, 420 and 720 s of the last 28 days
  from the mean-maximal curve, the training-file protocol of R4. Cycling is
  fitted separately for outdoor and indoor sessions; running uses outdoor runs
  only. Longest duration first, each pick is the best candidate from another
  session or at least 30 min after the end of every earlier pick of the same
  session. Test intent, sensor and calibration are reported as unknown; nothing
  is persisted and there is no schema change.

## Measurement error and uncertainty

R4 field CP versus lab CP: standard error of estimate 4.5 %, 5.8 % and 5.2 %;
limits of agreement −26 to +29 W, +26 to +53 W and −34 to +44 W for the
single-session, repeated-effort and training-file protocols. These are
protocol-specific group errors, not an individual confidence interval. Each
fit reports residuals, sensitivity to leaving one effort out and data age.
With three points uncertainty intervals can be unstable; overlapping bests from
one effort are dependent and must not narrow them.

## Bias and transferability

R4's repeated-effort protocol overestimated CP systematically (interval entirely
positive). R6: the 3-min all-out end power overestimates CP on average and its
work above end power does not estimate W′ accurately; possible publication
bias. R5 covers runners only and gives no pooled agreement. D′ is much less
precise than CS (R16). No study validates this athlete's power meter or GPS.

## Deviations from the studied procedure

- Efforts from everyday files are not verified as maximal, unlike lab trials.
- The best-effort curve (`mean-max-curve` v1) has 180, 420 and 720 s windows,
  but its points are best values from everyday files, not CP test data.
- A freely chosen period such as "best of the last 90 days" is not one
  unchanged physiological state and is not used as a protocol.
- No 3-min all-out test is offered as a substitute (R6).

## Minimum data and stop rules

- At least three differently long, suitably maximal efforts per sport and
  protocol; two points give no goodness-of-fit check.
- No numeric result for a non-identifiable fit, non-positive or implausible
  parameters, incompatible conditions, estimated cycling power, running
  power or unvalidated elevation correction.
- Downsampled streams are excluded or labelled; only full-resolution streams
  feed the curve (#1430). Overlapping bests of one session share an
  `effort_group` and count as one effort.
- Residual, leave-one-out and plausibility limits are in the numeric rules,
  fixed on 2026-11-02 before any real-data evaluation; there is no universal
  "under 5 % error is valid" rule.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| Minimum efforts per fit | 3 | product assumption | Conservative release rule; two points allow no fit check. R5 names two as practical minimum and three as more precise. |
| Cycling effort durations | about 180, 420 and 720 s | source | R4 3/7/12-min protocol. |
| Recovery between cycling efforts in one session | 30 min | source | R4 single-session protocol. |
| Running trial durations | 3 to 12 min | source | R5 recommendation. |
| Duration difference between running trials | at least 7 min | source | R5: shorter differences between trial durations failed validity criteria. Not a recovery time. |
| Recovery between running trials | 30 min | product assumption | Lower end of the 30-60 min R5 reports in included studies; same rule as cycling. |
| Effort window | 28 days | product assumption | Shorter analysis window of the curve, closer to one physiological state than 90 days. |
| Running sessions | outdoor only | product assumption | Treadmill speed and distance are not reliable without calibration. |
| Maximum relative residual | 3 % of the observed work or distance per effort | product assumption | Fixed before real data; a larger misfit suggests a non-maximal or incompatible effort. |
| Leave-one-out fits | every two-effort fit positive | product assumption | A non-positive parameter without one effort shows the estimate hinges on it. |
| Plausible cycling range | CP 50-600 W, W′ 1-50 kJ | product assumption | Outside these ranges a fit is treated as a data or effort error. |
| Plausible running range | CS 1.5-7 m/s, D′ 10-500 m | product assumption | Outside these ranges a fit is treated as a data or effort error. |
| Primary fit | work or distance on time | product assumption | Chosen in advance per #1431; other fit shown as sensitivity. |
| Curve cycling windows | 5, 15, 30, 60, 120, 180, 300, 420, 600, 720, 1200, 1800, 3600 s | product assumption | `backend/performance/power_profile.py:POWER_DURATIONS`; 180/420/720 s follow R4, the rest are display windows. |
| Curve running windows | 60, 180, 300, 420, 720, 1200 s; 1,000 and 5,000 m | product assumption | `backend/performance/power_profile.py:RUNNING_DURATIONS`, `RUNNING_DISTANCES`. |

## Allowed statements

- "Model estimate from three efforts (3, 7, 12 min, March 2027): CP 262 W,
  W′ 17 kJ; residuals and sensitivity shown."
- "No CP estimate: only two suitable efforts in the selected period."
- "Your best 20-minute power in this file was 281 W" (observed best effort,
  not a CP).

## Forbidden statements

- CP as FTP, lactate threshold, MLSS or a zone boundary, or automatic zone
  changes from CP (#1421).
- W′ or D′ as a measured anaerobic capacity.
- Marathon or long-race predictions from the short-duration model.
- "Scientifically validated" for this athlete's estimate, or validity claimed
  from a high R².
- A CP from estimated power, running power or a 3-min all-out test.

## Open points

- No comparison with published reference or controlled validation data yet;
  the estimate stays experimental (gate G4) and never feeds FTP or zones.
- Athlete-marked protocol tests with recorded intent, sensor and calibration
  are not stored; adding them needs a schema migration from v16.
- R4 participant count and recovery for its repeated-effort protocol were not
  reachable.
- Passive CS from everyday runs (R16) stays deferred to M5.
