# Spec Delta

## ADDED Requirements

### Requirement: Optional Yazio configuration
The system SHALL treat Yazio as an optional read-only food source configured by server-side environment values, with account email, password and application client identifiers overridable from the PWA provider settings. Stored values SHALL take precedence, clearing them SHALL restore the environment value, and Yazio SHALL be configured only when all four values exist. Status SHALL report only presence and source, never a value.

#### Scenario: Stored override
- **WHEN** the athlete saves Yazio credentials in the provider settings
- **THEN** lookups use them without a restart and status reports source "db" and configured without returning any value.

#### Scenario: Incomplete configuration
- **WHEN** any of email, password, client id or client secret is missing
- **THEN** Yazio is reported unconfigured and is never contacted.

#### Scenario: Secret handling
- **WHEN** logs, diagnostics, exports or Coach context are produced
- **THEN** Yazio credentials and tokens are absent from them.
