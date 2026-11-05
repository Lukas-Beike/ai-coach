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
