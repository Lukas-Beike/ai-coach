# Performance method evidence cards

These cards fix what each local performance or recovery method in Epic S
(#1409) may and may not say before its physiological interpretation is
implemented or released (gate G0, #1424). Code, UI text and Coach context cite
a card by its `Card` ID.

Every named number the derived-metric code fixes is listed, generated from the
code, in [code constants](code-constants.md); each card carries the constants
of its own modules.

| Card | Method | Classification |
| --- | --- | --- |
| [M1](m1-session-rpe-load.md) | Session-RPE load | descriptive statistic |
| [M2](m2-hrv-resting-hr.md) | Personal HRV and resting HR description | descriptive statistic |
| [M3](m3-sleep-duration-timing.md) | Sleep duration, goal shortfall and timing | descriptive statistic |
| [M4](m4-critical-power-speed.md) | Critical Power and Critical Speed | model estimate |
| [M5](m5-smoothed-session-load.md) | Short- and long-term session-RPE load | model estimate |
| [M6](m6-local-tss-load.md) | Local TSS-scale session load and intensity | model estimate |
| [M7](m7-local-fitness-fatigue.md) | Local fitness, fatigue and form | model estimate |
| [M8](m8-local-session-metrics.md) | Local efficiency factor, variability index, work and decoupling | descriptive statistic |
| [M9](m9-lt1-output-own-sessions.md) | LT1 pace and power from own steady sessions | model estimate |
| [M10](m10-dfa-alpha1-first-threshold.md) | First threshold heart rate from chest-strap RR intervals (DFA-α1) | model estimate |

M5 covers the smoothed load curves (#1432). M6 (#1725) replaces provider TSS
with a local load; Banister TRIMP appears only as its heart-rate branch. M7
(#1726) smooths the M6 load into local fitness, fatigue and form in place of
the Intervals.icu CTL, ATL and form.
M9 (#2427) reads LT1 pace and power at the LT1 heart rate from the athlete's
own steady sessions.
M10 (#2131) derives the first threshold heart rate from chest-strap RR
intervals (DFA-α1) per session and as an athlete-level estimate that only the
athlete can adopt into the profile. Passive CP/CS, other TRIMP uses, further
threshold or VO2max estimates, W′ balance and HRV-based recommendations stay
deferred without a card.

Method ids, versions, statuses and limits of the offered methods are
registered in `openspec/specs/performance-and-readiness/spec.md`;
`tests/test_performance_coach_ui_parity.py` checks that Coach and UI show the
same value, status and scope (gate G5, #1433). No observation phase has run;
one needs the athlete's consent with scope and duration fixed in advance.

[Method inputs](inputs.md) records where each card's inputs are stored, how
they reach API, UI and Coach, and which data gaps remain (gate G1, #1425).

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

### Funding and declared interests

Checked 2026-10-24 from the publication text. "No statement" means none in the
accessible text, not a declared absence.

| ID | Funding | Declared interests | Relevant industry tie | Access |
| --- | --- | --- | --- | --- |
| R1 | no statement | no statement | unknown | full text (third-party copy) |
| R2 | no statement | no statement | unknown | abstract |
| R3 | AHA and NIH grants (in part) | no statement | no (funding) | full text (author manuscript) |
| R4 | none received | none declared | no | full text |
| R5 | Czech Ministry of Education via university grant | none declared | no | full text |
| R6 | open-access funding only | none declared | no | full text |
| R7 | Finnish Ministry of Education and Culture | none declared | no | full text (author draft) |
| R8 | Spanish ministry grants | one author: one-time fees from PUSH, Inc. and Head's Up Health | yes, minor (wearable and HRV-app vendors) | full text |
| R9 | none received | none declared | no | full text |
| R10 | Air Force Research Laboratory | none declared | no | full text |
| R11 | CNPq scholarship | none declared | no | full text |
| R12 | no specific grant | one author: consulting for Fitbit and sleep, supplement and pharma companies; others: sport-agency grants | yes (wearable maker, one author) | full text (author version) |
| R13 | NIH, NSBRI and others | several authors: equity, royalties or consulting with wearable and sleep-technology makers (e.g. Empatica, Apple, Philips, Actiwatch devices) | yes (wearable and sleep technology) | full text |
| R14 | none received | none declared | no | full text |
| R15 | Shanghai science commission grant | none declared | no | full text |
| R16 | no statement | none declared | no | full text |
| R17 | Engineering research council of Canada | no statement | no | full text (third-party copy) |
| R18 | not applicable (book) | not checked | yes: authors linked to WKO/TrainingPeaks metrics | metadata only |
| R19 | not applicable (book chapter) | no statement | unknown | metadata only |
| R20 | no statement | no statement | unknown | abstract |
| R21 | no statement | no statement | unknown | abstract |
| R22 | no statement | no statement | unknown | abstract |
| R23 | no statement | no statement | unknown | abstract |
| R24 | no statement | no statement | unknown | abstract |
| R25 | no statement (author manuscript) | no statement | no | full-text methods |
| R26 | no statement | no statement | unknown | abstract |
| R27 | no statement | no statement | unknown | abstract |
| R28 | no statement | none declared | no | abstract |
| R29 | none (Europe PMC) | no statement | no | abstract |
| R30 | no statement | no statement | unknown | abstract |
| R31 | no statement | no statement | unknown | abstract |
| L1 | no statement | one author: funding from lighting and circadian-health companies, company co-founder | yes, indirect (lighting) | full text |

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
| R18 | Allen, Coggan & McGregor 2019, *Training and Racing with a Power Meter*, 3rd ed., VeloPress, ISBN 978-1-937715-93-9 | metadata only (book not read) | Origin of NP, IF and TSS. Formula `TSS = s × NP × IF / (FTP × 3600) × 100` confirmed only in vendor text (V1); NP definition (30-s rolling mean, 4th power) not verified from the book. Not peer-reviewed; author interest. |
| R19 | Banister 1991, "Modeling elite athletic performance", in MacDougall, Wenger & Green (eds), *Physiological Testing of the High-Performance Athlete*, 2nd ed., Human Kinetics, pp. 403-424 or 403-425 (sources disagree), ISBN 0-87322-300-4 | metadata only | Average-HR TRIMP with HR reserve. Male weighting 0.64·e^(1.92·HRr) as cited elsewhere, not verified from the chapter; R25 prints 0.84 instead of the usual 0.86 for the female constant. |
| R20 | Sanders et al. 2017, "Methods of Monitoring Training Load and Their Relationships to Changes in Fitness and Performance in Competitive Road Cyclists", IJSPP 12(5):668-675, PMID 28095061, DOI `10.1123/ijspp.2016-0454` | abstract | 15 well-trained cyclists, 10 weeks. TSS vs change in power at 2 and 4 mmol/L: r = .75 and .79 (wide CIs); iTRIMP similar; luTRIMP strongest for the time trial. Group dose-response only, no agreement between methods. |
| R21 | van Erp et al. 2019, "The Influence of Exercise Intensity on the Association Between Kilojoules Spent and Various Training Loads in Professional Cycling", IJSPP 14(10):1395-1400, PMID 30958053, DOI `10.1123/ijspp.2018-0877` | abstract | 21 professionals, 11,716 sessions. Intensity changes the kJ-TSS relation but not kJ-sRPE or kJ-luTRIMP; TSS is not interchangeable with HR load. |
| R22 | Vermeire et al. 2021, "The Influence of Different Training Load Quantification Methods on the Fitness-Fatigue Model", IJSPP 16(9):1261-1269, PMID 33691278, DOI `10.1123/ijspp.2020-0662` | abstract | 9 participants, 8 weeks. Similar model error for Banister, Lucia and Edwards TRIMP, TSS and sRPE, but the load series evolve differently; "cannot be used interchangeably". |
| R23 | Vermeire et al. 2023, "Training Load and Acute Performance Decrements Following Different Training Sessions", IJSPP 18(3):284-292, PMID 36716743, DOI `10.1123/ijspp.2022-0157` | abstract | 11 recreational cyclists, 4 sessions. TSS and iTRIMP over-express intensity; only sRPE matched the acute performance drop. |
| R24 | Kesisoglou, Nicolò & Passfield 2021, "Cycling Performance and Training Load: Effects of Intensity and Duration", IJSPP 16(4):535-543, PMID 33059328, DOI `10.1123/ijspp.2020-0072` | abstract | 14 cyclists. Load metrics including TSS differed across bouts while the acute performance drop did not. |
| R25 | Kesisoglou et al. 2021, "Continuous Versus Intermittent Running: Acute Performance Decrement and Training Load", IJSPP 16(12):1794-1803, PMID 34021094, DOI `10.1123/ijspp.2020-0844` | full-text methods (author manuscript) | 11 runners (10 men). rTSS with threshold pace assumed at 88 % of 10-min speed; rTSS and the TRIMPs moved opposite to the performance drop. Evidence against, not a validation. |
| R26 | Wallace et al. 2014, "Establishing the criterion validity and reliability of common methods for quantifying training load", J Strength Cond Res 28(8):2330-2337, PMID 24662229, DOI `10.1519/JSC.0000000000000416` | abstract | 10 recreational athletes vs VO2. Test-retest CV: Banister TRIMP 15.6 %, Lucia TRIMP 10.7 %, sRPE 28.1 %. No TSS. |
| R27 | Klitzke Borszcz et al. 2019, "Is the Functional Threshold Power Interchangeable With the Maximal Lactate Steady State in Trained Cyclists?", IJSPP 14(8):1029-1035, PMID 30676826, DOI `10.1123/ijspp.2018-0572` | abstract | 15 cyclists. FTP vs MLSS bias 1.4 % ± 9.2 % (95 % limits of agreement). |
| R28 | Klitzke Borszcz et al. 2020, "Reliability of the Functional Threshold Power in Competitive Cyclists", Int J Sports Med 41(3):175-181, PMID 31952081, DOI `10.1055/a-1018-1965` | abstract | 25 cyclists; 20-min test CV 2.9 %, ICC 0.97. |
| R29 | Wong et al. 2022 (online 2023-02-20), "Functional threshold power is not a valid marker of the maximal metabolic steady state", J Sports Sci 40(23):2578-2584, PMID 36803419, DOI `10.1080/02640414.2023.2176045` | abstract | 13 cyclists; time to failure at FTP 33.7 ± 7.6 min. IF = 1 is not the heavy/severe boundary. |
| R30 | McGregor, Weese & Ratz 2009, "Performance modeling in an Olympic 1500-m finalist: a practical approach", J Strength Cond Res 23(9):2515-2523, PMID 19910822, DOI `10.1519/JSC.0b013e3181bf88be` | abstract | One elite runner, pace-based TSS. Use case, not a validation; no formula in the abstract. |
| R31 | Bossi et al. 2026, "Quantifying and Comparing Training Load Metrics in Cycling: A Methodology Review", Int J Sport Nutr Exerc Metab 36(5):588-598, PMID 42315095, DOI `10.1123/ijsnem.2026-0028` | abstract | Teaching review of how TSS, Edwards TRIMP and sRPE are computed and compared; no pooled agreement. |
| R32 | Coyle & González-Alonso 2001, "Cardiovascular drift during prolonged exercise: new perspectives", Exerc Sport Sci Rev 29(2):88-92, PMID 11337829, DOI `10.1097/00003677-200104000-00009` | abstract | Review. Stroke volume falls progressively after 10-20 min, mainly because HR rises. Mechanism for the warm-up exclusion, not a validated cut-off. |
| R33 | Hamilton et al. 1991, "Fluid replacement and glucose infusion during exercise prevent cardiovascular drift", J Appl Physiol 71(3):871-877, PMID 1757323, DOI `10.1152/jappl.1991.71.3.871` | abstract | 10 trained cyclists, 2 h at 70 % VO2max, 22 °C. HR +10 % from 20 to 120 min without fluid (2.9 % mass loss), +5 % with full replacement. Hydration confounds decoupling. |
| R34 | Wingo, Ganio & Cureton 2012, "Cardiovascular drift during heat stress: implications for exercise prescription", Exerc Sport Sci Rev 40(2):88-94, PMID 22410803, DOI `10.1097/JES.0b013e31824c43af` | abstract | Review. Drift starts about 10 min into moderate exercise; in heat the higher HR reflects a higher relative intensity. |
| R35 | Wingo, Stone & Ng 2020, "Cardiovascular Drift and Maximal Oxygen Uptake during Running and Cycling in the Heat", Med Sci Sports Exerc 52(9):1924-1932, PMID 32102057, DOI `10.1249/MSS.0000000000002324` | abstract | 7 men, 60 % VO2max at 35 °C: HR +19 % running, +17 % cycling between 15 and 45 min. Heat alone exceeds any decoupling band. |
| R36 | Maunder et al. 2021, "The Importance of 'Durability' in the Physiological Profiling of Endurance Athletes", Sports Med 51(8):1619-1628, PMID 33886100, DOI `10.1007/s40279-021-01459-0` | abstract | Narrative review; defines durability. Concept only, no decoupling formula or threshold. |
| R37 | Smyth et al. 2022, "Decoupling of Internal and External Workload During a Marathon", Sports Med 52(9):2283-2295, PMID 35511416, DOI `10.1007/s40279-022-01680-5` | abstract | 82,303 recreational marathon runners; a different ratio ((%HRmax)/(speed/CS), 35-40 km vs 5-10 km). Lower decoupling went with better performance. Observational; its bands do not transfer to Pa:HR. |
| R38 | Barsumyan et al. 2026, "The relationship between cadence decline, cardiovascular drift and aerobic decoupling as a marker of fatigue in well trained cyclists", BMC Sports Sci Med Rehabil 18(1):179, PMID 41923151, DOI `10.1186/s13102-026-01678-w` | full-text methods | 17 trained men, 60 min at 75 % FTP indoors with fan and fluid; Pw:HR 0-30 vs 31-60 min: 2.00 ± 2.38 %. No threshold. Convenience sample. |
| R39 | Barsumyan et al. 2025, "Quantifying training response in cycling based on cardiovascular drift using machine learning", Front Artif Intell 8:1623384, PMID 40687435, DOI `10.3389/frai.2025.1623384` | abstract | 20 athletes over 5 months; drift and Pw:HR decoupling strongly correlated. Not a reliability study; classifier not externally validated. |
| R40 | Cartón-Llorente, García-Pinillos & Jaén-Carrillo 2026, "Power-Based Running Durability in Trained Runners", Eur J Sport Sci 26(11):e70275, PMID 42897874, DOI `10.1002/ejsc.70275` | abstract | 12 trail runners, footpod power; adjusted for speed, running power did not drift. Background for runs with power. |
| R41 | Ettema & Lorås 2009, "Efficiency in cycling: a review", Eur J Appl Physiol 106(1):1-14, PMID 19229554, DOI `10.1007/s00421-009-1008-7` | abstract | Energy expenditure is linear in work rate; gross efficiency depends on work rate. A fixed kJ-to-kcal factor is an approximation. |
| R42 | Moseley & Jeukendrup 2001, "The reliability of cycling efficiency", Med Sci Sports Exerc 33(4):621-627, PMID 11283439, DOI `10.1097/00005768-200104000-00017` | abstract | 17 men: gross efficiency 19.8 ± 0.6 %, test-retest CV 4.2 %. Lab value, not a field constant. |
| R43 | Hopker et al. 2009, "The effects of training on gross efficiency in cycling: a review", Int J Sports Med 30(12):845-850, PMID 19941249, DOI `10.1055/s-0029-1237712` | abstract | Training can raise gross efficiency, so work-to-energy varies within an athlete. |
| R44 | Minetti et al. 2002, "Energy cost of walking and running at extreme uphill and downhill slopes", J Appl Physiol 93(3):1039-1046, PMID 12183501, DOI `10.1152/japplphysiol.01177.2001` | abstract | 10 elite mountain runners on a treadmill, slopes −0.45 to +0.45; cost of running as a polynomial of slope. Laboratory model, not Garmin's GAP; used for grade-adjusted speed (M8, pace at heart rate). |
| R45 | Sweet et al. 2004, "Quantitation of resistance training using the session rating of perceived exertion method", J Strength Cond Res 18(4):796-802, PMID 15574104, DOI `10.1519/14153.1` | abstract | Session RPE in resistance training rose with lifting intensity while total work fell; session RPE may underrate the mean of per-set ratings. Supports the AU of strength sessions, not a conversion into TSS. |
| R46 | Day et al. 2004, "Monitoring exercise intensity during resistance training using the session RPE scale", J Strength Cond Res 18(2):353-358, PMID 15142026, DOI `10.1519/R-13113.1` | abstract | Session RPE distinguished resistance-training intensities; ICC 0.88. No TSS conversion. |
| R47 | Plews et al. 2012, "Heart rate variability in elite triathletes, is variation in variability the key to effective training? A case comparison", Eur J Appl Physiol 112(11):3729-3741, PMID 22367011, DOI `10.1007/s00421-012-2354-4` | abstract | Two elite triathletes; the 7-day rolling mean of ln(RMSSD) and its CV followed training better than single days. Case comparison, morning recordings. |
| R48 | Plews et al. 2014, "Monitoring training with heart-rate variability: how much compliance is needed for valid assessment?", IJSPP 9(5):784-791, DOI `10.1123/IJSPP.2013-0455` | abstract | Trained triathletes; ln(RMSSD) averaged over 1-7 random days per week; standardised changes and correlations plateau after 3-4 days; recommends at least 3 valid days per week. |
| R49 | Buchheit 2014, "Monitoring training status with HR measures: do all roads lead to Rome?", Front Physiol 5:73, PMID 24578692, DOI `10.3389/fphys.2014.00073` | abstract | Review; recommends log-transformed vagal HRV indices and weekly means over single values; interpretation depends on context. |
| R50 | Mattioni Maturana et al. 2018, "Critical power: How different protocols and models affect its determination", J Sci Med Sport 21(7):742-747, PMID 29203319, DOI `10.1016/j.jsams.2017.11.015` | abstract | 13 trained cyclists, five exhaustive trials of about 1-20 min on separate days. CP was considerably overestimated when only trials under 10 min entered the fit, independent of the model; fits with two trials of 12-20 min agreed well with the criterion for CP and W′. Lab trials, not training files. |
| R51 | Hunter, Ledger & Muniz-Pumares 2023, "Remote determination of critical speed and critical power in recreational runners", IJSPP, PMID 37888148 | abstract | 23 recreational runners, 8 weeks of foot-pod training data vs time trials and 3-min all-out tests. CS/CP from habitual training agreed with the tests; D′/W′ agreed only weakly and were moderately reliable. Running, not cycling. |
| R52 | Manzi et al. 2009, "Relation between individualized training impulses and performance in distance runners", Med Sci Sports Exerc 41(11):2090-2096, PMID 19812506, DOI `10.1249/MSS.0b013e3181a6a959` | abstract (PubMed summary) | 8 recreational runners over 8 weeks: a training impulse weighted by each runner's own heart-rate and lactate profiles correlated with gains in speed at 2 and 4 mmol/L lactate and with 5 and 10 km performance; group-average weights did not. Small sample. Supports summing the impulse over the heart-rate distribution; the card keeps Banister weights. |
| R53 | Charoensap et al. 2025 (author order differs between sources), "Durability of the moderate-to-heavy intensity transition can be predicted using readily available markers of physiological decoupling", Eur J Appl Physiol 125:2911-2920, PMC12479576 | abstract | 51 trained cyclists pooled from four studies; power at VT1 before and after about 2.5 h of moderate cycling; HR decoupling correlated with the VT1 power loss (r = −0.76), respiratory frequency weaker, ventilation not. Candidate reference for M8; laboratory sessions, not field files. |
| R54 | Faude, Kindermann & Meyer 2009, "Lactate threshold concepts: how valid are they?", Sports Med 39(6):469-490, PMID 19453206, DOI `10.2165/00007256-200939060-00003` | abstract | Review of 25 lactate threshold concepts; the first rise of lactate above baseline (LT1) lies close to the first ventilatory threshold. Laboratory step tests; defines the target construct of M9, which does not measure it. |
| R55 | Seiler 2010, "What is best practice for training intensity and duration distribution in endurance athletes?", IJSPP 5(3):276-291, PMID 20861519, DOI `10.1123/ijspp.5.3.276` | abstract | Descriptive review; three-zone model with LT1/VT1 as the upper boundary of the easy zone. Background for M9, not a validation of field readings. |
| R56 | Rogers et al. 2021 (online 2021-01-15), "A New Detection Method Defining the Aerobic Threshold for Endurance Exercise and Training Prescription Based on Fractal Correlation Properties of Heart Rate Variability", Front Physiol 11:596567, PMID 33519504, DOI `10.3389/fphys.2020.596567` | full text | 17 men aged 19-52 (15 analysed), incremental treadmill run, ECG RR series, Kubios with smoothness-priors λ = 500, 2-minute windows recalculated every 5 s, box sizes 4-16. HR at DFA-α1 0.75 (154 bpm) against gas-exchange VT1 (152 bpm): r = 0.97, ICC 0.96. No women; the only artifacts were atrial premature beats; laboratory, not field files. |
| R57 | Gronwald, Rogers & Hoos 2020, "Fractal Correlation Properties of Heart Rate Variability: A New Biomarker for Intensity Distribution in Endurance Exercise and Training Prescription?", Front Physiol 11:550572, PMID 33071812, DOI `10.3389/fphys.2020.550572` | abstract | Perspective; DFA-α1 as a possible marker for intensity distribution from non-invasive wearables. Hypothesis, no new data. |
| R58 | Rogers & Gronwald 2022 (online 2022-05-09), "Fractal Correlation Properties of Heart Rate Variability as a Biomarker for Intensity Distribution and Training Prescription in Endurance Exercise: An Update", Front Physiol 13:879071, PMID 35615679, DOI `10.3389/fphys.2022.879071` | abstract | Narrative update by the same group: 0.75 as midpoint between correlated and uncorrelated behaviour, associated with the aerobic threshold in elite, recreational and cardiac populations; minimal bias at artifact levels below 3 %, negligible HRVT change at 6 %. Not an independent validation. |
| R59 | Gronwald & Hoos 2020 (online 2019-09-09), "Correlation properties of heart rate variability during endurance exercise: A systematic review", Ann Noninvasive Electrocardiol 25(1):e12697, PMID 31498541, DOI `10.1111/anec.12697` | abstract | 11 studies of acute dynamic endurance exercise; DFA-α1 distinguishes intensities, exercise durations and movement frequencies. Descriptive; no threshold agreement pooled. |
| R60 | Peng, Havlin, Stanley & Goldberger 1995, "Quantification of scaling exponents and crossover phenomena in nonstationary heartbeat time series", Chaos 5(1):82-87, PMID 11538314, DOI `10.1063/1.166141` | abstract | Introduces DFA for nonstationary heartbeat series with short- and long-range scaling exponents. Method origin; not an exercise study. |
| R61 | Tarvainen, Ranta-aho & Karjalainen 2002, "An advanced detrending method with application to HRV analysis", IEEE Trans Biomed Eng 49(2):172-175, PMID 12066885, DOI `10.1109/10.979357` | abstract | Smoothness-priors detrending acting as a time-varying high-pass filter before HRV analysis. Method origin; λ is a free parameter. |
| R62 | Schaffarczyk, Rogers, Reer & Gronwald 2022, "Validity of the Polar H10 Sensor for Heart Rate Variability Analysis during Resting State and Incremental Exercise in Recreational Men and Women", Sensors 22(17):6536, PMID 36081005, DOI `10.3390/s22176536` | abstract | 25 participants, cycling ramp. RR and heart rate: minimal bias against ECG; DFA-α1 shows significant bias and wider limits of agreement during exercise, up to -41 to +58 % at high intensity. One chest-strap model. |
| L1 | Phillips & Steven 2026, "Perspective: sleep regularity—where do we go from here?", Sleep 49(8), PMID 42023690, DOI `10.1093/sleep/zsag114` | full text | Perspective without new data, formula, threshold or wearable/athlete content. Background only; not decision evidence. |

### Vendor documentation (not peer-reviewed)

| ID | Source | Access | Use and limits |
| --- | --- | --- | --- |
| V1 | TrainingPeaks articles: Friel 2009, https://www.trainingpeaks.com/learn/articles/estimating-training-stress-score-tss/ ; McGregor 2008 (updated 2026-04-13), https://www.trainingpeaks.com/learn/articles/running-training-stress-score-rtss-explained/ | full text (web) | TSS formula as text. The rTSS formula appears only as an image, so `hours × IF² × 100` for pace is unverified. |
| V2 | Intervals.icu forum, developer posts 2020-03-21 and 2020-03-26, https://forum.intervals.icu/t/hrss-normalized-trimp-training-load/569 | full text (web) | HRSS = normalised TRIMP, "100 = 1h max effort"; no formula, constants or peer-reviewed source. |
| V3 | Friel, TrainingPeaks, "Efficiency Factor and Decoupling" (2011-12-07, updated 2026-07-18), https://www.trainingpeaks.com/blog/efficiency-factor-and-decoupling/ | full text (web) | EF ride = NP / avg HR, run = normalized graded speed / avg HR; decoupling = (EF1 − EF2)/EF1 on a steady effort; "5 % or less" as a preference, no citations. |
| V4 | Friel, TrainingPeaks, "Aerobic Endurance and Decoupling" (2008-10-10, updated 2026-06-03), https://www.trainingpeaks.com/learn/articles/aerobic-endurance-and-decoupling/ | full text (web) | Bands < 5 %, 5-10 %, > 10 %, with "There's no hard research-based rule here"; heat and dehydration named as causes. |
| V6 | Garmin, "HRV Status" (health science page, https://www.garmin.co.jp/minisite/garmin-technology/health-science/hrv-status) and device manuals ("Daily RHR is calculated using the lowest 30 minute average in a 24 hour period", as quoted in Garmin forums) | search snippet only | HRV status = seven-night average of overnight HRV against a slowly adapting personal baseline after about three weeks; no formula. Resting HR definition as quoted, not verified from a manual page. |
| V5 | TrainingPeaks Help, "Aerobic Decoupling and Efficiency Factor" (204071724) and "Variability Index (VI)" (204071734) | search snippet only | VI = NP / AP; steady ride 1.00-1.02, MTB or cyclocross 1.13-1.50; decoupling under 20 min "not as valid". Not verified from the page. |

M8 search on 2026-11-07 (PubMed E-utilities, Crossref, vendor pages):
`aerobic decoupling`, `cardiovascular drift[ti] AND (2023:2026[dp])`,
`cardiac drift heat cycling`, `durability[ti] AND endurance AND (2024:2026[dp])`,
`efficiency factor[ti] AND heart rate`, `variability index AND normalized power`,
`gross efficiency cycling review`, author searches for R32-R43. Crossref
`filter=updates:<doi>` and PubMed `CommentsCorrections` found no correction or
retraction for R32-R43. No peer-reviewed validity or reliability study of EF or
VI and no peer-reviewed decoupling threshold was found.
R44 was added on 2026-11-07 (#1770) from a bibliographic search (PubMed
ID, repository records); its correction status was not checked.
R47 to R49 and V6 were added on 2026-11-07 (#1772) from a web search
(`Garmin HRV status 7-day average baseline`, `Plews 2014 compliance ln
rMSSD`, `Garmin resting heart rate lowest 30-minute average`) and the science
review's citations; their correction status was not checked.
R53 was added on 2026-11-08 (#1773) from a web search (`2025 European Journal
of Applied Physiology aerobic decoupling first ventilatory threshold
durability`); its correction status was not checked.
R50 and R51 were added on 2026-11-08 (#1773) from a web search
(`Mattioni Maturana 2018 critical power trial duration`, `Hunter 2023 critical
power W' training data`) and the science review's citations; their correction
status was not checked.
R45 and R46 were added on 2026-11-07 (#1771) from a web and PubMed search
(`session RPE resistance training`, TrainingPeaks and Intervals.icu pages on
TSS from RPE); no study converting session-RPE AU into TSS was found. Their
correction status was not checked.
R54 and R55 were added on 2026-11-12 (#2427) from a web search (`heart rate
drift test aerobic threshold validity`, `Firstbeat aerobic threshold heart rate
speed`, `intervals.icu DFA a1 aerobic threshold`) and the method document on
the issue; no peer-reviewed validation of a decoupling or drift test against a
laboratory LT1 was found. Their correction status was not checked.
R56 to R62 were added on 2026-11-13 (#2131) for M10 from bibliographic
records (Crossref, Europe PMC); R56 was read in full text (methods, limits),
the others by abstract. Searches: `DFA alpha1 first ventilatory threshold`,
`Rogers Gronwald fractal correlation properties heart rate variability`,
`smoothness priors detrending HRV`. Crossref `filter=updates:<doi>` found no
correction or retraction for R56 to R62. No independent field validation of a
DFA-α1 threshold from uncontrolled outdoor sessions and no study of optical
heart-rate RR was found in this targeted search.
R52 was added on 2026-11-08 (#1773) from a PubMed search
(`Manzi individualized training impulse`); its correction status was not
checked.

M6 search on 2026-11-06 (PubMed E-utilities, Europe PMC, publisher and vendor
pages): `"training stress score"[tiab] AND 2020:2026[dp]`,
`"normalized power"[tiab] AND (cycling OR cyclists) AND 2018:2026[dp]`,
`functional threshold power validity cyclists`, `hrTSS[tiab]`, `rTSS[tiab]`,
`"running power" AND (training load OR stress score)`, internal vs external
load in endurance athletes 2023-2026, and systematic reviews of training load
2023-2026. Crossref `filter=updates:<doi>` and PubMed `CommentsCorrections`
found no correction or retraction for R20-R31. No 2023-2026 systematic review
on internal vs external load agreement in endurance athletes was found.

### Newer work found, not yet decision evidence

- Czeisler et al. 2026, Sleep, DOI `10.1093/sleep/zsaf299` (abstract): two
  open-source SRI calculators gave substantially different scores. An SRI
  implementation must name its exact calculator and settings.
- Dai et al. 2025, BMC Sports Sci Med Rehabil, DOI
  `10.1186/s13102-025-01247-7` (abstract): sRPE and HR load agree much less
  for functional and strength sessions than for ergometer rowing.
- Anderson et al. 2026, Sports Med, DOI `10.1007/s40279-026-02410-x`
  (abstract): scoping review of CS and D′; protocol choice changes both.
