# Spec Delta

## ADDED Requirements

### Requirement: CS9 Competition-focused overview
The system SHALL present the planning segment as `Wettkämpfe`, with individually expandable, initially collapsed upcoming events ordered by date, priority and name. Each summary SHALL show saved name, date, sport, distance, personal A/B/C priority and athlete-local relative date without requiring training history.

#### Scenario: Upcoming competitions
- **WHEN** the athlete opens the competition overview with several saved upcoming events
- **THEN** all entries start collapsed in chronological order, today's events remain upcoming, and their summary facts are visible without expansion.

#### Scenario: Missing or unsupported facts
- **WHEN** distance is missing, sport has only local free-text detail, or a record has an invalid date
- **THEN** missing distance is shown as unknown rather than zero, local sport detail is preserved, and an undated record remains accessible separately without an invented date or countdown.

### Requirement: CS10 Saved event details and historical archive
The system SHALL reveal saved optional event details only on expansion, omit empty optional fields, and group past events in an initially collapsed archive ordered newest first. Expansion SHALL remain keyboard accessible and render untrusted event text safely.

#### Scenario: Expand an event
- **WHEN** the athlete expands a competition
- **THEN** its saved start time, target, expected duration, course profile, description and notes are shown where present, and other entries retain their expansion state.

#### Scenario: Historical and empty lists
- **WHEN** only past competitions exist or no competitions exist
- **THEN** the screen respectively offers the collapsed historical archive or a concise empty state without fabricated events or preparation metrics.

#### Scenario: Untrusted content
- **WHEN** event text contains markup or provider-supplied instructions
- **THEN** it is displayed as safe content and never executed or treated as authorization.

### Requirement: CS11 Overview excludes training analysis
The competition overview SHALL exclude date-derived training phases, weekly training volume/history, preparation evidence, long-session analysis and load-scenario controls. Reading the overview SHALL remain usable without activity analyses or scenario availability.

#### Scenario: Athlete checks competition dates
- **WHEN** the competition overview is loaded or an event is expanded
- **THEN** only competition facts and existing event-workflow access are presented, without weekly charts, evidence tables, phase labels or scenario inputs.

### Requirement: CS12 Read state and competition authority
The overview SHALL preserve canonical local records, existing Coach editing and receipt/undo workflows, compact source/local-change indications and explicit synchronization authorization. Opening, expanding, archiving visually or refreshing the overview SHALL perform no durable mutation or provider write.

#### Scenario: Local changes await synchronization
- **WHEN** a local competition has unsynchronized edits
- **THEN** its current local values remain authoritative and the pending local state is visible without an automatic push.

#### Scenario: Load and refresh failure
- **WHEN** the initial read is pending or a refresh fails
- **THEN** the screen distinguishes loading from an empty list, retains available cached facts with a stale/error indication, and offers retry without claiming a successful refresh.

#### Scenario: Return after a Coach edit
- **WHEN** an authorized Coach competition edit succeeds and the overview refreshes
- **THEN** the saved updated event appears with its stable identity and existing receipt/undo behavior, without an additional remote write.

Evidence for CS9–CS12: `public/plan-views.js` renders canonical competition state supplied through `public/state-loader.js`; `public/app.js` binds local retry, and `public/shared.js` no longer requests season preparation on route entry. Bootstrap/profile reads are owned by `backend/http_api/bootstrap_state.py` and `backend/http_api/athlete_get.py`; local mutation authority remains in `backend/planning/competition_service.py`.

Validation: `tests/competition-overview.test.cjs` covers missing, zero and free-text distance and invalid dates. `e2e/competitions.spec.js` covers summaries, disclosure details, ordering, archives, safe text, failed reads/retry, empty lists and absence of analysis requests or writes on mobile-small and desktop. `e2e/text-reflow.spec.js`, `e2e/training-feature-panels.spec.js`, `tests/test_server_frontend.py` and `tests/test_server_runtime.py` cover the surrounding UI and asset contracts. Existing CS1–CS8 remain unchanged.

Evidence limits: Coach-edit refresh is exercised using simulated canonical saved state rather than an end-to-end real-model mutation. Real-device microphone/notification permissions and keyboard-open behavior were not verified. The full Python discovery run's five obsolete UI assertions were corrected and both affected suites passed on rerun; the full discovery run was not repeated after those test-only corrections.
