## MODIFIED Requirements

### Requirement: CP5 Saved provider evidence and honest freshness
The system SHALL build ordinary Coach context from saved provider observations and local planning, retain available source/sync metadata, and read cached weather without causing an unconditional provider refresh. The `activities` section SHALL report its sync time (`synced_at` and `source.synced_at`) from the Intervals.icu activity fetch time of the canonical provider coverage, read in the same read snapshot as the activity rows, and SHALL report null when no coverage is stored.

#### Scenario: Ordinary context read
- **WHEN** the athlete sends an ordinary Coach message
- **THEN** context assembly reads saved data and weather with refresh disabled rather than issuing provider calls for every message.

#### Scenario: Missing Intervals snapshot
- **WHEN** the saved Intervals snapshot is empty
- **THEN** the context permits the implemented Garmin performance fallback while keeping provider recovery separate and unavailable evidence explicit.

#### Scenario: Local calendar planning
- **WHEN** context combines planned units, competitions and external calendar entries
- **THEN** calendar items identify their local-plan, competition or external-calendar origin; external calendar context is read-only.

#### Scenario: Activities freshness from canonical coverage
- **WHEN** the context includes the activities section and canonical coverage stores an Intervals.icu activity fetch time
- **THEN** the section's `synced_at` and `source.synced_at` equal that time regardless of the stored snapshot's `synced_at` or of a duplicate deletion, and are null when no coverage is stored.

Evidence: `backend/coach/context.py:CoachStructuredContextService.build`, `backend/coach/context.py:CoachPlanningContextReader.calendar`, `backend/coach/context.py:CoachPlanningContextReader.external_calendar`, `backend/coach/context.py:CoachPerformanceContextReader.current_performance`, `backend/coach/context.py:CoachIntervalsContextService.project`; `tests/test_coach_structured_context.py:test_build_uses_snapshot_fallback_and_projects_safe_provider_context`, `tests/test_coach_structured_context.py:test_explicit_snapshot_is_used_without_fallback_and_empty_snapshot_enables_garmin_fallback`. Per-metric provenance is owned by performance/provider capabilities; this requirement does not assert that every legacy section label identifies every canonical provider correctly. Missing evidence (planned in this change): activities section `synced_at` from coverage and null without coverage.
