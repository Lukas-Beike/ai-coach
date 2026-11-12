## ADDED Requirements

### Requirement: Planned units come from library templates
A planned unit that a Coach plan tool creates or whose structure it changes SHALL reference an undated training-library template by `template_id` and keep that template's structure for every sport: the strength exercises in order, the endurance steps in order. A variant SHALL differ from its template only in load and intensity. A Coach write that breaks this SHALL be rolled back with a required plan-check finding the model can act on.

#### Scenario: Unit from a template
- **WHEN** the Coach plans a unit with the `template_id` of an existing undated library template and the template's exercises or steps in the same order
- **THEN** the unit is saved with its `template_id`; strength and endurance exports (Garmin, Intervals.icu, Wahoo) use the unit's stored structure, which is the template's.

#### Scenario: Ad-hoc unit
- **WHEN** a Coach plan write creates a unit without `template_id`, or with an id that names no undated library template
- **THEN** the write is rolled back with a `template_missing` finding that tells the model to plan from `list_workout_library`, or to propose a new template to the athlete and create it with `manage_training_templates` before planning; no unit is created without a template.

#### Scenario: Scaled variant
- **WHEN** a unit keeps its template's exercises or steps in order and changes only sets, reps, kg, %1RM, RPE, RIR, rest, warm-up, step durations or targets, or the unit duration
- **THEN** the write is saved and the receipt carries a `template_scaled` note naming the unit and its template.

#### Scenario: Different structure
- **WHEN** a unit adds, drops, swaps or reorders an exercise or a step against its template
- **THEN** the write is rolled back with a `template_mismatch` finding; a different selection of exercises is a separate library template.

#### Scenario: Existing unit without a template
- **WHEN** a Coach write moves an older unit that has no `template_id`, sets its session focus or Garmin exercise, archives or deletes it
- **THEN** it passes; a change of its exercises, steps or loads is rolled back with `template_missing` until the unit is switched to a library template. Older units are never cleaned up automatically.

#### Scenario: Adaptive replacement
- **WHEN** an approved adaptive replan eases a planned unit
- **THEN** a run or ride may become the generic easy replacement (marked `source: adaptive`, exempt from the template check); a strength unit only gets the light strength intensity, its exercises, sets and weights stay unchanged.

#### Scenario: Template label
- **WHEN** the athlete expands a planned unit with a `template_id`
- **THEN** one line "Vorlage: <template name>" appears under its title; the calendar tile is unchanged.

Evidence: `backend/planning/plan_checks.py:template_conformance`, `backend/planning/plan_guard_service.py:PlanGuardService.findings`, `backend/planning/library_plan_service.py`, `backend/planning/adaptive.py:adaptive_recovery_replacement`, `public/plan-views.js`; `tests/test_plan_checks.py`, `tests/test_plan_guard_service.py`, `tests/test_coach_tool_coverage.py`, `tests/test_adaptive_replan_apply_service.py`.
