## MODIFIED Requirements

### Requirement: Domain views preserve supplied facts and source distinctions
The client SHALL present domain-provided planning, performance, activity, and equipment facts with their dates, units, source distinctions, and missing-data states. Rendering or opening a domain view SHALL not itself substitute for an authorized durable domain action.

#### Scenario: Agenda, library, and competitions
- **WHEN** the athlete opens plan overview, library, or the competitions tab
- **THEN** the agenda prioritizes dates and sessions with expandable weather/details, the active undated library is grouped by sport, and the competitions tab lists the saved competitions with their source labels; explicit preview/apply/export effects remain governed by the planning domain.

#### Scenario: Compact calendar week
- **WHEN** the athlete opens the calendar with past, today's and planned sessions
- **THEN** it shows the current week as a timeline (weekday and date column, today filled) with previous/next week buttons and the ISO week, limited to the configured weeks ahead (the configured weeks back load at once; paging back has no limit and older weeks load their completed sessions on demand); each session is one compact row with sport icon, title, duration and distance and, for a planned unit only, a zone bar for its workout profile (16 px high on narrow screens); a completed or missed unit is one slim row whose line holds the time and the status ("✓ Absolviert" with the share of the plan, "✓ Zusätzlich", "✕ Nicht absolviert") without zone or compliance bar, its activity name shown without the place prefix of the profile's weather location; opened, it shows its chart, each value once with German labels and per sport (runs and rides have their own lists, a value without data is left out), the plan line, the "Details" toggle, "Mit dem Coach analysieren" and "Feedback" (see "Calendar cards carry the single-session analysis"); planned sessions are dashed, completed ones solid and missed ones outlined in red; identical extra activities of a day form one row; on screens at least 1100 px wide the opened session shows as a detail pane beside the week, level with its card (title, day, status, larger profile with its axis, and the session details), and one session of the week is opened by default; a "Woche | Monat" switch (never stored, entering the calendar shows the week again) shows the month of the selected day as whole weeks Monday to Sunday with neighbouring days muted, one mark per session (a dot coloured by sport, outlined when planned, red when missed; a duration chip and the ISO week with its planned time on wide screens), today filled, the selected day ringed and the current week tinted, and selecting a day shows its week below; "Zusätzlich" appears only in weeks with a plan; the week summary is a fixed planned/completed grid with one duration format and no dash-only rows; calendar notes are neutral text, each conflict is one component with one Coach action, and weeks with workout profiles show a zone legend.

#### Scenario: Provider send state of plan entries
- **WHEN** the athlete views a pending planned unit, a strength unit Garmin cannot receive, or a changed Wahoo library workout
- **THEN** a pending unit offers a "Synchronisieren" action that queues only that unit's push; a blocked strength unit names the reason (no strength structure or an unmapped exercise) with a "Mit Coach strukturieren" action or exercise suggestions; a changed library workout shows "Wahoo: geändert" with an explicit send, and opening a view sends nothing.

#### Scenario: Loading, empty, missing and failed reads
- **WHEN** an analysis or session read is pending, has no data yet, lacks a single value, or fails
- **THEN** a pending read shows a busy status line; an install without data shows one empty card per analysis tab with one action (the connections when no Garmin or Wahoo source is connected, "12 Wochen anzeigen" when a source is connected and the tab shows the 14-day period, otherwise a sync); a missing value reads "nicht erfasst" in a muted style; a failed or 15-second timed-out read shows a "Konnte nicht geladen werden." alert with an "Erneut versuchen" action and neither a permanent loading line nor the empty card.

#### Scenario: Chart units and labels
- **WHEN** an analysis chart plots daily values, weekly sums, or weekly means
- **THEN** its axis names the unit and the aggregation (for example "h · Wochensumme", "Schritte/Tag · Wochenmittel"), whole-number metrics show whole numbers, and value labels stay inside the chart and off marks and other labels.

#### Scenario: Performance and recovery charts
- **WHEN** domain series contain sparse, stale, current, or missing observations
- **THEN** charts/tables retain dates, gaps, provenance and period-specific coverage, distinguish current reference lines from historical observations, and avoid fabricating normal ranges or duplicate prediction charts.

#### Scenario: Recovery comparison wording and band
- **WHEN** the Erholung view shows the HRV or resting-HR comparison for the athlete's earlier values
- **THEN** the labels call it the range of the athlete's earlier values with its quartile limits, provisional state and earlier-night count, use no "normal", "usual", "green", "Basis" or "confirmed" wording and no helper sentence repeating it, the band uses a neutral colour whose series strokes keep at least 3:1 contrast against it in the light and dark themes, and the sleep chart shows no band.

#### Scenario: Seven-day HRV mean
- **WHEN** the Erholung view has at least three nights of HRV in the last seven days
- **THEN** its information text adds the seven-day mean of ln(RMSSD) back-transformed to milliseconds with the night count, its position below, in or above the athlete's range, the variation and a provisional marker; otherwise it states the missing minimum.

#### Scenario: Activity list and detail measurements
- **WHEN** the athlete opens a completed session's "Details" in its calendar card or its "Feedback" dialog
- **THEN** sport-appropriate pace/speed and cadence/step-frequency channels, units, missing points, and available metadata remain readable; failed detail loading retains the session summary and its explicit refresh path.

#### Scenario: Equipment and maintenance
- **WHEN** equipment is displayed or maintenance is requested
- **THEN** local authoritative items and imported/archived sources remain distinguishable, and only eligible active local gear offers the maintenance action under the equipment domain contract.

