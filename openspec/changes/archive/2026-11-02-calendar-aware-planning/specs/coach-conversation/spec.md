## ADDED Requirements

### Requirement: Clarify uncertain calendar impact
The planning playbook SHALL direct the Coach to ask whether to train and whether to reduce intensity when an event creates material uncertainty, and to use the athlete's answer. An ordinary event alone SHALL not imply a cancellation or reduction.

#### Scenario: Uncertain busy day
- **WHEN** a calendar event leaves a material training decision unclear
- **THEN** the Coach asks before making that decision and groups questions where practical.

Evidence: `backend/coach/playbooks.py:playbook_for`; `tests/test_calendar_planning.py:test_plan_playbook_requests_clarification`; `tests/test_coach_dialogue.py:test_calendar_clarification_then_easy_workout`. The scripted dialogue proves mechanics, not natural-language model reliability.
