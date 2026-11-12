## MODIFIED Requirements

### Requirement: Analyse is split by sport
The Analyse tab SHALL show the segments Laufen, Radfahren, Belastung and Erholung in this order, without a Leistung segment. Laufen and Radfahren SHALL each show only their sport's current values, best efforts, development charts and estimates; Belastung and Erholung SHALL stay sport-independent. Every value and chart of the former Leistung segment SHALL appear in exactly one segment, and an old Leistung link SHALL open Laufen.

#### Scenario: Laufen
- **WHEN** the athlete opens Analyse › Laufen
- **THEN** it shows the running current values (threshold pace, threshold power, threshold heart rate, LT1 pace and heart rate as on the zones page, VO2max), the development charts (threshold pace, VO2max, running tolerance), the best efforts of the last 90 days (best pace over 1, 3, 5, 7, 12 and 20 minutes and best time over 1 km and 5 km, each with its date and source, missing ones marked as missing) with the experimental critical-speed line, and the race predictions; no cycling value appears.

#### Scenario: Radfahren
- **WHEN** the athlete opens Analyse › Radfahren
- **THEN** it shows the cycling current values (FTP, power per weight, threshold heart rate, LT1 power and heart rate as on the zones page, VO2max), the power profile with its coverage note and the experimental critical-power line, and the development charts (FTP, VO2max); no running value appears.

#### Scenario: Cross-sport values
- **WHEN** the athlete opens Analyse › Belastung or Erholung
- **THEN** the endurance score is charted in Belastung, readiness stays in Erholung, and the weekly training status is not charted because it repeats the acute load in Belastung.

#### Scenario: Empty sport and old links
- **WHEN** one sport has no current values, charts, best efforts or estimates, or the athlete opens `#analysis/performance`
- **THEN** that sport's segment shows its one empty card while the other sport keeps its content, and the old link opens Laufen.

Evidence: `public/analysis.js::renderAnalysisSegments`, `public/analysis.js::renderRunningBestEfforts`, `public/analysis.js::criticalPowerLine`, `public/analysis.js::renderAnalysisHistory`, `public/performance-view.js::renderCurrentPerformance`, `public/navigation.js::routeFromHash`; `tests/analysis-presentation.test.cjs::an analysis segment is empty only when every content container reports no data`, `tests/analysis-presentation.test.cjs::current performance shows the status lines below its heading`, `e2e/performance-values.spec.js::@responsive Laufen and Radfahren each show only their sport`.
