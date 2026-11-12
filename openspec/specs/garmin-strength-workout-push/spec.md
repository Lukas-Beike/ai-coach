# garmin-strength-workout-push Specification

## Purpose
Send planned strength units to the athlete's Garmin watch as structured strength workouts, only on explicit athlete action and without blank exercise steps.

## Requirements

### Requirement: Garmin exercise resolution
Each strength exercise SHALL resolve to one Garmin catalogue exercise before export: its explicit `garmin_exercise` name or stored pair first, then a catalogue name the athlete confirmed for the same exercise name in another active unit or template, then the exercise name, then a fixed German/English alias list. An explicit unknown name SHALL be rejected on save with `invalid_strength_structure` and catalogue suggestions; a valid one SHALL be stored with its category/exercise pair.

#### Scenario: Explicit catalogue name
- **WHEN** a strength unit is saved with `garmin_exercise` "barbell back squat"
- **THEN** the stored exercise carries `garmin_exercise` "Barbell Back Squat" and the pair SQUAT/BARBELL_BACK_SQUAT, always derived from the catalogue on write and never taken from the request; a remote reconcile drops only a stored mapping the catalogue no longer knows and keeps the structure.

#### Scenario: Catalogue rename of a stored exercise
- **WHEN** a later catalogue no longer knows the stored `garmin_exercise` name of a saved unit
- **THEN** the stored name stays valid with its stored pair, so the unit stays pushable instead of `no_structure`; a request that sends an unknown name is still rejected.

#### Scenario: Confirmed once, remembered
- **WHEN** the athlete picks a catalogue exercise for one unit's exercise through the calendar or the Coach
- **THEN** the same exercise name in other active units and templates resolves to it without asking again; the newest confirmation wins and deleted or archived units do not count.

#### Scenario: Unmatched exercise
- **WHEN** an exercise matches neither field, name nor alias at export
- **THEN** that unit is not uploaded and its result names the exercise with up to five catalogue suggestions.

Detailed contract (matching): names are compared after Unicode decomposition, case folding, removal of accents and collapsing of spaces. After the exact catalogue name, the exercise name is matched in three loose steps: ignoring spaces, hyphens and a plural "s" of words longer than three letters; through the fixed alias list; as the single catalogue entry that contains every word of the name with the fewest words ("Pull Face" finds "Face Pull", "Row" stays open). Suggestions are up to five catalogue names containing a word of the text over two letters, the longest word first.

Evidence: `backend/providers/garmin_strength_workout.py:resolve_exercise`, `backend/providers/garmin_strength_workout.py:_loose_match`, `backend/providers/garmin_strength_workout.py:suggestions`, `tests/test_garmin_strength_push.py:test_word_fallback_needs_one_closest_entry`, `tests/test_garmin_strength_push.py:test_every_alias_names_a_catalogue_exercise`, `backend/planning/exercise_mappings.py:remembered_exercises`, `backend/planning/strength_structure.py`; `tests/test_garmin_strength_push.py` (MappingTests, StructureTests), `tests/test_planning_push_state.py:test_a_confirmed_exercise_is_remembered_for_other_units`.

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

#### Scenario: Whole job refused
- **WHEN** the job asks for `repair`, Garmin is not configured, the Garmin sync lock is not free within 30 seconds, or no SDK login is available (fixture mode, or the Personal API key only)
- **THEN** the job fails with 400 `invalid_job_request`, 409 `not_configured`, 409 `garmin_busy` or 409 `garmin_sdk_required` ("Garmin-Workouts brauchen die Garmin-Anmeldung (SDK); die Personal API kann nicht schreiben."), and `garmin_sdk_required` is never retried automatically.

#### Scenario: Run stopped
- **WHEN** an entry stopped the run
- **THEN** every later entry fails with "Nicht gesendet: Der Lauf wurde nach einem Garmin-Fehler beendet."

Detailed contract (result): the job result is `{ok, status, results, failed_object_ids, retry_scope}` with `status` `ok`, `partial` (some entries failed) or `error` (all failed). Each result has the `library_workout_id` and a `status`: `synced` (with `remote_id` and `date`, or `action: "removed"`), `already_synced` (a removal with no link left), `conflict` ("Einheit nicht gefunden", "Seit der Vorschau geändert") or `error` with a fixed message. A link stores the workout id as remote id and the schedule id as external id.

