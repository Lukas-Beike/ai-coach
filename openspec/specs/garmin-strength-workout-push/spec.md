# garmin-strength-workout-push Specification

## Purpose
Send planned strength units to the athlete's Garmin watch as structured strength workouts, only on explicit athlete action and without blank exercise steps.

## Requirements

### Requirement: Garmin exercise resolution
Each strength exercise SHALL resolve to one Garmin catalogue exercise before export: its explicit `garmin_exercise` name or stored pair first, then a catalogue name the athlete confirmed for the same exercise name in another active unit or template, then the exercise name, then a fixed German/English alias list. An explicit unknown name SHALL be rejected on save with `invalid_strength_structure` and catalogue suggestions; a valid one SHALL be stored with its category/exercise pair.

#### Scenario: Explicit catalogue name
- **WHEN** a strength unit is saved with `garmin_exercise` "barbell back squat"
- **THEN** the stored exercise carries `garmin_exercise` "Barbell Back Squat" and the pair SQUAT/BARBELL_BACK_SQUAT, always derived from the catalogue on write and never taken from the request; a remote reconcile drops only a stored mapping the catalogue no longer knows and keeps the structure.

#### Scenario: Confirmed once, remembered
- **WHEN** the athlete picks a catalogue exercise for one unit's exercise through the calendar or the Coach
- **THEN** the same exercise name in other active units and templates resolves to it without asking again; the newest confirmation wins and deleted or archived units do not count.

#### Scenario: Unmatched exercise
- **WHEN** an exercise matches neither field, name nor alias at export
- **THEN** that unit is not uploaded and its result names the exercise with up to five catalogue suggestions.

Evidence: `backend/providers/garmin_strength_workout.py:resolve_exercise`, `backend/planning/exercise_mappings.py:remembered_exercises`, `backend/planning/strength_structure.py`; `tests/test_garmin_strength_push.py` (MappingTests, StructureTests), `tests/test_planning_push_state.py:test_a_confirmed_exercise_is_remembered_for_other_units`.

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
- **WHEN** the Coach proposes the push after the athlete named Garmin or the watch
- **THEN** the same job is queued only after the athlete approves the card, with the payload hashes stored when the card was created (see coach-tool-authority CA5).

#### Scenario: Rejected locally
- **WHEN** a unit is stale, deleted, archived, in the past, not strength or has no structure
- **THEN** it is reported as conflict or error and no Garmin login or write happens for it.

Evidence: `backend/sync/garmin_strength_push.py`, `backend/sync/jobs.py`, `backend/sync/executor.py:GarminJobAdapter`; `tests/test_garmin_strength_push.py` (PushTests, JobValidationTests).

### Requirement: Calendar sync button
The calendar list SHALL show one sync action on each future, not yet completed planned unit that still needs a push to a configured provider: Intervals.icu when its state is local, sync_error or remote_missing; Garmin when it is a strength unit with a valid structure whose name, date, structure or workout document version differ from the pushed ones. It SHALL send one `plan_push` job per provider, Intervals.icu last, with the current payload hash.

#### Scenario: Pending structured strength unit
- **WHEN** a future strength unit with a structure is neither synced to Intervals.icu nor pushed to Garmin in its current version
- **THEN** its opened calendar card shows "Synchronisieren", and a click queues an Intervals.icu and a Garmin `plan_push` job for it.

#### Scenario: Intervals.icu receives a note
- **WHEN** a strength unit is pushed to Intervals.icu
- **THEN** it is sent as a NOTE calendar event with the generated exercise text and read back as a note, because Intervals.icu forwards WORKOUT events to Garmin as one unnamed step; the structured workout reaches the watch only by the Garmin push.

#### Scenario: Garmin blocked
- **WHEN** a future strength unit has no valid structure, or an exercise has no Garmin match
- **THEN** no Garmin push is offered and the card says why; an unmatched exercise lists up to five catalogue suggestions that save the choice for the unit, and the Coach can structure or map it.

#### Scenario: Nothing pending
- **WHEN** a unit is synced everywhere, in a sync conflict, in the past, already matched to a recorded activity, or its only pending provider is not configured
- **THEN** no sync action is shown.

Evidence: `backend/planning/push_state.py`, `backend/planning/planned_unit_service.py:PlannedUnitService.list`, `backend/http_api/planned_unit_focus_post.py`, `public/plan-views.js:plannedPushTargets`, `public/plan-views.js:plannedGarminBlocked`; `tests/test_planning_push_state.py`, `tests/plan-views-sync-button.test.cjs`, `tests/test_workout_export_intervals.py:test_strength_is_sent_and_read_back_as_a_note`.

