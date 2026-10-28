# Proposal

## Why

Yazio food lookup failed with a sanitized authentication error in the supplied diagnostics, while the connections screen has no Yazio connection status. The current error combines several upstream rejection causes, so the evidence does not establish which credential or client version failed.

## What Changes

- Investigate and correct the supported Yazio authentication or request compatibility issue using reproducible, sanitized evidence; do not assume the recorded error identifies its cause.
- Add a Yazio connection card and an explicit connection check with honest configuration, unchecked, successful, and safe failure states.
- Distinguish actionable failure categories where reliably supported without exposing provider response bodies or credentials, while preserving existing lookup fallback and rate limits.
- Document operation and verify the backend, UI, security, and PWA behavior with mocked providers and isolated fixtures.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `provider-connections`: Yazio connection checking and safe, meaningful connection status.
- `food-catalog-and-meal-library`: reliable, bounded Yazio authentication and sanitized failure classification while preserving fallback.

## Impact

The Yazio provider adapter and nutrition assembly, authenticated HTTP routes, provider settings and connections UI, diagnostics, tests, PWA assets and README may be affected. The integration remains read-only, tokens remain in memory, and no live account or data migration is required for tests. Inspected baseline: `c6ddecc8`; relevant evidence includes `backend/providers/yazio.py`, `backend/nutrition/food_database.py`, `backend/provider_credentials.py`, `public/provider-connections.js`, `public/index.html`, `tests/test_yazio.py`, and `tests/test_food_lookup_chain.py`. The exact upstream rejection and live compatibility remain unverified.
