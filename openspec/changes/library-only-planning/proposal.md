## Why

In production the Coach planned strength units whose exercise lists did not come from the athlete's training library (a "short" upper-body unit with 3 of the template's 7 exercises, a "moderate" variant that swapped an exercise), and they were pushed to Garmin that way (#2379). Athlete decision 2026-11-12: planned units come only from the training library, for every sport; variants only scale load and intensity.

## What Changes

- A planned unit written by a Coach plan tool carries `template_id`, the local id of an undated library template, and keeps the template's structure: the strength exercises in order, the endurance steps in order. Only load and intensity scale (sets, reps, kg, %1RM, RPE, RIR, rest, warm-up, step durations and targets, the unit duration).
- Two new required plan-check findings, `template_missing` and `template_mismatch`, roll back a Coach plan write that creates a unit without a template or changes a unit's structure away from its template; like `strength_incomplete` they can never be accepted, and an untouched older unit never blocks a write. A scaled unit adds a `template_scaled` note to the receipt.
- No fitting template: the Coach proposes and creates a library template first (`manage_training_templates`), then plans from it. Plan creation no longer stores free Coach content when no template matches (TP3).
- Existing units without a template (athlete decision): moving, session focus, Garmin exercise, archive and delete still work; a content change needs a template.
- Adaptive replanning (athlete decision): a run or ride may still become the generic easy replacement; a strength unit only gets the light strength intensity, its exercises, sets and weights stay.
- The expanded planned unit shows "Vorlage: <name>"; the calendar tile is unchanged. Exports keep using the unit's stored structure, which now follows its template.
- Coach prompt, playbooks and tool descriptions plan from the library.

## Capabilities

### New Capabilities

### Modified Capabilities
- `training-library`: new requirement for library-only planned units.
- `training-plans-and-adaptation`: TP3 template matching without a free-content fallback.
- `coach-tool-authority`: CA11 lists the new required findings and the note.

## Impact

`backend/planning/plan_checks.py`, `backend/planning/plan_guard_service.py` (template provider), the planning normalizers (`template_id` field, excluded from the push payload hash), `backend/planning/library_plan_service.py`, `backend/planning/local_plan_creation_service.py`, `backend/planning/adaptive.py`, Coach prompt, playbooks and tool schemas, `public/plan-views.js` (label). No schema migration: `template_id` lives in the payload JSON. Exclusions: no automatic cleanup of existing units; explicit athlete UI/API edits stay unchecked (CA11).
