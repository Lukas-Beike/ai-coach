## ADDED Requirements

### Requirement: CS13 Completed races link to stored competitions
The system SHALL link each stored competition to the completed sessions of its local date and sport when it reads activity summaries, without storing the link, so consumers see which session was the race.

#### Scenario: Provider races are linked
- **WHEN** a session with purpose race starts on a competition's local date in its sport
- **THEN** its summary carries that `competition_id`; other sessions of the day stay unlinked.

#### Scenario: A competition marks its best candidate as a race hint
- **WHEN** no session of the competition's date and sport has purpose race
- **THEN** the session that starts nearest the competition's local start time, else the longest, else the earliest, gets purpose race with source "Lokale Wettkämpfe" and the `competition_id`.

#### Scenario: No link across sports or for commutes
- **WHEN** a session has another sport, another local date, or purpose commute, warm-up or cool-down, or the competition's sport is unsupported
- **THEN** the session is not linked and keeps its own purpose.

Detailed contract: a session links to at most one competition (competitions in date then id order); unlinking by athlete marking is not yet implemented.

Evidence: `backend/activities/session_purpose.py:with_competitions`, `backend/sync/canonical_read_selector.py:activity_summaries`, `backend/db/repositories.py:CompetitionRepository.between`; `tests/test_session_purpose.py`.
