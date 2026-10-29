# Spec Delta

## ADDED Requirements

### Requirement: Uniform explicit provider connection checks
The system SHALL offer an explicit read-only connection check on the OpenAI, Intervals.icu, Garmin, Wahoo and Open-Meteo cards and present its last result in a line separate from configuration and synchronization state. A result SHALL describe the last check rather than promise current availability.

#### Scenario: Missing configuration
- **WHEN** the provider is not configured, or Wahoo or Garmin is not connected
- **THEN** the card reports not configured and a check makes no provider request.

#### Scenario: Configured but not checked
- **WHEN** the provider is configured and has not been checked for the current credentials
- **THEN** the card reports the connection as not checked and does not claim it is connected.

#### Scenario: Explicit check succeeds
- **WHEN** the athlete requests a check and the provider accepts the current credentials
- **THEN** the card reports success with the check time and no remote data is changed.

#### Scenario: Distinguishable failures
- **WHEN** a check is rejected, rate limited, unreachable, or the endpoint cannot answer the probe
- **THEN** the card shows the matching safe category with provider-specific recovery guidance and reveals no provider response, credential or token.

#### Scenario: Connection health is not sync freshness
- **WHEN** a sync succeeded earlier or later than a check
- **THEN** the sync label and the check result are shown separately and neither changes the other.

#### Scenario: Credentials change or restart
- **WHEN** the effective credentials of a provider change or the server restarts
- **THEN** an earlier result is not shown as current and a configured provider is reported as not checked.

#### Scenario: Result completes after a change
- **WHEN** credentials change while a check is in flight
- **THEN** the late result is discarded.

#### Scenario: Passive status
- **WHEN** the connections screen is loaded or polled, or unrelated settings are saved
- **THEN** it reads local state without any provider request and keeps existing results.

#### Scenario: Unauthorized check
- **WHEN** a check lacks an authenticated session or valid CSRF protection
- **THEN** it is rejected before any provider request.

#### Scenario: Garmin never logs in with credentials
- **WHEN** the Garmin check runs
- **THEN** it authenticates with the stored tokens only, and without them it reports not configured; it never uses e-mail and password.

#### Scenario: Providers without a check
- **WHEN** the card is the shared calendar or Open Food Facts
- **THEN** no check action is offered because a check would equal the full feed fetch or the provider needs no credentials.