### Requirement: Safe Garmin write outcomes
A saved workout whose exercise steps differ from the sent ones SHALL be deleted when just created, or unscheduled when updated, and reported. Apart from the removal of past workouts after a refresh, removal SHALL happen only for a `remove` entry, which the job contract accepts for Garmin and Wahoo and refuses for Intervals.icu, and SHALL delete only the linked workout and schedule. A non-client remote failure SHALL stop the remaining units; messages SHALL never contain Garmin's response text.

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

Evidence: `backend/sync/garmin_strength_push.py`, `backend/sync/jobs.py:_normalize_plan_push_entry`; `tests/test_garmin_strength_push.py`, `tests/test_sync_jobs.py:test_plan_push_normalizes_entries_reason_and_repair`.

### Requirement: Garmin leftovers are removed by the explicit sync
A link of provider `garmin` whose planned unit is missing, tombstoned, archived, deleted, no longer a strength unit, or no longer pushable SHALL count as an orphan. The explicit Garmin job SHALL carry up to 20 orphans as `remove` entries and calendar and Coach cards SHALL list them ("Wird bei Garmin entfernt"); nothing else SHALL be removed outside an explicit sync, and a Garmin workout without a link SHALL never be touched.

#### Scenario: Unpushable or unreadable unit
- **WHEN** a linked strength unit has no valid structure or an exercise without a Garmin match, or its stored payload cannot be read
- **THEN** the first is an orphan, because it can no longer replace its pushed workout; the second is not, because a damaged unit is not a deleted one.

#### Scenario: Kept link and marker
- **WHEN** the creation of a unit is undone, or a workout is sent
- **THEN** the unit's Garmin link stays so the workout remains removable, and the workout description starts with "Pacecraft".

#### Scenario: Replaced unit
- **WHEN** a unit was replaced by a new unit and the new unit is synced to Garmin
- **THEN** the job also unschedules and deletes the old unit's linked workout, drops its link and schedules the new workout once.

#### Scenario: Failed removal
- **WHEN** Garmin refuses an orphan's removal
- **THEN** the job reports the failure, the link stays and the next sync lists the orphan again.

#### Scenario: Foreign workout
- **WHEN** the Garmin calendar holds a workout this app did not send
- **THEN** no orphan removal reads, changes or deletes it.

Detailed contract: the calendar lists the orphans once, on the first card offering the Garmin sync.

Evidence: `backend/planning/garmin_orphans.py`, `backend/planning/push_state.py:attach_push_state`, `backend/coach/proposal_creation.py:_approved_garmin_arguments`, `backend/db/remote_links.py:RemoteLinkRepository.delete_for_entity`, `public/plan-views.js:plannedCleanup`; `tests/test_garmin_strength_push.py` (PushTests orphan tests, `test_a_linked_unit_that_became_unpushable_is_an_orphan`, `test_a_unit_with_an_unreadable_payload_is_no_orphan`), `tests/plan-views-sync-button.test.cjs`, `tests/test_sync_jobs.py:test_one_stored_item_keeps_a_failure_among_several_results`.

### Requirement: Past Garmin workouts are removed after a refresh
After each Garmin `refresh` job, the system SHALL unschedule and delete the linked workout of every planned unit dated before the athlete's local today and drop its link, at most 20 per refresh, oldest day first. This is the one Garmin write without an athlete request (athlete decision 2026-11-11). It SHALL touch only linked ids, never a recorded activity or an unlinked workout, SHALL try no SDK login the latest refresh could not make, and SHALL never change the refresh result.

#### Scenario: Day passed
- **WHEN** a Garmin refresh finishes and a linked strength unit's day lies before today
- **THEN** its workout is unscheduled and deleted at Garmin and its link is dropped, while today's linked workout stays.

#### Scenario: Garmin failure
- **WHEN** Garmin answers the removal with a server error, or the Garmin login is busy
- **THEN** the refresh is unaffected, a server error stops the run, and every link stays for the next refresh.

#### Scenario: Refused workout
- **WHEN** Garmin refuses one workout's deletion with a client error
- **THEN** its link stays for the next refresh and the other past workouts are still removed.

Evidence: `backend/sync/garmin_strength_push.py:GarminStrengthPushService.remove_past`, `backend/sync/executor.py:GarminJobAdapter`; `tests/test_garmin_strength_push.py:PastWorkoutRemovalTests`.
