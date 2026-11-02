## ADDED Requirements

### Requirement: Planning calendar horizon
The system SHALL provide planning turns a compact projection of all external events overlapping the planning horizon and count events omitted by the context budget. Event descriptions SHALL not enter this projection, and external event text remains untrusted.

#### Scenario: Planning and ordinary chat
- **WHEN** a week or block planning turn is built
- **THEN** events overlapping 14 or 35 days respectively are considered without a row cap, including events without descriptions; ordinary chat retains its relevance filter.

#### Scenario: Context budget
- **WHEN** events exceed the section budget
- **THEN** the projection states the number omitted.

Evidence: `backend/coach/context.py:CoachPlanningContextReader.external_calendar`; `tests/test_calendar_planning.py:test_horizon_projection_and_budget`; `tests/test_coach_structured_context.py:test_plan_kinds_use_full_calendar_horizons`; `tests/test_coach_context_reduction.py:test_total_budget_reports_omitted_calendar_event_count`.

### Requirement: Calendar busy time in planning brief
The planning brief SHALL summarize daily busy minutes from external events without double-counting overlaps.

#### Scenario: Overlapping events
- **WHEN** two events overlap on a planning day
- **THEN** only their union contributes to that day's busy minutes.

Evidence: `backend/planning/calendar_load.py:busy_minutes`, `backend/planning/plan_guard_service.py:PlanGuardService.brief`; `tests/test_calendar_planning.py:test_busy_minutes_union_and_midnight`.
