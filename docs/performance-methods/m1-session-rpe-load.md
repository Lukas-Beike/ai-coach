# M1 — Session-RPE load

- **Card:** M1
- **Card version:** 1
- **Method ID:** session-rpe-load-v1 (planned, #1427)
- **Status:** not implemented
- **Classification:** descriptive statistic
- **Literature checked:** 2026-10-24
- **Review:** released 2026-10-24 (athlete)

## Target construct

Subjective internal load of one whole session, and its sum per day, week and
sport, from the athlete's own global effort rating. It is not a mechanical
load, an HR score or a tissue-specific strain.

## Formula and units

`L_session = duration_min × session_RPE`, unit arbitrary units (AU).

- `duration_min`: elapsed duration of the rated session in minutes, including
  its warm-up, cool-down and recovery parts. Moving time is not a silent
  substitute; a session that has only moving time, or an unclear long
  interruption, gets no value or is marked as a deviating duration.
- `session_RPE`: local feedback `session_rpe`, 0 to 10, step 0.5.
- Aggregation: compute each session in full precision, sum sessions per local
  day, ISO week and sport, round only for display.
- AU are never added to TSS, Garmin load, TRIMP or any provider load.
  Cross-sport sums are subjective load only.

## Sources

R1 (original method and scale), R2 (global rating differs from momentary
ratings). R14 and R15 bound what may be built on top of load sums (no ACWR
risk statement). Newer contrary finding: sRPE and HR load agree much less for
strength and functional sessions (Dai et al. 2025, see README).

## Population and reference measurement

R1: 12 trained recreational cyclists (laboratory bouts) and 14 male collegiate
basketball players, 26 independent participants; reference was summated HR
zone load (Edwards). R2: 1,184 sessions from one laboratory over 30 years;
independent participant count not available in the abstract. The reference is
another load estimate, not a gold standard.

## Protocol and data window

R1 shows a modified CR-10 scale about 30 minutes after the end of the bout and
asks "How was your workout?" for one global rating of the whole session. Scale
anchors as read from the scanned R1 figure (OCR, not visually confirmed):
0 Rest, 1 Very, Very Easy, 2 Easy, 3 Moderate, 4 Somewhat Hard, 5 Hard,
7 Very Hard, 10 Maximal; 6, 8 and 9 without anchors. R2 collected sRPE about
30 minutes after cool-down. Data window: any session with local feedback; no
history window is needed for the per-session value.

## Measurement error and uncertainty

No per-rating measurement error is used. R2 reports sRPE about 0.6 to 1.1
points above the mean of momentary ratings (abstract). R1 reports high
consistency with HR zone load but systematically higher sRPE scores. No
uncertainty interval is shown for the athlete's AU.

## Bias and transferability

R1 used laboratory bouts and team-sport practices with supervised collection;
our rating is self-reported in an app at an unrecorded time. R2 comes from one
laboratory. Ratings may be anchored by the session plan or by provider scores
shown before rating. Team-sport ACWR data (R15) do not transfer to this
endurance athlete.

## Deviations from the studied procedure

- The UI shows 0 to 10 in steps of 0.5 without the CR-10 verbal anchors.
- Collection time relative to session end is not stored; historical ratings are
  "timing unknown" and are not given protocol fidelity retroactively.
- Duration comes from provider records, not a stopwatch of the rated session.
- Intervals `icu_rpe` is a second rating source. Local `session_rpe` is the
  input (decision D3 on #1406); `icu_rpe` is used only as a labelled fallback
  when no local rating exists, never averaged with it.

## Minimum data and stop rules

- One session with a known rating and a valid duration gives one value.
- RPE 0 is valid; a missing RPE is unknown and gives no value.
- Non-positive duration, NaN, Infinity or an ambiguous session assignment are
  excluded with a reason.
- Duplicate imports of one session count once (canonical session).
- Day and week sums show the known partial sum and the count of rated and
  unrated sessions. A day without records is a rest day only with evidence.

## Numeric rules

| Rule | Value | Tag | Rationale |
| --- | --- | --- | --- |
| Rating scale range | 0 to 10 | source | CR-10 scale used in R1; enforced in `backend/activities/feedback.py:47-48`. |
| Rating step | 0.5 | product assumption | Existing UI input step in `public/activity-details.js`; R1 does not specify half steps. |
| Collection time | about 30 min after session end | source | R1 protocol; R2 after cool-down. Not enforced; unknown times stay marked. |
| Duration unit | minutes | source | R1 uses minutes for 30/60/90-min bouts. |
| Duration includes warm-up and cool-down | yes | product assumption | R1 text read does not say; R2 rated sessions including warm-up and cool-down. Decided to match the rated whole session. |
| Fallback rating source | Intervals `icu_rpe` only without local rating | product assumption | Decision D3 on #1406; keeps provider value labelled and separate. |
| Existing ATL reconstruction decay (not M1) | exp(-1/7) per day | product assumption | `backend/performance/load.py:121`; fitness-fatigue form from R17, the 7-day constant is not individually validated. Applies to imported load, never to AU. |
| Existing scenario model constants (not M1) | 42 and 7 days | product assumption | `backend/planning/season_preparation.py:260` and `:478-479`; R17 model form, parameters not validated for this athlete. |
| Duplicate session matching | start within 30 min, duration within max(120 s, 10 %), distance within max(500 m, 10 %) | product assumption | Existing canonical session bundling in `bundle_sessions`; not a scientific rule. |

## Allowed statements

- "300 AU from your RPE 5 and 60 minutes." (value, inputs and unit)
- "This week: 1,240 AU from 4 rated sessions; 1 session has no rating."
- "Your session-RPE load this week is higher than last week" (descriptive
  comparison of the athlete's own sums with coverage).
- "This value uses the Intervals.icu rating because no local rating exists."

## Forbidden statements

- Any equivalence or conversion between AU and TSS, Garmin load or TRIMP.
- Injury risk, overtraining, readiness or "safe ramp" statements from AU,
  including any ACWR (R14, R15).
- An RPE derived from heart rate, interval RPEs, provider load or AI estimate.
- Claiming the ratings follow the R1 protocol when the collection time is
  unknown.
- Treating unrated sessions or days without records as zero load.

## Open points

- Verify the CR-10 anchors in R1 visually and decide whether the rating control
  shows them (UI rule: no helper text; labelled steps instead).
- Decide whether to store a collection timestamp relative to session end
  (schema change needs migrations from v9).
- Choose the canonical elapsed-duration field and its behaviour for Garmin
  records that have only moving time (#1423, #1425).
- R2 full text (participant count, duration definition, funding and declared
  interests) was not reachable; R1 has no funding or interest statement in
  the accessible copy.