Detailed contract (document): `workoutName` has at most 80 characters (default "Krafteinheit") and `description` at most 1000; the sport is strength training (type id 5) in one segment. Each exercise is a repeat group (iterations = sets) with one step of end condition `reps`, the catalogue `category` and `exerciseName`, and a `rest` step of end condition `time` when a rest is set; a warm-up group of step type `warmup` precedes it when warm-up sets exist. `weightValue` is sent only above 0 kg with the unit `{unitId: 8, unitKey: "kilogram", factor: 1000.0}`; the step note is "<n> % 1RM", "RPE <n>" or "<n> RIR" plus the exercise note, at most 100 characters. The document version (2) is part of the pushed fingerprint, the SHA-256 of name, date, normalized exercises and that version.

Evidence: `backend/sync/garmin_strength_push.py`, `backend/sync/jobs.py`, `backend/sync/executor.py:GarminJobAdapter`, `backend/providers/garmin_strength_workout.py:strength_workout`, `backend/providers/garmin_strength_workout.py:PAYLOAD_VERSION`, `backend/planning/push_state.py:garmin_fingerprint`, `backend/sync/refresh.py:sync_job_error_class`; `tests/test_garmin_strength_push.py` (PushTests, JobValidationTests), `tests/test_garmin_payload_version_guard.py:test_document_changes_come_with_a_payload_version_bump`, `tests/test_sync_job_outcomes.py:test_a_garmin_sdk_requirement_is_final_and_never_requeued`.

### Requirement: Calendar sync button
Each calendar week SHALL show one sync button, "Woche synchronisieren", while a future, not yet completed unit of that week still needs a push to a configured provider, or a leftover of that week waits for removal. Intervals.icu waits when the unit's state is local or sync_error, or its event has another category than it gets now. Garmin waits when a strength unit with a valid structure differs from the pushed one. Planned unit cards SHALL carry no sync button.

#### Scenario: Pending structured strength unit
- **WHEN** a future strength unit with a structure is neither synced to Intervals.icu nor pushed to Garmin in its current version
- **THEN** its week shows "Woche synchronisieren", and a click queues the week's Garmin and Intervals.icu `plan_push` jobs, Intervals.icu last, each entry with its current payload hash and at most 28 entries per job.

#### Scenario: Intervals.icu receives a note
- **WHEN** a strength unit is pushed to Intervals.icu
- **THEN** it is sent as a NOTE calendar event with the generated exercise text and read back as a note, because Intervals.icu forwards WORKOUT events to Garmin as one unnamed step; the structured workout reaches the watch only by the Garmin push.

#### Scenario: Garmin blocked
- **WHEN** a future strength unit has no valid structure, or an exercise has no Garmin match
- **THEN** no Garmin push is offered and the card says why; an unmatched exercise lists up to five catalogue suggestions that save the choice for the unit, and the Coach can structure or map it.

#### Scenario: Nothing pending
- **WHEN** every unit of a week is synced everywhere, in a sync conflict, in the past, already matched to a recorded activity, or waits only for a provider that is not configured, and no leftover belongs to the week
- **THEN** the week shows no sync button.

#### Scenario: Leftovers without a pending unit
- **WHEN** a provider has leftovers and no visible upcoming unit waits for that provider
- **THEN** the visible unit nearest to today carries them, so the calendar can always offer the removal; a deleted or archived unit never carries them.

Detailed contract: each listed planned unit carries `payload_hash` (the hash the `plan_push` job checks), `push_pending` (per provider; Intervals.icu: state local, sync_error or remote_missing, another event category, or an exported heart-rate range that moved with the threshold; Garmin: present only for a pushable strength unit, true when the pushed fingerprint differs), `push_blocked` (`{garmin: "no_structure" | "unmapped"}` or empty), `push_unmapped` (per unmapped exercise its `index`, `name` and up to five `suggestions`) and `push_cleanup` (per provider the leftovers its sync removes: `id`, `name`, `date`, and for Intervals.icu the `hash`).

Evidence: `backend/planning/push_state.py`, `backend/planning/push_state.py:attach_push_state`, `backend/planning/push_state.py:_carry_unclaimed_cleanup`, `backend/planning/planned_unit_service.py:PlannedUnitService.list`, `backend/http_api/planned_unit_focus_post.py`, `public/plan-views.js:plannedPushTargets`, `public/plan-views.js:plannedWeekSyncJobs`, `public/plan-views.js:plannedWeekSyncButton`, `public/plan-views.js:plannedGarminBlocked`; `tests/test_planning_push_state.py`, `tests/test_planning_push_state.py:test_leftovers_ride_on_a_unit_even_when_no_provider_waits`, `tests/test_planning_push_state.py:test_a_deleted_unit_nearest_today_never_carries_the_leftovers`, `tests/plan-views-sync-button.test.cjs`, `tests/test_workout_export_intervals.py:test_strength_is_sent_and_read_back_as_a_note`, `e2e/calendar-week-sync.spec.js`, `e2e/planned-sync-button.spec.js`.

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

