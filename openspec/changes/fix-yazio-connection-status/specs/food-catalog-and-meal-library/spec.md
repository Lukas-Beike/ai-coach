# Spec Delta

## ADDED Requirements

### Requirement: Yazio authentication failure is honestly classified
The system SHALL classify Yazio authentication and compatibility failures only as precisely as supported by safe evidence, and SHALL avoid presenting ambiguous rejection as a proven incorrect password or client version.

#### Scenario: Ambiguous authentication rejection
- **WHEN** an upstream rejection could result from account credentials, application credentials, or an unsupported client
- **THEN** the athlete receives an actionable ambiguous authentication failure and no unsupported cause is asserted.

#### Scenario: Reliably identified client version rejection
- **WHEN** a supported, safely recognized response establishes a client version rejection
- **THEN** the athlete is told that the client version needs attention without exposing the provider response.

#### Scenario: Working authentication and lookup
- **WHEN** a compatible provider accepts the configured credentials and returns a valid food response
- **THEN** Yazio lookup can return the normalized food with its existing source provenance and no remote write.

#### Scenario: Failed check or lookup
- **WHEN** authentication fails or the provider is unavailable
- **THEN** existing local and alternative food sources remain usable and retry/backoff limits remain effective.

Evidence baseline: `backend/providers/yazio.py`, `backend/nutrition/food_database.py`, `tests/test_yazio.py`, `tests/test_food_lookup_chain.py`. The supplied diagnostic records `food_database_auth_failed`; the upstream response and actual cause are unverified.
