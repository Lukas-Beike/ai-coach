## MODIFIED Requirements

### Requirement: AP7 Exact completed-activity feedback
The system SHALL save subjective notes, optional finite session RPE from 0 through 10 and bounded deviation reasons against a resolved existing activity, preserving omitted fields and keeping feedback separate from daily/provider records. An activity exists when its local session id, or the provider activity id of an active record of any provider, leads to a live canonical session.

#### Scenario: Existing activity and partial edit
- **WHEN** the Coach or the detail view saves nonempty feedback for a live canonical session by local or provider ID, including a Garmin- or Wahoo-only session
- **THEN** it resolves the activity reference, stores local feedback, preserves omitted fields and attaches that feedback to activity reads.

#### Scenario: Empty, unknown or invalid feedback
- **WHEN** the Coach submits empty observations, an id that leads to no live canonical session, or invalid/nonfinite/out-of-range RPE
- **THEN** the save fails rather than creating a completed activity or inventing feedback.

#### Scenario: Explicit removal
- **WHEN** the authorized delete-feedback tool clears notes, RPE and deviation reason for an activity
- **THEN** the local feedback row is removed without deleting the activity or altering provider feedback.

Evidence: `backend/activities/feedback.py:normalize_activity_feedback`, `backend/activities/feedback.py:ActivityFeedbackService.save_coach`, `backend/db/canonical_store.py:live_session_id`, `backend/activities/feedback.py:ActivityFeedbackService._save`, `backend/activities/feedback.py:ActivityFeedbackService.attach_to_activities`; `backend/coach/athlete_record_tools.py:CoachAthleteRecordToolService.execute`; `tests/test_activity_feedback.py:test_rpe_only_preserves_notes_and_explicit_clear_deletes`, `tests/test_activity_feedback.py:test_coach_save_requires_a_live_canonical_session`, `tests/test_activity_feedback.py:test_attach_finds_feedback_older_than_the_newest_500_rows`; `tests/test_coach_tool_coverage.py:test_daily_feedback_and_activity_feedback_are_separate_from_profile`.

### Requirement: AP9 Explicit equipment assignments and honest usage
The system SHALL assign only resolved canonical completed activities to compatible active main equipment, allow explicit unassignment, and calculate usage from known assignments and supported Garmin links with coverage metadata. Usage, hours, distance, maintenance and sport derivation SHALL read canonical session summaries, so each session counts once whichever providers recorded it.

#### Scenario: Assign or reassign
- **WHEN** the athlete explicitly assigns an existing activity to compatible active main equipment
- **THEN** the local assignment is saved and both old and new equipment usage reflect the current assignment; unknown/component/archived/incompatible equipment is rejected.

#### Scenario: Explicit assignment beats provider link
- **WHEN** Garmin links an activity to gear but a local assignment or unassignment exists
- **THEN** the explicit local decision takes precedence without inferring a favorite bicycle or shoe.

#### Scenario: Bounded lists and incomplete history
- **WHEN** assignment display exceeds its list bound or provider history is incomplete/stale
- **THEN** usage still counts eligible known assignments, the list avoids splitting one activity's gear and incomplete coverage remains explicit.

#### Scenario: Sessions from any provider
- **WHEN** a Garmin- or Wahoo-only session is assigned or linked by a Garmin gear item, and a bundled Intervals.icu and Garmin session is assigned
- **THEN** each counts once in usage, hours, distance and maintenance; the bundled session's assignment stays keyed by its Intervals.icu id, so earlier assignments still apply.

Evidence: `backend/athlete/equipment.py:EquipmentService.assign`, `backend/athlete/equipment.py:EquipmentService.read`, `backend/athlete/equipment.py:_effective_assignments`, `backend/athlete/equipment.py:_assignment_list`; `tests/test_training_record_features.py:test_equipment_assignment_is_explicit_and_unassignable`, `tests/test_training_record_features.py:test_explicit_assignment_and_unassignment_beat_the_garmin_link`, `tests/test_training_record_features.py:test_assignment_list_limit_keeps_activities_whole`, `tests/test_training_record_features.py:test_assignment_list_is_bounded_but_usage_counts_every_link`; `tests/test_activity_reference.py:test_equipment_assignment_resolves_the_reference_at_the_boundary`; `tests/test_equipment_canonical_sessions.py:test_wahoo_only_session_counts_in_usage_hours_distance_and_maintenance`, `tests/test_equipment_canonical_sessions.py:test_garmin_gear_links_the_garmin_only_session_and_the_bundled_one`, `tests/test_equipment_canonical_sessions.py:test_bundled_session_counts_once_under_its_intervals_key`, `tests/test_equipment_canonical_sessions.py:test_assignment_stored_under_an_intervals_id_still_applies`.
