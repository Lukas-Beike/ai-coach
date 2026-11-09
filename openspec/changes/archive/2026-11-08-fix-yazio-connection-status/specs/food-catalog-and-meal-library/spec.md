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

Evidence: `backend/providers/yazio.py::YazioClient._grant_rejected` (login 400/401/403 stays one ambiguous `food_database_auth_failed`), `backend/providers/yazio.py::YazioClient._raise_http_error` (only a bounded `version_blocked` body on a product request becomes `food_database_version_blocked`), `backend/nutrition/food_database.py::FoodDatabaseService._chain_search` (notices, fallback); `tests/test_yazio.py::YazioClientTests.test_rejected_login_pauses_further_attempts_without_leaking`, `tests/test_yazio.py::YazioClientTests.test_recognized_version_block_is_safe_and_distinct`, `tests/test_yazio.py::YazioClientTests.test_truncated_forbidden_response_is_sanitized`, `tests/test_food_lookup_chain.py::LookupChainTests.test_version_block_is_reported_while_fallback_remains_available`, `tests/test_food_lookup_chain.py::LookupChainTests.test_text_chain_names_rejected_yazio_credentials`. The incident's upstream response and actual cause stay unverified; no live account was used.
