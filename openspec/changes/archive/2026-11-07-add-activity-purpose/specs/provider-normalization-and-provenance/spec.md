## ADDED Requirements

### Requirement: Activity purpose
The system SHALL classify why an activity was done as training, race, commute, warm-up or cool-down from Garmin's activity event type and stored competitions, never from Intervals.icu fields, and carry it with its source label on the session summary and the Coach activity list.

#### Scenario: Garmin event types name race and commute
- **WHEN** a Garmin activity list entry (unofficial SDK or Personal API) has `eventType.typeKey` `race` or `transportation`
- **THEN** its record has purpose race or commute; any other event type, a missing event type or a missing key leaves the purpose unset, and a key that is not text is one mapping issue.

#### Scenario: A race in any record wins
- **WHEN** the records of one session report different purposes
- **THEN** the session purpose is race if any record says race, else the first purpose in derived order, and `sources.purpose` names that record's provider.

#### Scenario: Intervals.icu classification is not read
- **WHEN** an Intervals.icu activity carries `sub_type`, `race` or `commute`
- **THEN** its record has no purpose.

Detailed contract: the purpose is stored in the record details (`purpose`), so no migration is needed; an unknown stored value is ignored on read. The Garmin activity mapper version 17 replays stored payloads. The Coach activity list adds `purpose_label` (Training, Wettkampf, Pendeln, Einfahren, Ausfahren). Warm-up and cool-down are reserved for the athlete's own marking, which is not yet implemented.

Evidence: `backend/canonical/vocabulary.py:ActivityPurpose`, `backend/providers/garmin_activity_mapping.py:_purpose`, `backend/activities/session_purpose.py:session_purpose`, `backend/db/canonical_store.py:activity_summary_values`, `backend/coach/context.py:compact_coach_activity`; `tests/test_session_purpose.py`, `tests/test_coach_activity_summary_parity.py`.
