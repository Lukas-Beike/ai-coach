## MODIFIED Requirements

### Requirement: Explicit Garmin strength push
A strength planned unit SHALL reach Garmin only through an explicit `plan_push` job for provider `garmin` with the preview payload hash. Each unit SHALL be validated and mapped locally before any remote call, become one strength workout (a repeat group per exercise, a warm-up group before it when the exercise has warm-up sets, weight sent in kilograms, relative load as note, timed rest) and be scheduled on its date. Ids SHALL be stored in `remote_links`.

#### Scenario: First push
- **WHEN** a future, active strength unit with a resolvable structure is pushed
- **THEN** the workout is uploaded, read back, scheduled on the unit's date, and the workout and schedule ids are linked to the unit.

#### Scenario: Repeated push
- **WHEN** a linked unit is pushed again after a change or move
- **THEN** the same Garmin workout is updated, its own schedule is replaced by one on the current date, and a workout missing at Garmin is uploaded again after its old schedule and workout are unscheduled and deleted.

#### Scenario: Weight unit
- **WHEN** a set with 40 kg is exported
- **THEN** the step carries `weightValue` 40.0 with the kilogram unit, and units sent in an earlier form show as changed so the athlete can send them again.

#### Scenario: Coach request
- **WHEN** the Coach sends units after the athlete named Garmin or the watch
- **THEN** the same job is queued without a card, with the payload hashes stored when the request ran; a call that explicitly removes a workout is queued only after the athlete approves its card (see coach-tool-authority CA5).

#### Scenario: Rejected locally
- **WHEN** a unit is stale, deleted, archived, in the past, not strength or has no structure
- **THEN** it is reported as conflict or error and no Garmin login or write happens for it.

Evidence: `backend/sync/garmin_strength_push.py`, `backend/sync/jobs.py`, `backend/sync/executor.py:GarminJobAdapter`; `tests/test_garmin_strength_push.py` (PushTests, JobValidationTests).
