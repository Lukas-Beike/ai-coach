## MODIFIED Requirements

### Requirement: Domain views preserve supplied facts and source distinctions
The client SHALL present domain-provided planning, performance, activity, and equipment facts with their dates, units, source distinctions, and missing-data states. Rendering or opening a domain view SHALL not itself substitute for an authorized durable domain action.

#### Scenario: Agenda, library, and season
- **WHEN** the athlete opens plan overview, library, or season
- **THEN** the agenda prioritizes dates and sessions with expandable weather/details, the active undated library is grouped by sport, and season calculations retain their evidence and estimate labels; explicit preview/apply/export effects remain governed by the planning domain.

#### Scenario: Performance and recovery charts
- **WHEN** domain series contain sparse, stale, current, or missing observations
- **THEN** charts/tables retain dates, gaps, provenance and period-specific coverage, distinguish current reference lines from historical observations, and avoid fabricating normal ranges or duplicate prediction charts.

#### Scenario: Recovery comparison wording and band
- **WHEN** the Erholung view shows the HRV or resting-HR comparison for the athlete's earlier values
- **THEN** the labels call it the range of the athlete's earlier values with its quartile limits, provisional state and earlier-night count, use no "normal", "usual", "green", "Basis" or "confirmed" wording and no helper sentence repeating it, the band uses a neutral colour whose series strokes keep at least 3:1 contrast against it in the light and dark themes, and the sleep chart shows no band.

#### Scenario: Activity list and detail measurements
- **WHEN** the athlete expands a completed session or activity details
- **THEN** sport-appropriate pace/speed and cadence/step-frequency channels, units, missing points, and available metadata remain readable; failed detail loading retains the session summary and its explicit refresh path.

#### Scenario: Equipment and maintenance
- **WHEN** equipment is displayed or maintenance is requested
- **THEN** local authoritative items and imported/archived sources remain distinguishable, and only eligible active local gear offers the maintenance action under the equipment domain contract.

Evidence: `public/plan-views.js::renderPlanned`, `public/plan-views.js::renderLibrary`, `public/analysis.js::renderAnalysisHistory`, `public/analysis.js::renderTrainingRecords`, `public/analysis.js::recoveryReferenceLabel`, `public/analysis.js::renderRecoveryCharts`, `public/performance-view.js::renderPerformance`, `public/activity-analysis.js::renderPanel`, `public/activity-details.js::render`; `e2e/contracts.spec.js::planned agenda prioritizes dates and sessions with compact weather and expandable details`, `e2e/analysis-info.spec.js::@responsive latest measurement stays visible without inventing measurements in empty weeks`, `e2e/analysis-info.spec.js::@responsive recovery uses independent scales, honest coverage over exactly fourteen days`, `e2e/activity-details.spec.js::@responsive analysis lists sessions whose details failed to load`, `e2e/training-feature-panels.spec.js::@responsive equipment keeps local authority and groups archived sources`. Source sections and these browser scenarios were inspected; this requirement does not independently re-specify backend calculations.