Evidence: `public/plan-views.js::renderPlanned`, `public/plan-views.js::renderLibrary`, `public/analysis.js::renderAnalysisHistory`, `public/analysis.js::renderTrainingRecords`, `public/analysis.js::recoveryReferenceLabel`, `public/analysis.js::recoveryRollingNote`, `public/components.js::createErrorState`, `public/components.js::createLoadingState`, `public/components.js::markValueMissing`, `public/analysis.js::requestAnalysisReport`, `public/analysis.js::renderRecoveryCharts`, `public/performance-view.js::renderPerformance`, `public/activity-analysis.js::renderPanel`, `public/activity-details.js::render`; `e2e/contracts.spec.js::planned agenda prioritizes dates and sessions with compact weather and expandable details`, `e2e/calendar-week-compact.spec.js::@responsive compact calendar week shows one week, groups repeats and keeps one conflict style`, `e2e/calendar-week-compact.spec.js::@responsive the Monat switch shows the month grid and the calendar returns to the week`, `e2e/analysis-info.spec.js::@responsive latest measurement stays visible without inventing measurements in empty weeks`, `e2e/analysis-info.spec.js::@responsive recovery uses independent scales, honest coverage over exactly fourteen days`, `e2e/activity-details.spec.js::@responsive analysis lists sessions whose details failed to load`, `e2e/activity-details.spec.js::@responsive calendar details show running step frequency and cycling cadence`, `e2e/training-feature-panels.spec.js::@responsive equipment keeps local authority and groups archived sources`, `e2e/data-states.spec.js::@responsive an empty install shows one empty card with one action per analysis tab`, `e2e/data-states.spec.js::@responsive a failed analysis read shows an error with retry instead of a permanent loading line`, `e2e/data-states.spec.js::@responsive a hanging analysis read times out into the retry state`, `e2e/data-states.spec.js::@responsive a failed equipment read offers a retry`, `e2e/activity-details.spec.js::@responsive calendar details chart running dynamics per second and retry a failed read`, `e2e/activity-details.spec.js::@responsive calendar details expand Garmin-style charts`, `e2e/analysis-info.spec.js::@responsive steps and floors show per-day units, whole numbers and the plotted basis`, `tests/analysis-presentation.test.cjs`, `tests/plan-views-sport-label.test.cjs`, `e2e/planned-sync-button.spec.js::@responsive a week with pending units offers one sync button that queues their pushes`, `e2e/strength-garmin-blocked.spec.js::@responsive a strength unit says why it does not reach Garmin and offers the fix`, `e2e/library-wahoo-state.spec.js::@responsive a changed Wahoo library workout offers the explicit send`. Source sections and these browser scenarios were inspected; this requirement does not independently re-specify backend calculations.

## ADDED Requirements

### Requirement: Calendar cards carry the single-session analysis
The calendar card of a completed session SHALL carry its single-session analysis behind a "Details" toggle, with "Mit dem Coach analysieren" and "Feedback" beside it. The Analyse tab SHALL have no separate list of sessions, the calendar SHALL page back without limit so every stored session stays reachable, and the Coach SHALL NOT receive per-second running dynamics.

#### Scenario: Details in the card
- **WHEN** the athlete opens "Details" of a completed session
- **THEN** its charts, zones, laps, values, form drift and provider notes appear in the card; a failed or timed-out read shows the retry card; an opened Details stays open and reloads when the calendar is rebuilt by a sync or reload.

#### Scenario: Running dynamics per second
- **WHEN** a run has stored running dynamics streams
- **THEN** each available one is charted per second with the same name as its average in the value list and named in the data coverage, and the Coach's activity details carry only the averages.

#### Scenario: Feedback and Coach actions
- **WHEN** the athlete taps "Feedback" or "Mit dem Coach analysieren" on an opened completed session
- **THEN** "Feedback" opens the dialog with the session type, session RPE, deviation reason, notes and the confirm, split and delete actions, and the Coach button starts one turn that names the session by date, sport, time, duration and id, never by its stored name.

#### Scenario: No sessions segment in Analyse
- **WHEN** the athlete opens the Analyse tab or an old `#analysis/sessions` link
- **THEN** Analyse shows Belastung, Leistung and Erholung only, and the old link opens the calendar overview instead.

#### Scenario: Paging back without limit
- **WHEN** the athlete pages back to a week before the configured weeks back and before the loaded sessions
- **THEN** the calendar loads the older completed sessions page by page from the session list, newest first, adds only sessions older than the loaded ones, and shows them with Details and Feedback like any other session.

Evidence: `public/plan-views.js::plannedActivityActions`, `public/plan-views.js::loadOlderSessions`, `public/activity-analysis.js::loadPanel`, `public/navigation.js::routeFromHash`, `backend/activities/detail_contract.py:activity_detail_contract`, `backend/coach/activity_read_tools.py:CoachActivityReadToolService`; `e2e/activity-details.spec.js::@responsive calendar details expand Garmin-style charts`, `e2e/activity-details.spec.js::@responsive calendar details chart running dynamics per second and retry a failed read`, `e2e/activity-details.spec.js::@responsive the calendar details open a Garmin-only indoor session; old Einheiten links land on the calendar`, `e2e/activity-details.spec.js::@responsive the calendar pages back past the loaded weeks and loads older sessions`, `e2e/ux-polish.spec.js::a session's calendar details keep a flat series as a line on a real axis @responsive`, `tests/test_activity_detail_contract.py:StreamTests.test_streams_are_downsampled_with_aligned_equal_length_channels`, `tests/test_coach_activity_read_tools.py:test_activity_detail_exposes_the_session_bundle_for_corrections`.
