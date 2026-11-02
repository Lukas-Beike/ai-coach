## ADDED Requirements

### Requirement: Calendar plan notes
Coach plan writes SHALL report a non-blocking note for a long or hard unit on a heavily occupied day or overlapping an external event. Explicit calendar markers retain their existing enforcement.

#### Scenario: Calendar conflict
- **WHEN** a Coach plan write introduces a qualifying calendar conflict
- **THEN** the receipt includes a non-blocking note with safe evidence.

Evidence: `backend/planning/plan_checks.py:check_plan`, `backend/coach/change_receipts.py:change_summary`, `public/coach.js:appendPlanNotes`; `tests/test_plan_guard_service.py:test_calendar_conflict_is_saved_as_note`, `tests/coach-turn-undo.test.cjs`, `e2e/coach-plan-notes.spec.js`.
