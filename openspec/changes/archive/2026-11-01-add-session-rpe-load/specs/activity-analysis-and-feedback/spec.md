## ADDED Requirements

### Requirement: Session RPE rating time and session load in the detail
The system SHALL store when the athlete last set a feedback row's session RPE, keep it while the RPE stays the same and clear it with the RPE; ratings stored before schema v18 SHALL keep an unknown rating time. The activity detail document SHALL carry the session's session-RPE load, and the PWA SHALL offer the RPE as a 0–10 half-point selection with the CR-10 anchors.

#### Scenario: Rating time follows the RPE
- **WHEN** the athlete saves a new RPE, then saves only notes, then clears the RPE
- **THEN** the rating time is set, kept, then cleared; undo restores the recorded rating time with the row.

#### Scenario: Detail shows the load
- **WHEN** the activity detail of a session with local RPE 6.5 and 62 elapsed minutes is opened or its feedback is saved
- **THEN** it shows `403 AU · RPE 6,5 (Athletenfeedback) × 62 min`; a session without a summary shows no load line.

Evidence: `backend/db/repositories.py:ActivityFeedbackRepository.upsert`, `backend/performance/detail_envelope.py:DetailEnvelopeReader`, `public/activity-details.js:rpeSelect`; `tests/test_db_feedback_rating_time_migration.py::test_upgraded_feedback_records_its_rating_time_only_on_an_rpe_change`, `tests/test_detail_envelope.py`, `e2e/activity-details.spec.js`.
