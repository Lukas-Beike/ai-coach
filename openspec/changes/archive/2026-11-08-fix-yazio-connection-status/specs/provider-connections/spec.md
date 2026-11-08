# Spec Delta

## ADDED Requirements

### Requirement: Yazio connection status and explicit check
The system SHALL present Yazio on the connections screen, distinguish missing configuration, an unchecked configuration, a successful check, and a safely classified failure, and provide an explicit authenticated connection check. Status SHALL describe the last check rather than promise current availability.

#### Scenario: Missing configuration
- **WHEN** any required Yazio credential is absent
- **THEN** the card reports not configured and a check makes no upstream request.

#### Scenario: Configured but not checked
- **WHEN** configuration is complete but has not been checked for the current credentials
- **THEN** the card reports that the connection has not been checked and does not claim it is connected.

#### Scenario: Explicit check succeeds
- **WHEN** the athlete requests a check and Yazio accepts the current authentication
- **THEN** the card reports successful authentication and the time of the check; no food or diary record is changed.

#### Scenario: Authentication or service failure
- **WHEN** a check is rejected, rate-limited, or encounters a transient or unexpected provider failure
- **THEN** the card shows a safe actionable category and does not claim success or reveal provider responses, account values, or tokens.

#### Scenario: Credentials change or server restarts
- **WHEN** effective Yazio credentials change or the server restarts
- **THEN** an old successful result is not presented as a current verification; complete configuration is shown as unchecked.

#### Scenario: Passive status refresh
- **WHEN** the connections screen is loaded or polled
- **THEN** it reads local status without starting a Yazio network request.

#### Scenario: Unauthorized check
- **WHEN** a check request lacks an authenticated session or valid CSRF protection
- **THEN** it is rejected before contacting Yazio.

Evidence: `backend/providers/yazio.py::YazioClient.connection_status`, `backend/providers/yazio.py::YazioClient.check_connection`, `backend/http_api/nutrition.py::NutritionGetRoutes.handle`, `backend/http_api/nutrition.py::NutritionPostRoutes._check_yazio`, `public/provider-connections.js::checkYazioConnection`, `public/provider-connections.js::loadYazioStatus`; `tests/test_yazio.py::YazioConnectionTests.test_passive_status_check_and_credential_change`, `tests/test_yazio.py::YazioConnectionTests.test_check_uses_password_grant_and_restart_is_unchecked`, `tests/test_yazio.py::YazioConnectionTests.test_inflight_result_is_discarded_after_credential_replacement`, `tests/test_yazio_connection_routes.py`, `tests/provider-connections.test.cjs`, `e2e/yazio-connection.spec.js::@responsive Yazio shows a checked login and refreshes its local status`. The check reports `not_configured`, `unchecked`, `success`, `auth_failed`, `rate_limited` or `unavailable`.
