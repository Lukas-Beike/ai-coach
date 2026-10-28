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

Evidence baseline: `backend/provider_credentials.py`, `public/provider-connections.js`, `public/index.html`, `tests/test_provider_credentials.py`, `tests/provider-connections.test.cjs`; explicit check and its tests do not yet exist.
