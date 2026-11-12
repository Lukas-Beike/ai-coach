## 1. Configuration and credentials

- [ ] 1.1 Add `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` (validated, default official endpoint) to the configuration and the stored credential fields (key secret, base URL visible and re-auth); verify with `tests/test_config.py` and `tests/test_provider_credentials.py`.
- [ ] 1.2 Treat the Anthropic key as a configured secret in redaction and diagnostics; verify with `tests/test_observability.py`.

## 2. Connection check and card

- [ ] 2.1 Add the read-only Anthropic probe (one model listing with `x-api-key` and `anthropic-version`) to the provider checks; verify with `tests/test_provider_connection_checks.py`.
- [ ] 2.2 Add the Claude (Anthropic) card below OpenAI with key, base URL, save and check; verify with `tests/provider-connections.test.cjs` and the affected Playwright specs on mobile, tablet-landscape and desktop where available, recording unavailable runs as gaps.
- [ ] 2.3 Document the new configuration in README/docs; verify by reading the changed docs.

## 3. Verification

- [ ] 3.1 Run `python tests/run_tests.py --changed`, compileall, the quality baseline and `node --test tests/*.cjs`; run strict OpenSpec validation for this change.
