## Why

Issue #2355 makes the Claude API (Anthropic Messages API) a selectable model provider next to OpenAI. Its first part is the credential surface: the athlete needs a place to store an Anthropic API key, and optionally a compatible base URL, before any Claude request can run. This part ships that surface on its own; the adapter and the provider selection follow in later parts of #2355.

## What Changes

- New server-side configuration `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` (default `https://api.anthropic.com`), overridable from the PWA and stored encrypted like the other provider credentials. The base URL is validated as strictly as `OPENAI_BASE_URL` and changing it needs the app password again.
- New card "Claude (Anthropic)" directly below OpenAI under Mehr › Anbindungen with API key, base URL, save and an explicit read-only connection check (one `GET /v1/models`).
- The key is a secret everywhere: never returned by status, never in logs, diagnostics, exports, browser state or Coach context.
- No model traffic goes to Anthropic yet; OpenAI stays the only model provider in this part.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `provider-connections`: adds the optional Anthropic configuration and its explicit connection check.

## Impact

- `backend/config.py`, `backend/provider_credentials.py`, `backend/observability.py`, `backend/providers/connection_check_probes.py`, `server.py` (probe wiring).
- `public/index.html`, `public/provider-connections.js`, `public/views.js`.
- `docs/setup.md` / configuration docs.
- Tests: `tests/test_provider_credentials.py`, `tests/test_provider_connection_checks.py`, `tests/test_observability.py`, `tests/provider-connections.test.cjs`.
