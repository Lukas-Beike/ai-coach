# garmin-strength-workout-push Specification

## Purpose
Send planned strength units to the athlete's Garmin watch as structured strength workouts, only on explicit athlete action and without blank exercise steps.

## Requirements

### Requirement: Garmin exercise resolution
Each strength exercise SHALL resolve to one Garmin catalogue exercise before export: an explicit `garmin_exercise` catalogue name first, then the exercise name, then a fixed German/English alias list. An explicit unknown name SHALL be rejected on save with `invalid_strength_structure` and catalogue suggestions; a valid one SHALL be stored with its category/exercise pair.

#### Scenario: Explicit catalogue name
- **WHEN** a strength unit is saved with `garmin_exercise` "barbell back squat"
- **THEN** the stored exercise carries `garmin_exercise` "Barbell Back Squat" and the pair SQUAT/BARBELL_BACK_SQUAT, always derived from the catalogue on write and never taken from the request; a remote reconcile drops only a stored mapping the catalogue no longer knows and keeps the structure.

#### Scenario: Unmatched exercise
- **WHEN** an exercise matches neither field, name nor alias at export
- **THEN** that unit is not uploaded and its result names the exercise with up to five catalogue suggestions.

Evidence: `backend/providers/garmin_strength_workout.py`, `backend/planning/strength_structure.py`; `tests/test_garmin_strength_push.py` (MappingTests, StructureTests).

### Requirement: Explicit Garmin strength push
A strength planned unit SHALL reach Garmin only through an explicit `plan_push` job for provider `garmin` with the preview payload hash. Each unit SHALL be validated and mapped locally before any remote call, become one strength workout (a repeat group per exercise, kg as weight, relative load as note, timed rest) and be scheduled on its date. Ids SHALL be stored in `remote_links`.

#### Scenario: First push
- **WHEN** a future, active strength unit with a resolvable structure is pushed
- **THEN** the workout is uploaded, read back, scheduled on the unit's date, and the workout and schedule ids are linked to the unit.

#### Scenario: Repeated push
- **WHEN** a linked unit is pushed again after a change or move
- **THEN** the same Garmin workout is updated, its own schedule is replaced by one on the current date, and a workout missing at Garmin is uploaded again.

#### Scenario: Coach request
- **WHEN** the Coach proposes the push after the athlete named Garmin or the watch
- **THEN** the same job is queued only after the athlete approves the card, with the payload hashes stored when the card was created (see coach-tool-authority CA5).

#### Scenario: Rejected locally
- **WHEN** a unit is stale, deleted, archived, in the past, not strength or has no structure
- **THEN** it is reported as conflict or error and no Garmin login or write happens for it.

Evidence: `backend/sync/garmin_strength_push.py`, `backend/sync/jobs.py`, `backend/sync/executor.py:GarminJobAdapter`; `tests/test_garmin_strength_push.py` (PushTests, JobValidationTests).

### Requirement: Calendar sync button
The calendar list SHALL show one sync action on each future planned unit that still needs a push: to Intervals.icu when its state is local, sync_error or remote_missing, and to Garmin when it is a strength unit with a structure whose current payload hash differs from the pushed one. The action SHALL send one `plan_push` job per pending provider with the unit's current payload hash.

#### Scenario: Pending structured strength unit
- **WHEN** a future strength unit with a structure is neither synced to Intervals.icu nor pushed to Garmin in its current version
- **THEN** its calendar card shows "Synchronisieren", and a click queues an Intervals.icu and a Garmin `plan_push` job for it without opening the card.

#### Scenario: Nothing pending
- **WHEN** a unit is synced everywhere, in a sync conflict, in the past or a completed activity
- **THEN** no sync action is shown.

Evidence: `backend/planning/push_state.py`, `backend/planning/planned_unit_service.py:PlannedUnitService.list`, `public/plan-views.js:plannedPushTargets`; `tests/test_planning_push_state.py`, `tests/plan-views-sync-button.test.cjs`.

### Requirement: Safe Garmin write outcomes
A saved workout whose exercise steps differ from the sent ones SHALL be deleted when just created, or unscheduled when updated, and reported. Removal SHALL happen only for a `remove` entry, accepted for Garmin only, and SHALL delete only the linked workout and schedule. A non-client remote failure SHALL stop the remaining units; messages SHALL never contain Garmin's response text.

#### Scenario: Garmin blanks an exercise
- **WHEN** the read-back workout lacks a sent exercise name
- **THEN** the new workout is deleted, nothing is scheduled and the unit fails with a verification error.

#### Scenario: Schedule id missing
- **WHEN** Garmin confirms the schedule without an id and the calendar lookup for that workout and day finds none
- **THEN** the unit fails as unconfirmed, its link keeps no payload hash, and it is not reported as synced.

#### Scenario: Explicit removal
- **WHEN** a job entry carries `remove: true` for a linked unit
- **THEN** only its schedule and workout are deleted and the link is dropped; unrelated Garmin calendar items stay.

#### Scenario: Garmin outage
- **WHEN** Garmin answers a server error, throttling or authentication failure
- **THEN** that unit fails with a fixed message and the remaining units are not attempted.

Evidence: `backend/sync/garmin_strength_push.py`; `tests/test_garmin_strength_push.py`.
