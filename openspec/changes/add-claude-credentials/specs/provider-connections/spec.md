## ADDED Requirements

### Requirement: Optional Anthropic configuration
The system SHALL accept an Anthropic API key and base URL from server-side environment values, overridable from the PWA and stored encrypted. Stored values SHALL take precedence and clearing them SHALL restore the environment value. The base URL SHALL default to the official endpoint and be validated like the OpenAI base URL; setting it SHALL need the app password. Status SHALL report the key's presence and source only, never its value.

#### Scenario: Stored override
- **WHEN** the athlete saves an Anthropic API key in the Claude (Anthropic) card
- **THEN** it takes effect without a restart and status reports source "db" and configured without returning the key.

#### Scenario: Default and environment base URL
- **WHEN** no base URL is stored or set in the environment
- **THEN** the official Anthropic endpoint is used; an environment value applies when nothing is stored.

#### Scenario: Unsafe base URL
- **WHEN** a base URL uses plain HTTP to a non-loopback host or carries credentials, a query, a fragment or dot segments
- **THEN** the save is rejected without writing, and an invalid stored value is ignored at load in favor of the environment value.

#### Scenario: Base URL needs the app password
- **WHEN** the athlete sets the base URL without the app password
- **THEN** the save is rejected without writing.

#### Scenario: Secret handling
- **WHEN** logs, diagnostics, exports, browser state or Coach context are produced
- **THEN** the Anthropic API key is absent from them.

Evidence: `backend/config.py:load_config`, `backend/config.py:validated_base_url`, `backend/provider_credentials.py:SECRET_FIELDS`, `backend/provider_credentials.py:REAUTH_FIELDS`, `backend/observability.py:config_secret_values`; `tests/test_provider_credentials.py`, `tests/test_config.py`, `tests/test_observability.py`.

### Requirement: Anthropic connection check
The system SHALL offer the explicit read-only connection check of the uniform provider checks on the Claude (Anthropic) card. The check SHALL send one model-listing request with the configured key and base URL, store nothing from the answer, and report rejected credentials with guidance to check the key and base URL.

#### Scenario: Check without a key
- **WHEN** no Anthropic API key is configured
- **THEN** the card reports not configured and a check makes no provider request.

#### Scenario: Check succeeds
- **WHEN** the athlete checks the card and Anthropic accepts the key
- **THEN** the card reports success with the check time and nothing from the answer is stored.

#### Scenario: Rejected key or unsupported endpoint
- **WHEN** the key is rejected, or a compatible endpoint does not implement the model listing
- **THEN** the card shows the safe failure category with key and base URL guidance, or reports that the endpoint does not support the check.

Evidence: `backend/providers/connection_check_probes.py:build_probes`, `public/index.html` (`connection-anthropic`), `public/provider-connections.js:CREDENTIAL_FORMS`; `tests/test_provider_connection_checks.py`, `tests/provider-connections.test.cjs`.
