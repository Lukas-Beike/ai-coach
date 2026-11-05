## ADDED Requirements

### Requirement: Athlete session corrections
The system SHALL let the athlete confirm a canonical session's bundle, split one provider copy into its own session, and merge two live sessions, from the activity detail view or through local Coach tools. Each correction SHALL mark the resulting sessions athlete-confirmed, record a change-history receipt whose undo restores the touched session rows, and change no provider record, provider data or feedback row.

#### Scenario: Confirm a bundle
- **WHEN** the athlete confirms a session that bundles several provider copies
- **THEN** it is stored as athlete-confirmed with link kind `confirmed`, and later session linking never merges or splits it.

#### Scenario: Split a provider copy
- **WHEN** the athlete splits one provider copy off a bundle
- **THEN** that copy becomes its own active, athlete-confirmed session, the remaining copies stay bundled under their oldest session, later syncs do not merge them again, and feedback stays with the session it was written for.

#### Scenario: Merge two sessions
- **WHEN** the athlete merges two live sessions that hold no two active records of one provider and recording origin
- **THEN** the younger becomes an alias of the older one, which is athlete-confirmed with link kind `confirmed`; a merge that would join two records of one provider and origin is refused with a conflict.

#### Scenario: Undo a correction
- **WHEN** the athlete undoes a correction's receipt while the touched sessions are unchanged since
- **THEN** the recorded session rows are restored; a later change to them makes the undo conflict instead.

#### Scenario: Feedback written before another copy arrives
- **WHEN** feedback is saved on a Garmin-only session and the Intervals.icu copy is linked later
- **THEN** the feedback resolves through either id because it stays bound to the session it was written for.

Detailed contract: the activity detail response carries `session_bundle` with the live session id, link kind, confirmation, the provider copies (`session_id`, provider label, recording origin, start, duration) and the live sessions of the same local date as merge candidates. A correction touching more than 16 session rows is refused so its receipt stays restorable.

Evidence: `backend/activities/session_corrections.py:SessionCorrectionService`, `backend/http_api/feedback_post.py:FeedbackPostRoutes`, `public/activity-details.js:renderBundle`; `tests/test_session_corrections.py`.
