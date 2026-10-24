# Performance method evidence cards

These cards fix what each local performance or recovery method in Epic S
(#1409) may and may not say before its physiological interpretation is
implemented or released (gate G0, #1424). Code, UI text and Coach context cite
a card by its `Card` ID.

| Card | Method | Classification |
| --- | --- | --- |
| [M1](m1-session-rpe-load.md) | Session-RPE load | descriptive statistic |
| [M2](m2-hrv-resting-hr.md) | Personal HRV and resting HR description | descriptive statistic |
| [M3](m3-sleep-duration-timing.md) | Sleep duration, goal shortfall and timing | descriptive statistic |
| [M4](m4-critical-power-speed.md) | Critical Power and Critical Speed | model estimate |

M5 (own smoothed load curves, passive CP/CS, HRV-based recommendations, #1432)
is deferred and has no card. It needs its own card and G0 review before work
starts.

## Three separate proofs

1. **Computational correctness:** formula, units, filters and edge cases match
   the card. Synthetic tests prove this level only.
2. **Validity for the intended use:** population, device, protocol and target
   quantity fit this application. Correlation is not agreement; repeatability
   is not validity.
3. **Individual benefit:** the output helps this athlete with a concrete
   decision. A personal observation phase checks plausibility, not general
   effectiveness.

A method can pass level 1 and stay experimental on levels 2 and 3. The level
reached stays visible in API, UI and Coach.

## Card rules

- Each card has the same front block and `##` sections;
  `tests/test_performance_method_cards.py` enforces them.
- Every numeric rule is in the `Numeric rules` table and tagged `source`
  (with an evidence ID) or `product assumption` (with a rationale). Rules
  already in code cite the code location.
- `Review` is `blocked` until the athlete's method review is recorded as
  `released YYYY-MM-DD (athlete)`. Open points block only the affected
  physiological interpretation, not correct and limited descriptive output.
- A method change bumps `Card version` together with the method version in
  code. The language model never selects formulas or parameters.

## Review procedure

The athlete is the independent method reviewer (decision on #1406,
2026-10-24). A second coding agent checks for contradictions and citation
mismatches but does not replace sports-science expertise. Because the reviewer
is not a sports scientist, a released card covers only this athlete's own use;
it is not a claim of general scientific validation.

1. The implementation author updates the card and the literature check.
2. An independent agent reviews the card against the register and code.
3. The athlete reviews the allowed and forbidden statements and records
   `released YYYY-MM-DD (athlete)` or keeps `blocked` with the open points.

## Literature currency

The register is a targeted evidence overview, not a systematic review.
Publication year, online date and search end differ: R6 searched until
2025-06-20, R15 until October 2024.

Search blocks used on 2026-10-24 (PubMed/PMC, then publisher pages and
repositories):

- `session RPE training load validity 2025 2026`
- `heart rate variability guided training systematic review meta analysis`
- `nocturnal HRV consumer wearable validation 2025`
- `critical power field testing validity 2026`,
  `critical speed field systematic review 2025`
- `sleep athlete consensus`, `sleep regularity index Phillips`
- `acute chronic workload ratio injury meta analysis 2026`

Limits: no full search in Embase, SPORTDiscus or Web of Science. The
correction and retraction check used Crossref update metadata
(`filter=updates:<doi>`) and PubMed `CommentsCorrections`, not the Retraction
Watch database directly. Numbers from full texts were extracted by a fetch tool
and spot-checked, not re-read line by line.

Before implementing a method family, repeat the search, verify DOI metadata and
corrections, and record search date, paths, inclusion reasons and access level
on its card. Older robust original work is not replaced because of age; a
perspective article does not replace a controlled trial.

**Maintenance rule (product assumption):** repeat the literature check before
each methodological release and at the latest 90 days after the last check for
an actively offered method. This is a maintenance decision, not a scientific
deadline, and is not automated.

## Evidence register

Checked 2026-10-24. Access: *abstract* = abstract and metadata only;
*full-text methods* = methods section read; *full text* = whole article read.
For every source the correction check found no erratum, correction or
retraction.

Funding and declared interests were checked for R10 only (no competing
interests declared; public research funding). For the other sources they are
not yet checked; each card lists this as an open point, and it must be
recorded before the affected interpretation is released.

| ID | Source | Access | Use and limits |
| --- | --- | --- | --- |
| R1 | Foster et al. 2001, "A new approach to monitoring exercise training", J Strength Cond Res 15(1):109-115, PMID 11708692, DOI `10.1519/00124278-200102000-00019` | full-text methods (scanned author copy, OCR) | Session load = duration × global session RPE on a modified CR-10 scale, rated about 30 min after the bout. 12 cyclists and 14 basketball players vs summated HR zones; consistent but sRPE scores higher. Not interchangeable with HR-based load. |
| R2 | Foster et al. 2026, "Systematic Differences in Mean Rating of Perceived Exertion and Session Rating of Perceived Exertion During Training and Competition", IJSPP 21(11):1233-1237, PMID 42632634, DOI `10.1123/ijspp.2025-0209`, online 2026-08-22 | abstract (publisher 403) | 1,184 observations from one laboratory; global sRPE systematically above the mean of momentary ratings, mostly at ratings of 5 or more. No reconstruction from momentary RPE. Independent participant count unknown; mechanisms not adopted. |
| R3 | Poole et al. 2016, "Critical Power: An Important Fatigue Threshold in Exercise Physiology", Med Sci Sports Exerc 48(11):2320-2334, PMID 27031742, DOI `10.1249/MSS.0000000000000939` | abstract | Narrative review; hyperbolic power-duration model with CP and W′. Model foundation, not validation of our data preparation. |
| R4 | Karsten et al. 2015 (online 2014-09-27), "Validity and reliability of critical power field testing", Eur J Appl Physiol 115(1):197-204, PMID 25260244, DOI `10.1007/s00421-014-3001-z` | abstract | Field CP from 3/7/12-min efforts (single session with 30-min recovery, separate days, or training/race files) vs lab CP. Protocol-specific errors, not an individual confidence interval. Participant count not reached. |
| R5 | Lipková et al. 2025, "Field-based tests for determining critical speed among runners and its practical application: a systematic review", Front Sports Act Living 7:1520914, PMID 40134905, DOI `10.3389/fspor.2025.1520914` | full text | Runners only, 19 studies, 285 participants, no meta-analysis or pooled agreement. Recommends 2-3 trials of 3-12 min whose durations differ by at least 7 min; recovery is protocol-specific (30-60 min in included studies). |
| R6 | Quittmann & Piehl 2026, "The 3-min all-out test in cycling: a systematic review and meta-analysis on its reliability and validity", Eur J Appl Physiol 126(9):4673-4691, PMID 42479066, DOI `10.1007/s00421-026-06356-w`, online 2026-07-21 | full text | 20 studies, 284 participants, search to 2025-06-20. End-test power above CP (mean +11.7 W, limits of agreement -37.1 to +60.5 W); work above end power does not estimate W′ accurately. Possible publication bias. |
| R7 | Vesterinen et al. 2016, "Individual Endurance Training Prescription with Heart Rate Variability", Med Sci Sports Exerc 48(7):1347-1354, PMID 26909534, DOI `10.1249/MSS.0000000000000910` | full-text methods (author final draft) | 40 recreational runners, randomised. Morning 4-min supine RMSSD, 7-day rolling mean vs mean ± 0.5 SD. Within-group gains do not prove superiority. |
| R8 | Manresa-Rocamora et al. 2021, "Heart Rate Variability-Guided Training for Enhancing Cardiac-Vagal Modulation, Aerobic Fitness, and Endurance Performance", Int J Environ Res Public Health 18(19):10299, PMID 34639599, DOI `10.3390/ijerph181910299` | full text | 8 studies, 199 participants. Pooled endurance performance and VO2max effects not significant; the abstract's SMD 0.50 is the RMSSD/SD1 subgroup, overall vagal SMD 0.15. "Not significant" is not equivalence. |
| R9 | Schaffarczyk & Sperlich 2026, "Heart rate variability-guided endurance training: evaluating strengths, weaknesses, opportunities, and threats for load prescription and adjustment", Front Sports Act Living 8:1858271, PMID 42724227, DOI `10.3389/fspor.2026.1858271` | full text | Perspective without new data. HRV is non-specific; rolling baselines drift; no validated universal readiness formula. |
| R10 | Dial et al. 2025, "Validation of nocturnal resting heart rate and heart rate variability in consumer wearables", Physiol Rep 13(16):e70527, PMID 40834291, DOI `10.14814/phy2.70527` | full-text methods | 13 healthy adults, 536 nights vs Polar H10 ECG. Garmin Fenix 6 HRV only (150 nights): bias -1.84 ms, limits of agreement -15.2 to +11.6 ms, MAPE 10.5 %; Garmin resting HR excluded (no timestamp for its lowest window). Model- and protocol-specific. Industry letter (DOI `10.14814/phy2.70710`) responds; not a correction. |
| R11 | Catai et al. 2020 (online 2019-02-26), "Heart rate variability: are you using it properly? Standardisation checklist of procedures", Braz J Phys Ther 24(2):91-102, PMID 30852243, DOI `10.1016/j.bjpt.2019.02.006` | full text | Cardiology and rehabilitation context. Duration, position, breathing, time of day and artefact editing affect comparability; no numeric artefact threshold. |
| R12 | Walsh et al. 2021 (online 2020-11-03), "Sleep and the athlete: narrative review and 2021 expert consensus recommendations", Br J Sports Med 55(7):356-368, PMID 33144349, DOI `10.1136/bjsports-2020-102025` | full text (author version and supplement) | Sleep need is individual; a blanket 7-9 h target is unlikely to fit. Wearables overestimate duration and underestimate wake vs polysomnography; stages only where validated. |
| R13 | Phillips et al. 2017, "Irregular sleep/wake patterns are associated with poorer academic performance and delayed circadian and sleep/wake timing", Sci Rep 7:3216, PMID 28607474, DOI `10.1038/s41598-017-03171-4` | full-text methods | Introduces SRI: probability of the same sleep/wake state 24 h apart, 1-min epochs, naps included, rescaled to -100..100. 61 students analysed; not a validation study, no individual diagnosis. |
| R14 | Impellizzeri et al. 2021 (online 2020-12-17), "What Role Do Chronic Workloads Play in the Acute to Chronic Workload Ratio? Time to Dismiss ACWR and Its Underlying Theory", Sports Med 51(3):581-592, DOI `10.1007/s40279-020-01378-6` | abstract | ACWR rescales acute load and adds no predictive value in the reanalysed data. Not proof that load changes are irrelevant. |
| R15 | Ding et al. 2026, "Acute:chronic workload ratio and load management for team sports: a multilevel meta-analysis", Front Public Health 14:1896651, PMID 42662491, DOI `10.3389/fpubh.2026.1896651` | abstract | 16 studies, 797 athletes, g 0.35, I² 95.8 %, search to October 2024. No standalone prediction; team sport, not an endurance athlete. |
| R16 | Smyth & Muniz-Pumares 2020, "Calculation of Critical Speed from Raw Training Data in Recreational Marathon Runners", Med Sci Sports Exerc 52(12):2637-2645, PMID 32472926, DOI `10.1249/MSS.0000000000002412` | full-text methods | Passive CS from logged runs (best 400-5000 m efforts, linear distance-time fit). No lab validation; maximality unverified; D′ imprecise. Abstract and full text disagree on the runner count. |
| R17 | Morton, Fitz-Clarke & Banister 1990, "Modeling human performance in running", J Appl Physiol 69(3):1171-1177, PMID 2246166, DOI `10.1152/jappl.1990.69.3.1171` | abstract | Fitness-fatigue model with two exponentially decaying responses. No validation of our 42-/7-day parameters. |
| L1 | Phillips & Steven 2026, "Perspective: sleep regularity—where do we go from here?", Sleep 49(8), PMID 42023690, DOI `10.1093/sleep/zsag114` | full text | Perspective without new data, formula, threshold or wearable/athlete content. Background only; not decision evidence. |

### Newer work found, not yet decision evidence

- Czeisler et al. 2026, Sleep, DOI `10.1093/sleep/zsaf299` (abstract): two
  open-source SRI calculators gave substantially different scores. An SRI
  implementation must name its exact calculator and settings.
- Dai et al. 2025, BMC Sports Sci Med Rehabil, DOI
  `10.1186/s13102-025-01247-7` (abstract): sRPE and HR load agree much less
  for functional and strength sessions than for ergometer rowing.
- Anderson et al. 2026, Sports Med, DOI `10.1007/s40279-026-02410-x`
  (abstract): scoping review of CS and D′; protocol choice changes both.