#### Scenario: Entry rejected by Garmin
- **WHEN** Garmin answers 4xx other than 401, 408 and 429 for one entry
- **THEN** only that entry fails with "Garmin hat das Workout abgelehnt (HTTP <status>)." and the next entries are still sent.

#### Scenario: Garmin outage
- **WHEN** Garmin answers a server error, throttling or authentication failure
- **THEN** that unit fails with a fixed message and the remaining units are not attempted.

Evidence: `backend/sync/garmin_strength_push.py`, `backend/sync/jobs.py:_normalize_plan_push_entry`; `tests/test_garmin_strength_push.py`, `tests/test_sync_jobs.py:test_plan_push_normalizes_entries_reason_and_repair`.

### Requirement: Garmin leftovers are removed by the explicit sync
A link of provider `garmin` whose planned unit is missing, tombstoned, archived, deleted, no longer a strength unit, or no longer pushable SHALL count as an orphan. The explicit Garmin job SHALL carry up to 20 orphans as `remove` entries, the week sync button and Coach cards SHALL remove or list them ("Wird bei Garmin entfernt"); nothing else SHALL be removed outside an explicit sync, and a Garmin workout without a link SHALL never be touched.

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

Detailed contract: an orphan belongs to the week button of its day; an undated or earlier one to the current week, a later one beyond the shown weeks to the last shown week. The week sends its leftovers in jobs of their own, so a leftover that cannot be removed never fails a unit.

Evidence: `backend/planning/garmin_orphans.py`, `backend/planning/push_state.py:attach_push_state`, `backend/coach/proposal_creation.py:_approved_garmin_arguments`, `backend/db/remote_links.py:RemoteLinkRepository.delete_for_entity`, `public/plan-views.js:plannedLeftoversByWeek`; `tests/test_garmin_strength_push.py` (PushTests orphan tests, `test_a_linked_unit_that_became_unpushable_is_an_orphan`, `test_a_unit_with_an_unreadable_payload_is_no_orphan`), `tests/plan-views-sync-button.test.cjs`, `tests/test_sync_jobs.py:test_one_stored_item_keeps_a_failure_among_several_results`.

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
- **THEN** its link stays for the next refresh and the other past workouts are still removed; one refresh makes at most 40 removal attempts.

#### Scenario: One-time removal of the app's unlinked old workouts
- **WHEN** a Garmin refresh finishes and the one-time removal (athlete decision 2026-11-12, #2373) has not finished yet
- **THEN** the strength workouts of the Garmin library whose description starts with the app's marker line "Pacecraft", that no stored unit dated today or later links and that no day from today through 90 days ahead schedules are deleted, together with any link to them; workouts without the marker (the athlete's own and Intervals.icu copies), other sports, upcoming and scheduled ones stay. It reads at most 40 workouts and removes at most 20 per refresh, remembers the ids read as not the app's and those Garmin refused to delete, keeps that progress through a Garmin outage, and once a pass reaches the end of the list it never runs again.

#### Scenario: Every run is visible
- **WHEN** a Garmin refresh finishes
- **THEN** a removal run logs `garmin_past_workouts_removed` with its count, zero included, or `garmin_past_workout_removal_failed`, and stores its time, its outcome, the running total of removals and the past linked workouts it left; a refresh whose SDK login was skipped logs `garmin_past_workout_removal_skipped`, stores the outcome `skipped` and makes no Garmin call; the diagnostics section `garmin_past_workout_removal` reports only these counts, the outcome and the last run time (#2408).

Evidence: `backend/sync/garmin_strength_push.py:GarminStrengthPushService.remove_past`, `backend/sync/garmin_strength_push.py:GarminStrengthPushService._remove_unlinked`, `backend/sync/executor.py:GarminJobAdapter`, `backend/diagnostics/plan_sync.py:summarize_garmin_removal`; `tests/test_garmin_strength_push.py:PastWorkoutRemovalTests`, `tests/test_diagnostic_plan_sync.py:GarminRemovalDiagnosticsTests`.
